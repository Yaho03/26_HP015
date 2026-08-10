"""이슈 #87: 백엔드 재시작 시 경보 상태 복구 — TDD 테스트."""
from __future__ import annotations

import pytest

from app.models.alert import AlertLevel
from app.services.alert_engine import AlertEvaluator


def _co2_thresholds():
    from app.models.threshold import Threshold, ThresholdDirection
    return {
        "co2_ppm": [
            Threshold(metric="co2_ppm", level="level1_caution", direction=ThresholdDirection.ABOVE,
                      enter_threshold=1000, exit_threshold=900, enter_for_ms=3000, exit_for_ms=5000),
            Threshold(metric="co2_ppm", level="level2_warning", direction=ThresholdDirection.ABOVE,
                      enter_threshold=2000, exit_threshold=1900, enter_for_ms=3000, exit_for_ms=5000),
            Threshold(metric="co2_ppm", level="level3_critical", direction=ThresholdDirection.ABOVE,
                      enter_threshold=5000, exit_threshold=4500, enter_for_ms=0, exit_for_ms=5000),
        ],
    }


def test_recover_function_exists():
    from app.services import alert_service
    assert hasattr(alert_service, "recover_from_retain_messages")


@pytest.mark.asyncio
async def test_recover_active_message_sets_state(monkeypatch):
    from app.services import alert_service

    evaluator = AlertEvaluator(thresholds=_co2_thresholds())
    monkeypatch.setattr(alert_service, "_evaluator", evaluator)

    await alert_service.recover_from_retain_messages([
        {
            "source_node_id": "sensor-01",
            "alert_key": "co2_ppm",
            "level": "level2_warning",
            "status": "active",
        },
    ])

    state = evaluator.get_state("sensor-01", "co2_ppm")
    assert state.current_level == AlertLevel.LEVEL2


@pytest.mark.asyncio
async def test_recover_resolved_message_keeps_state_normal(monkeypatch):
    from app.services import alert_service

    evaluator = AlertEvaluator(thresholds=_co2_thresholds())
    monkeypatch.setattr(alert_service, "_evaluator", evaluator)

    await alert_service.recover_from_retain_messages([
        {
            "source_node_id": "sensor-01",
            "alert_key": "co2_ppm",
            "level": "level1_caution",
            "status": "resolved",
        },
    ])

    state = evaluator.get_state("sensor-01", "co2_ppm")
    assert state.current_level == AlertLevel.NORMAL


@pytest.mark.asyncio
async def test_recover_multiple_messages_independent(monkeypatch):
    from app.services import alert_service

    evaluator = AlertEvaluator(thresholds=_co2_thresholds())
    monkeypatch.setattr(alert_service, "_evaluator", evaluator)

    await alert_service.recover_from_retain_messages([
        {"source_node_id": "sensor-01", "alert_key": "co2_ppm",
         "level": "level1_caution", "status": "active"},
        {"source_node_id": "sensor-02", "alert_key": "co2_ppm",
         "level": "level3_critical", "status": "active"},
    ])

    assert evaluator.get_state("sensor-01", "co2_ppm").current_level == AlertLevel.LEVEL1
    assert evaluator.get_state("sensor-02", "co2_ppm").current_level == AlertLevel.LEVEL3


@pytest.mark.asyncio
async def test_recover_empty_messages_no_error(monkeypatch):
    from app.services import alert_service

    evaluator = AlertEvaluator(thresholds=_co2_thresholds())
    monkeypatch.setattr(alert_service, "_evaluator", evaluator)

    await alert_service.recover_from_retain_messages([])
    assert True


@pytest.mark.asyncio
async def test_recover_skips_unknown_metric(monkeypatch):
    """thresholds 에 없는 metric 은 스킵 (에러 아님)."""
    from app.services import alert_service

    evaluator = AlertEvaluator(thresholds=_co2_thresholds())
    monkeypatch.setattr(alert_service, "_evaluator", evaluator)

    await alert_service.recover_from_retain_messages([
        {"source_node_id": "sensor-01", "alert_key": "unknown_metric",
         "level": "level1_caution", "status": "active"},
    ])


@pytest.mark.asyncio
async def test_recover_skips_malformed_message(monkeypatch):
    from app.services import alert_service

    evaluator = AlertEvaluator(thresholds=_co2_thresholds())
    monkeypatch.setattr(alert_service, "_evaluator", evaluator)

    await alert_service.recover_from_retain_messages([
        {"incomplete": "message"},
        {"source_node_id": "sensor-01", "alert_key": "co2_ppm",
         "level": "level1_caution", "status": "active"},
    ])
    assert evaluator.get_state("sensor-01", "co2_ppm").current_level == AlertLevel.LEVEL1
