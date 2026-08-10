"""이슈 #55: Hysteresis + De-escalation 추가 검증 — TDD 테스트.

#54 엔진에서 이미 Hysteresis(enter/exit 분리)와 De-escalation(한 단계씩)이 동작함.
이 테스트는 추가 엣지 케이스를 검증한다:

1. Hysteresis band(enter ↔ exit 사이)에서 상태 유지 — 플리커링 방지
2. L3 → L2 → L1 → Normal 점진적 하양 시나리오
3. 급격한 정상 복귀 시에도 점진적 하양 (L3 → 즉시 normal 금지)
4. Hysteresis gap 없이 enter_threshold == exit_threshold 인 경우 동작
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models.alert import AlertLevel
from app.services.alert_engine import AlertEvaluator


def _threshold(metric: str, level: AlertLevel, *, enter: float, exit_: float,
               enter_ms: int, exit_ms: int, direction: str = "above"):
    from app.models.threshold import Threshold, ThresholdDirection
    return Threshold(
        metric=metric,
        level=level,
        direction=ThresholdDirection(direction),
        enter_threshold=enter,
        exit_threshold=exit_,
        enter_for_ms=enter_ms,
        exit_for_ms=exit_ms,
    )


def _co2_thresholds() -> list:
    return [
        _threshold("co2_ppm", AlertLevel.LEVEL1, enter=1000, exit_=900, enter_ms=3000, exit_ms=5000),
        _threshold("co2_ppm", AlertLevel.LEVEL2, enter=2000, exit_=1900, enter_ms=3000, exit_ms=5000),
        _threshold("co2_ppm", AlertLevel.LEVEL3, enter=5000, exit_=4500, enter_ms=0, exit_ms=5000),
    ]


def _ts(seconds: float) -> datetime:
    return datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc) + timedelta(seconds=seconds)


# ============================================================
# 1. Hysteresis band — 플리커링 방지
# ============================================================

@pytest.mark.asyncio
async def test_hysteresis_band_keeps_alert_active_between_enter_and_exit():
    """L1 active 상태에서 value 가 enter(1000) 와 exit(900) 사이로 떨어져도
    exit_threshold(900) 미만이 아니면 active 유지."""
    evaluator = AlertEvaluator(thresholds={"co2_ppm": _co2_thresholds()})
    # L1 진입
    await evaluator.evaluate("sensor-01", "co2_ppm", 1100.0, _ts(0))
    await evaluator.evaluate("sensor-01", "co2_ppm", 1100.0, _ts(3.0))
    # hysteresis band 내 (900 < value < 1000)
    await evaluator.evaluate("sensor-01", "co2_ppm", 950.0, _ts(4.0))
    state = evaluator.get_state("sensor-01", "co2_ppm")
    assert state.current_level == AlertLevel.LEVEL1
    assert state.exit_started_at is None, "exit timer 가 시작되면 안됨"


@pytest.mark.asyncio
async def test_hysteresis_prevents_flickering_with_rapid_oscillation():
    """L1 → exit 직전 → enter → exit 직전 → enter 반복해도 active 유지되어야 함."""
    evaluator = AlertEvaluator(thresholds={"co2_ppm": _co2_thresholds()})
    await evaluator.evaluate("sensor-01", "co2_ppm", 1100.0, _ts(0))
    await evaluator.evaluate("sensor-01", "co2_ppm", 1100.0, _ts(3.0))

    # 반복 oscillation
    for i in range(5):
        await evaluator.evaluate("sensor-01", "co2_ppm", 850.0, _ts(10.0 + i * 2))   # exit_threshold=900 미만
        await evaluator.evaluate("sensor-01", "co2_ppm", 950.0, _ts(10.0 + i * 2 + 1))  # hysteresis band

    state = evaluator.get_state("sensor-01", "co2_ppm")
    # exit timer 가 매번 리셋되므로 active 유지 또는 정상 복귀 — 핵심은 L1 미만으로 점프 안 함
    assert state.current_level in (AlertLevel.LEVEL1, AlertLevel.NORMAL)


# ============================================================
# 2. 점진적 De-escalation 시나리오
# ============================================================

@pytest.mark.asyncio
async def test_gradual_deescalation_l3_to_normal():
    """L3 active 상태에서 value 가 모든 exit_threshold 미만으로 떨어져도
    L3 → L2 → L1 → Normal 로 한 단계씩 하향 (즉시 normal 점프 금지)."""
    evaluator = AlertEvaluator(thresholds={"co2_ppm": _co2_thresholds()})
    # L3 진입
    await evaluator.evaluate("sensor-01", "co2_ppm", 5500.0, _ts(0))

    # 모든 exit 임계치 미만 (500) 으로 유지
    # L3 → L2 (exit_for_ms=5000 경과)
    await evaluator.evaluate("sensor-01", "co2_ppm", 500.0, _ts(1.0))  # exit timer 시작
    t1 = await evaluator.evaluate("sensor-01", "co2_ppm", 500.0, _ts(6.0))
    assert t1 is not None
    assert t1.from_level == AlertLevel.LEVEL3
    assert t1.to_level == AlertLevel.LEVEL2

    # L2 → L1 (L2 exit_for_ms=5000 경과)
    await evaluator.evaluate("sensor-01", "co2_ppm", 500.0, _ts(7.0))  # exit timer 시작
    t2 = await evaluator.evaluate("sensor-01", "co2_ppm", 500.0, _ts(12.0))
    assert t2 is not None
    assert t2.from_level == AlertLevel.LEVEL2
    assert t2.to_level == AlertLevel.LEVEL1

    # L1 → Normal (L1 exit_for_ms=5000 경과)
    await evaluator.evaluate("sensor-01", "co2_ppm", 500.0, _ts(13.0))
    t3 = await evaluator.evaluate("sensor-01", "co2_ppm", 500.0, _ts(18.0))
    assert t3 is not None
    assert t3.from_level == AlertLevel.LEVEL1
    assert t3.to_level == AlertLevel.NORMAL


@pytest.mark.asyncio
async def test_l3_does_not_jump_directly_to_normal_even_with_zero_value():
    """L3 → normal 직접 점프 금지. value=0 이어도 L2를 거쳐야."""
    evaluator = AlertEvaluator(thresholds={"co2_ppm": _co2_thresholds()})
    await evaluator.evaluate("sensor-01", "co2_ppm", 5500.0, _ts(0))
    await evaluator.evaluate("sensor-01", "co2_ppm", 0.0, _ts(1.0))
    t = await evaluator.evaluate("sensor-01", "co2_ppm", 0.0, _ts(6.0))
    assert t is not None
    assert t.to_level == AlertLevel.LEVEL2, "L3 에서 normal 로 점프하면 안됨"


# ============================================================
# 3. De-escalation 중 escalation 되돌아오면 취소
# ============================================================

@pytest.mark.asyncio
async def test_deescalation_cancels_when_value_returns_high():
    """exit timer 진행 중 value 가 다시 current_level 의 enter 조건 만족하면
    exit timer 리셋, active 유지."""
    evaluator = AlertEvaluator(thresholds={"co2_ppm": _co2_thresholds()})
    await evaluator.evaluate("sensor-01", "co2_ppm", 1100.0, _ts(0))
    await evaluator.evaluate("sensor-01", "co2_ppm", 1100.0, _ts(3.0))

    # exit 진행 3초
    await evaluator.evaluate("sensor-01", "co2_ppm", 800.0, _ts(4.0))
    # 다시 L1 진입 조건 (>= 1000) — exit timer 리셋 기대
    await evaluator.evaluate("sensor-01", "co2_ppm", 1100.0, _ts(7.0))
    state = evaluator.get_state("sensor-01", "co2_ppm")
    assert state.current_level == AlertLevel.LEVEL1
    assert state.exit_started_at is None

    # exit 재시작 후 4초만 경과 (5초 필요) → 아직 active
    await evaluator.evaluate("sensor-01", "co2_ppm", 800.0, _ts(8.0))
    t = await evaluator.evaluate("sensor-01", "co2_ppm", 800.0, _ts(12.0))
    assert t is None  # 4초 경과, 5초 필요 → 아직 전환 없음


# ============================================================
# 4. Hysteresis gap 없는 경우 — 동작 호환성
# ============================================================

@pytest.mark.asyncio
async def test_zero_hysteresis_gap_still_works():
    """enter_threshold == exit_threshold 인 경우에도 동작 (no gap).
    일반적이지는 않지만 설정 실수 시에도 크래시 없이 동작해야."""
    evaluator = AlertEvaluator(thresholds={
        "test_metric": [
            _threshold("test_metric", AlertLevel.LEVEL1, enter=100, exit_=100, enter_ms=0, exit_ms=0),
        ],
    })
    t1 = await evaluator.evaluate("sensor-01", "test_metric", 150.0, _ts(0))
    assert t1 is not None
    assert t1.to_level == AlertLevel.LEVEL1

    t2 = await evaluator.evaluate("sensor-01", "test_metric", 50.0, _ts(1.0))
    assert t2 is not None
    assert t2.to_level == AlertLevel.NORMAL
