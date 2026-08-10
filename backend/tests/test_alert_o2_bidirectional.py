"""이슈 #56: O₂ 양방향 경보 (o2_low / o2_high) — TDD 테스트.

검증 범위:
1. o2_pct 센서값이 alert_service 를 통해 o2_low 와 o2_high 두 alert_key 로 분산 평가
2. 정상 범위(19.5~23.5%) → 둘 다 inactive
3. 저농도(<19.5%) → o2_low 만 active
4. 고농도(>23.5%) → o2_high 만 active
5. 동시 발생 불가 (같은 value 가 두 조건을 동시 만족 불가)
6. 시나리오: low active → 정상 복귀 → high active 전환
7. 마이그레이션 005 시드에 o2_low/o2_high threshold 포함
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.models.alert import AlertLevel
from app.services.alert_engine import AlertEvaluator


def _o2_thresholds():
    from app.models.threshold import Threshold, ThresholdDirection
    return {
        "o2_low": [
            Threshold(metric="o2_low", level="level1_caution", direction=ThresholdDirection.BELOW,
                      enter_threshold=19.5, exit_threshold=20.0, enter_for_ms=5000, exit_for_ms=10000),
            Threshold(metric="o2_low", level="level2_warning", direction=ThresholdDirection.BELOW,
                      enter_threshold=18.0, exit_threshold=18.5, enter_for_ms=5000, exit_for_ms=10000),
            Threshold(metric="o2_low", level="level3_critical", direction=ThresholdDirection.BELOW,
                      enter_threshold=16.0, exit_threshold=16.5, enter_for_ms=0, exit_for_ms=10000),
        ],
        "o2_high": [
            Threshold(metric="o2_high", level="level1_caution", direction=ThresholdDirection.ABOVE,
                      enter_threshold=23.5, exit_threshold=23.0, enter_for_ms=5000, exit_for_ms=10000),
            Threshold(metric="o2_high", level="level2_warning", direction=ThresholdDirection.ABOVE,
                      enter_threshold=25.0, exit_threshold=24.5, enter_for_ms=5000, exit_for_ms=10000),
            Threshold(metric="o2_high", level="level3_critical", direction=ThresholdDirection.ABOVE,
                      enter_threshold=28.0, exit_threshold=27.5, enter_for_ms=0, exit_for_ms=10000),
        ],
    }


def _ts(seconds: float) -> datetime:
    return datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc) + timedelta(seconds=seconds)


def _make_async_handler(store):
    async def _h(t):
        store.append(t)
    return _h


# ============================================================
# 1. alert_service metric 매핑 — o2_pct → o2_low/o2_high
# ============================================================

def test_alert_service_has_metric_mapping():
    """alert_service 가 o2_pct → [o2_low, o2_high] 매핑을 가져야 한다."""
    from app.services import alert_service
    assert hasattr(alert_service, "METRIC_TO_ALERT_KEYS")
    assert "o2_pct" in alert_service.METRIC_TO_ALERT_KEYS
    assert "o2_low" in alert_service.METRIC_TO_ALERT_KEYS["o2_pct"]
    assert "o2_high" in alert_service.METRIC_TO_ALERT_KEYS["o2_pct"]


@pytest.mark.asyncio
async def test_o2_pct_normal_range_no_alert(monkeypatch):
    """o2_pct 20.9% (정상 범위) → o2_low/o2_high 모두 inactive."""
    from app.services import alert_service

    evaluator = AlertEvaluator(thresholds=_o2_thresholds())
    monkeypatch.setattr(alert_service, "_evaluator", evaluator)

    transitions = []
    monkeypatch.setattr(
        alert_service, "_handle_transition",
        _make_async_handler(transitions),
    )

    await alert_service._on_metric_ingested("wearable-01", "o2_pct", 20.9, _ts(0))
    assert transitions == []
    assert evaluator.get_state("wearable-01", "o2_low").current_level == AlertLevel.NORMAL
    assert evaluator.get_state("wearable-01", "o2_high").current_level == AlertLevel.NORMAL


@pytest.mark.asyncio
async def test_o2_low_concentration_triggers_only_o2_low(monkeypatch):
    """o2_pct 19.0% (<19.5) → o2_low enter timer 시작, o2_high inactive."""
    from app.services import alert_service

    evaluator = AlertEvaluator(thresholds=_o2_thresholds())
    monkeypatch.setattr(alert_service, "_evaluator", evaluator)

    await alert_service._on_metric_ingested("wearable-01", "o2_pct", 19.0, _ts(0))
    low_state = evaluator.get_state("wearable-01", "o2_low")
    high_state = evaluator.get_state("wearable-01", "o2_high")
    assert low_state.enter_started_at is not None, "o2_low enter timer 가 시작되어야 함"
    assert high_state.current_level == AlertLevel.NORMAL


@pytest.mark.asyncio
async def test_o2_high_concentration_triggers_only_o2_high(monkeypatch):
    """o2_pct 24.0% (>23.5) → o2_high enter timer 시작, o2_low inactive."""
    from app.services import alert_service

    evaluator = AlertEvaluator(thresholds=_o2_thresholds())
    monkeypatch.setattr(alert_service, "_evaluator", evaluator)

    await alert_service._on_metric_ingested("wearable-01", "o2_pct", 24.0, _ts(0))
    low_state = evaluator.get_state("wearable-01", "o2_low")
    high_state = evaluator.get_state("wearable-01", "o2_high")
    assert low_state.current_level == AlertLevel.NORMAL
    assert high_state.enter_started_at is not None


@pytest.mark.asyncio
async def test_o2_low_after_duration_enters_l1(monkeypatch):
    """o2_low 5초 경과 → L1 진입."""
    from app.services import alert_service

    evaluator = AlertEvaluator(thresholds=_o2_thresholds())
    monkeypatch.setattr(alert_service, "_evaluator", evaluator)
    transitions = []
    monkeypatch.setattr(
        alert_service, "_handle_transition",
        _make_async_handler(transitions),
    )

    await alert_service._on_metric_ingested("wearable-01", "o2_pct", 19.0, _ts(0))
    await alert_service._on_metric_ingested("wearable-01", "o2_pct", 19.0, _ts(5.0))
    assert len(transitions) == 1
    assert transitions[0].metric == "o2_low"
    assert transitions[0].to_level == AlertLevel.LEVEL1


# ============================================================
# 2. 시나리오: low → normal → high 전환
# ============================================================

@pytest.mark.asyncio
async def test_scenario_low_to_normal_to_high(monkeypatch):
    """시나리오: o2_low active → 정상 복귀 → o2_high active."""
    from app.services import alert_service

    evaluator = AlertEvaluator(thresholds=_o2_thresholds())
    monkeypatch.setattr(alert_service, "_evaluator", evaluator)
    transitions = []
    monkeypatch.setattr(
        alert_service, "_handle_transition",
        _make_async_handler(transitions),
    )

    # low 진입
    await alert_service._on_metric_ingested("wearable-01", "o2_pct", 19.0, _ts(0))
    await alert_service._on_metric_ingested("wearable-01", "o2_pct", 19.0, _ts(5.0))
    assert evaluator.get_state("wearable-01", "o2_low").current_level == AlertLevel.LEVEL1

    # 정상 복귀 (exit_threshold=20.0, exit_for_ms=10000)
    await alert_service._on_metric_ingested("wearable-01", "o2_pct", 20.5, _ts(10.0))
    await alert_service._on_metric_ingested("wearable-01", "o2_pct", 20.5, _ts(20.0))
    assert evaluator.get_state("wearable-01", "o2_low").current_level == AlertLevel.NORMAL

    # high 진입
    await alert_service._on_metric_ingested("wearable-01", "o2_pct", 24.0, _ts(25.0))
    await alert_service._on_metric_ingested("wearable-01", "o2_pct", 24.0, _ts(30.0))
    assert evaluator.get_state("wearable-01", "o2_high").current_level == AlertLevel.LEVEL1


@pytest.mark.asyncio
async def test_o2_low_and_high_cannot_be_active_simultaneously(monkeypatch):
    """ENTER 시점에 동시 active 가 불가능함을 검증.
    value < 19.5 ∧ value > 23.5 는 수학적으로 불가능.
    Hysteresis 로 인한 일시적 동시 active(exit timer 진행 중)는 허용하되,
    ENTER transition 발생 시점에는 반드시 한쪽만 active 여야 한다."""
    from app.services import alert_service

    test_values = [15.0, 17.0, 19.0, 20.9, 22.0, 24.0, 26.0, 30.0]
    for v in test_values:
        evaluator = AlertEvaluator(thresholds=_o2_thresholds())
        monkeypatch.setattr(alert_service, "_evaluator", evaluator)
        transitions = []
        monkeypatch.setattr(
            alert_service, "_handle_transition",
            _make_async_handler(transitions),
        )

        await alert_service._on_metric_ingested("wearable-01", "o2_pct", v, _ts(0))
        await alert_service._on_metric_ingested("wearable-01", "o2_pct", v, _ts(6.0))

        low = evaluator.get_state("wearable-01", "o2_low").current_level
        high = evaluator.get_state("wearable-01", "o2_high").current_level

        if low != AlertLevel.NORMAL:
            assert high == AlertLevel.NORMAL, (
                f"value={v}: o2_low active({low}) 인데 o2_high 도 active({high})"
            )
        if high != AlertLevel.NORMAL:
            assert low == AlertLevel.NORMAL, (
                f"value={v}: o2_high active({high}) 인데 o2_low 도 active({low})"
            )


# ============================================================
# 3. migration 005 시드 검증 — 이미 포함되어 있어야 함
# ============================================================

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def test_migration_005_includes_o2_low_and_high():
    """005 시드에 o2_low, o2_high threshold 가 포함되어야 한다."""
    sql = (MIGRATIONS_DIR / "005_thresholds.sql").read_text()
    assert "o2_low" in sql
    assert "o2_high" in sql
    # direction=below for o2_low
    import re
    low_below_pattern = re.search(
        r"\('o2_low'[^)]*?'below'", sql, re.DOTALL
    )
    assert low_below_pattern, "o2_low threshold 가 direction=below 로 시드되어야 함"


def test_migration_005_o2_thresholds_match_prd():
    """PRD FR-201 + 06_ALERT_RULES 4.2 의 O₂ 임계값과 시드가 일치해야 한다.
    whitespace 는 정규식 \s* 로 관대하게 매칭."""
    sql = (MIGRATIONS_DIR / "005_thresholds.sql").read_text()
    import re

    def _has(pattern: str) -> bool:
        return re.search(pattern, sql) is not None

    assert _has(r"'o2_low'\s*,\s*'level1_caution'\s*,\s*'below'\s*,\s*19\.5\s*,\s*20\.0\s*,\s*5000\s*,\s*10000")
    assert _has(r"'o2_low'\s*,\s*'level3_critical'\s*,\s*'below'\s*,\s*16\.0\s*,\s*16\.5\s*,\s*0\s*,\s*10000")
    assert _has(r"'o2_high'\s*,\s*'level1_caution'\s*,\s*'above'\s*,\s*23\.5\s*,\s*23\.0\s*,\s*5000\s*,\s*10000")
    assert _has(r"'o2_high'\s*,\s*'level3_critical'\s*,\s*'above'\s*,\s*28\.0\s*,\s*27\.5\s*,\s*0\s*,\s*10000")
