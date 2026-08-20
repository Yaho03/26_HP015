"""이슈 #54: 시간 기반 경보 판정 — TDD 테스트.

검증 범위:
1. AlertLevel, AlertState, AlertTransition 모델 정의
2. 임계값 미만 → no transition
3. 임계값 초과 + enter_for_ms 미경과 → no transition (타이머 시작)
4. 임계값 초과 + enter_for_ms 경과 → ENTER transition
5. enter_for_ms=0 (Level 3) → 즉시 ENTER
6. exit_threshold 회귀 + exit_for_ms 경과 → EXIT 한 단계 하향
7. 값이 oscillation → 타이머 리셋
8. 여러 노드/메트릭 독립 추적
9.escalation L1→L2→L3 순차
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models.alert import AlertLevel, AlertState, AlertTransition
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
# 1. 모델 정의 검증
# ============================================================

def test_alert_level_values():
    assert AlertLevel.NORMAL.value == "normal"
    assert AlertLevel.LEVEL1.value == "level1_caution"
    assert AlertLevel.LEVEL2.value == "level2_warning"
    assert AlertLevel.LEVEL3.value == "level3_critical"


def test_alert_state_default_is_normal():
    state = AlertState()
    assert state.current_level == AlertLevel.NORMAL
    assert state.enter_started_at is None
    assert state.exit_started_at is None


# ============================================================
# 2. AlertEvaluator 초기 동작
# ============================================================

def test_evaluator_initial_state_is_normal():
    evaluator = AlertEvaluator(thresholds={"co2_ppm": _co2_thresholds()})
    state = evaluator.get_state("sensor-01", "co2_ppm")
    assert state.current_level == AlertLevel.NORMAL


@pytest.mark.asyncio
async def test_value_below_threshold_no_transition():
    evaluator = AlertEvaluator(thresholds={"co2_ppm": _co2_thresholds()})
    transition = await evaluator.evaluate("sensor-01", "co2_ppm", 500.0, _ts(0))
    assert transition is None


@pytest.mark.asyncio
async def test_first_crossing_starts_enter_timer_no_immediate_transition():
    """첫 임계값 초과는 enter_started_at 만 갱신, transition 없음 (enter_for_ms > 0)."""
    evaluator = AlertEvaluator(thresholds={"co2_ppm": _co2_thresholds()})
    transition = await evaluator.evaluate("sensor-01", "co2_ppm", 1100.0, _ts(0))
    assert transition is None
    state = evaluator.get_state("sensor-01", "co2_ppm")
    assert state.current_level == AlertLevel.NORMAL
    assert state.enter_started_at == _ts(0)


@pytest.mark.asyncio
async def test_enter_after_duration():
    """enter_for_ms 경과 후 ENTER transition."""
    evaluator = AlertEvaluator(thresholds={"co2_ppm": _co2_thresholds()})
    await evaluator.evaluate("sensor-01", "co2_ppm", 1100.0, _ts(0))
    transition = await evaluator.evaluate("sensor-01", "co2_ppm", 1100.0, _ts(3.0))
    assert transition is not None
    assert transition.from_level == AlertLevel.NORMAL
    assert transition.to_level == AlertLevel.LEVEL1
    state = evaluator.get_state("sensor-01", "co2_ppm")
    assert state.current_level == AlertLevel.LEVEL1
    assert state.enter_started_at is None


@pytest.mark.asyncio
async def test_enter_resets_when_value_returns_below():
    """임계값 초과 후 다시 정상 복귀 시 enter_started_at 리셋."""
    evaluator = AlertEvaluator(thresholds={"co2_ppm": _co2_thresholds()})
    await evaluator.evaluate("sensor-01", "co2_ppm", 1100.0, _ts(0))
    await evaluator.evaluate("sensor-01", "co2_ppm", 500.0, _ts(1.0))
    state = evaluator.get_state("sensor-01", "co2_ppm")
    assert state.enter_started_at is None
    assert state.current_level == AlertLevel.NORMAL


@pytest.mark.asyncio
async def test_level3_immediate_enter():
    """Level 3 (enter_for_ms=0) 는 즉시 ENTER."""
    evaluator = AlertEvaluator(thresholds={"co2_ppm": _co2_thresholds()})
    transition = await evaluator.evaluate("sensor-01", "co2_ppm", 5500.0, _ts(0))
    assert transition is not None
    assert transition.to_level == AlertLevel.LEVEL3
    assert transition.from_level == AlertLevel.NORMAL


# ============================================================
# 3. Escalation (순차)
# ============================================================

@pytest.mark.asyncio
async def test_escalation_l1_to_l2():
    """Level 1 active 상태에서 Level 2 임계값 초과 + enter_for_ms 경과 → L2 ENTER."""
    evaluator = AlertEvaluator(thresholds={"co2_ppm": _co2_thresholds()})
    # L1 진입
    await evaluator.evaluate("sensor-01", "co2_ppm", 1100.0, _ts(0))
    await evaluator.evaluate("sensor-01", "co2_ppm", 1100.0, _ts(3.0))
    # L2 임계값 초과 시작
    await evaluator.evaluate("sensor-01", "co2_ppm", 2100.0, _ts(4.0))
    transition = await evaluator.evaluate("sensor-01", "co2_ppm", 2100.0, _ts(7.0))
    assert transition is not None
    assert transition.from_level == AlertLevel.LEVEL1
    assert transition.to_level == AlertLevel.LEVEL2


@pytest.mark.asyncio
async def test_escalation_skips_when_no_duration_required():
    """L1 active 상태에서 L3 (enter_for_ms=0) 임계값 도달 시 즉시 L3."""
    evaluator = AlertEvaluator(thresholds={"co2_ppm": _co2_thresholds()})
    await evaluator.evaluate("sensor-01", "co2_ppm", 1100.0, _ts(0))
    await evaluator.evaluate("sensor-01", "co2_ppm", 1100.0, _ts(3.0))
    transition = await evaluator.evaluate("sensor-01", "co2_ppm", 5500.0, _ts(4.0))
    assert transition is not None
    assert transition.to_level == AlertLevel.LEVEL3


@pytest.mark.asyncio
async def test_lower_level_elapsed_time_not_reused_for_higher_level(monkeypatch):
    """이슈 #108: L1을 향해 쌓인 경과시간이 L3 판정에 재사용되면 안 된다.

    재현 시나리오(이슈 본문과 동일): L1 값이 12초간 지속되다가(L1 자체
    enter_for_ms=15s라 아직 L1 진입 전) 첫 L3 샘플이 들어옴. 수정 전이면
    enter_started_at이 12초 전 그대로라 elapsed(12s) >= L3 enter_for(10s)로
    즉시 L3 전환되던 오탐. 수정 후에는 L3를 향한 타이머가 그 샘플부터 새로
    시작해야 하므로, t+22s(L3 값이 실제로 10초 지속된 시점)에야 전환된다.
    """
    thresholds = {
        "co2_ppm": [
            _threshold("co2_ppm", AlertLevel.LEVEL1, enter=1000, exit_=900, enter_ms=15000, exit_ms=5000),
            _threshold("co2_ppm", AlertLevel.LEVEL3, enter=5000, exit_=4500, enter_ms=10000, exit_ms=5000),
        ]
    }
    evaluator = AlertEvaluator(thresholds=thresholds)

    await evaluator.evaluate("sensor-01", "co2_ppm", 1100.0, _ts(0))
    # 12초 뒤 첫 L3 샘플 — 수정 전이면 여기서 즉시(오탐) 전환됨
    transition = await evaluator.evaluate("sensor-01", "co2_ppm", 5500.0, _ts(12.0))
    assert transition is None, "L1 타이머가 L3 판정에 재사용되어 즉시 전환되면 안 됨(오탐)"

    # L3 타이머가 t=12에 새로 시작했으므로, 그로부터 10초 미만이면 아직 전환 안 됨
    still_none = await evaluator.evaluate("sensor-01", "co2_ppm", 5500.0, _ts(20.0))
    assert still_none is None

    # t=22 (L3 타이머 시작 후 정확히 10초) → 실제로 전환
    transition = await evaluator.evaluate("sensor-01", "co2_ppm", 5500.0, _ts(22.0))
    assert transition is not None
    assert transition.to_level == AlertLevel.LEVEL3


# ============================================================
# 4. De-escalation (한 단계씩)
# ============================================================

@pytest.mark.asyncio
async def test_exit_after_duration_single_step():
    """L1 active 상태에서 exit_threshold 회귀 + exit_for_ms 경과 → NORMAL."""
    evaluator = AlertEvaluator(thresholds={"co2_ppm": _co2_thresholds()})
    # L1 진입
    await evaluator.evaluate("sensor-01", "co2_ppm", 1100.0, _ts(0))
    await evaluator.evaluate("sensor-01", "co2_ppm", 1100.0, _ts(3.0))
    # exit 시작
    await evaluator.evaluate("sensor-01", "co2_ppm", 800.0, _ts(4.0))
    # exit_for_ms (5000ms) 경과
    transition = await evaluator.evaluate("sensor-01", "co2_ppm", 800.0, _ts(9.0))
    assert transition is not None
    assert transition.from_level == AlertLevel.LEVEL1
    assert transition.to_level == AlertLevel.NORMAL


@pytest.mark.asyncio
async def test_l3_exit_goes_to_l2_not_normal():
    """L3 → L2 (한 단계만 하향). L3 → normal 점프 금지."""
    evaluator = AlertEvaluator(thresholds={"co2_ppm": _co2_thresholds()})
    # L3 진입
    await evaluator.evaluate("sensor-01", "co2_ppm", 5500.0, _ts(0))
    # exit 시작 (L3 exit_threshold=4500)
    await evaluator.evaluate("sensor-01", "co2_ppm", 4000.0, _ts(1.0))
    # exit_for_ms (5000ms) 경과 — 여전히 L2 임계값(2000) 이상이므로 L2 로
    transition = await evaluator.evaluate("sensor-01", "co2_ppm", 4000.0, _ts(6.0))
    assert transition is not None
    assert transition.from_level == AlertLevel.LEVEL3
    assert transition.to_level == AlertLevel.LEVEL2


@pytest.mark.asyncio
async def test_exit_resets_when_value_returns_high():
    """exit 시작 후 다시 높은 값 → exit_started_at 리셋, active 유지."""
    evaluator = AlertEvaluator(thresholds={"co2_ppm": _co2_thresholds()})
    await evaluator.evaluate("sensor-01", "co2_ppm", 1100.0, _ts(0))
    await evaluator.evaluate("sensor-01", "co2_ppm", 1100.0, _ts(3.0))
    await evaluator.evaluate("sensor-01", "co2_ppm", 800.0, _ts(4.0))
    await evaluator.evaluate("sensor-01", "co2_ppm", 1100.0, _ts(5.0))
    state = evaluator.get_state("sensor-01", "co2_ppm")
    assert state.current_level == AlertLevel.LEVEL1
    assert state.exit_started_at is None


# ============================================================
# 5. 다중 노드/메트릭 독립성
# ============================================================

@pytest.mark.asyncio
async def test_multiple_nodes_independent():
    evaluator = AlertEvaluator(thresholds={"co2_ppm": _co2_thresholds()})
    # sensor-01 L1 진입
    await evaluator.evaluate("sensor-01", "co2_ppm", 1100.0, _ts(0))
    await evaluator.evaluate("sensor-01", "co2_ppm", 1100.0, _ts(3.0))
    # sensor-02 여전히 normal
    state2 = evaluator.get_state("sensor-02", "co2_ppm")
    assert state2.current_level == AlertLevel.NORMAL


@pytest.mark.asyncio
async def test_multiple_metrics_independent():
    """co2_ppm 와 temperature_c 는 독립 추적."""
    evaluator = AlertEvaluator(thresholds={
        "co2_ppm": _co2_thresholds(),
        "temperature_c": [
            _threshold("temperature_c", AlertLevel.LEVEL1, enter=35, exit_=34, enter_ms=5000, exit_ms=10000),
            _threshold("temperature_c", AlertLevel.LEVEL2, enter=38, exit_=37, enter_ms=5000, exit_ms=10000),
            _threshold("temperature_c", AlertLevel.LEVEL3, enter=40, exit_=39, enter_ms=0, exit_ms=10000),
        ],
    })
    # co2 L1 진입
    await evaluator.evaluate("sensor-01", "co2_ppm", 1100.0, _ts(0))
    await evaluator.evaluate("sensor-01", "co2_ppm", 1100.0, _ts(3.0))
    # temperature L1 진입 시도 (enter_for_ms=5000 이므로 미진입)
    await evaluator.evaluate("sensor-01", "temperature_c", 36.0, _ts(0))
    co2_state = evaluator.get_state("sensor-01", "co2_ppm")
    temp_state = evaluator.get_state("sensor-01", "temperature_c")
    assert co2_state.current_level == AlertLevel.LEVEL1
    assert temp_state.current_level == AlertLevel.NORMAL


# ============================================================
# 6. 방향(below) 처리 — O2 low
# ============================================================

@pytest.mark.asyncio
async def test_below_direction_o2_low():
    """direction=below 인 경우 value < enter_threshold 일 때 진입 후보."""
    evaluator = AlertEvaluator(thresholds={
        "o2_low": [
            _threshold("o2_low", AlertLevel.LEVEL1, enter=19.5, exit_=20.0, enter_ms=5000, exit_ms=10000, direction="below"),
            _threshold("o2_low", AlertLevel.LEVEL2, enter=18.0, exit_=18.5, enter_ms=5000, exit_ms=10000, direction="below"),
            _threshold("o2_low", AlertLevel.LEVEL3, enter=16.0, exit_=16.5, enter_ms=0, exit_ms=10000, direction="below"),
        ],
    })
    transition = await evaluator.evaluate("wearable-01", "o2_low", 19.0, _ts(0))
    assert transition is None  # timer 시작
    transition = await evaluator.evaluate("wearable-01", "o2_low", 19.0, _ts(5.0))
    assert transition is not None
    assert transition.to_level == AlertLevel.LEVEL1


@pytest.mark.asyncio
async def test_below_direction_no_transition_when_above_threshold():
    """direction=below 이고 value >= enter_threshold 이면 진입 없음."""
    evaluator = AlertEvaluator(thresholds={
        "o2_low": [
            _threshold("o2_low", AlertLevel.LEVEL1, enter=19.5, exit_=20.0, enter_ms=5000, exit_ms=10000, direction="below"),
            _threshold("o2_low", AlertLevel.LEVEL2, enter=18.0, exit_=18.5, enter_ms=5000, exit_ms=10000, direction="below"),
            _threshold("o2_low", AlertLevel.LEVEL3, enter=16.0, exit_=16.5, enter_ms=0, exit_ms=10000, direction="below"),
        ],
    })
    transition = await evaluator.evaluate("wearable-01", "o2_low", 21.0, _ts(0))
    assert transition is None


# ============================================================
# 7. ingest_telemetry 통합 — metric 없을 때 안전
# ============================================================

@pytest.mark.asyncio
async def test_evaluate_unknown_metric_returns_none():
    """thresholds 에 없는 metric 은 None 반환 (오류 아님)."""
    evaluator = AlertEvaluator(thresholds={"co2_ppm": _co2_thresholds()})
    transition = await evaluator.evaluate("sensor-01", "unknown_metric", 100.0, _ts(0))
    assert transition is None


def test_evalulator_get_state_unknown_key_returns_normal():
    """처음 보는 alert_key 는 normal 상태로 자동 생성."""
    evaluator = AlertEvaluator(thresholds={"co2_ppm": _co2_thresholds()})
    state = evaluator.get_state("new-node", "new-metric")
    assert state.current_level == AlertLevel.NORMAL
