"""이슈 #196: DB 기반 AlertEvaluator 상태 복구."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.models.alert import AlertLevel
from app.services.alert_engine import AlertEvaluator

TS = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)


def _co2_thresholds():
    from app.models.threshold import Threshold, ThresholdDirection

    return {
        "co2_ppm": [
            Threshold(
                metric="co2_ppm", level="level1_caution",
                direction=ThresholdDirection.ABOVE, enter_threshold=1000,
                exit_threshold=900, enter_for_ms=3000, exit_for_ms=5000,
            ),
            Threshold(
                metric="co2_ppm", level="level2_warning",
                direction=ThresholdDirection.ABOVE, enter_threshold=2000,
                exit_threshold=1900, enter_for_ms=3000, exit_for_ms=5000,
            ),
            Threshold(
                metric="co2_ppm", level="level3_critical",
                direction=ThresholdDirection.ABOVE, enter_threshold=5000,
                exit_threshold=4500, enter_for_ms=0, exit_for_ms=5000,
            ),
        ]
    }


def _row(**overrides):
    row = {
        "source_node_id": "sensor-01",
        "alert_key": "co2_ppm",
        "alert_id": "01AAAAAAAAAAAAAAAAAAAAAAAA",
        "activated_at": TS,
        "status": "active",
        "level": "level2_warning",
    }
    row.update(overrides)
    return row


def test_restore_active_state_sets_level_without_pending_timers():
    evaluator = AlertEvaluator(_co2_thresholds())
    state = evaluator.get_state("sensor-01", "co2_ppm")
    state.enter_started_at = TS
    state.enter_pending_level = AlertLevel.LEVEL2
    state.exit_started_at = TS

    assert evaluator.restore_active_state(
        "sensor-01", "co2_ppm", AlertLevel.LEVEL2
    )
    assert state.current_level == AlertLevel.LEVEL2
    assert state.enter_started_at is None
    assert state.enter_pending_level is None
    assert state.exit_started_at is None


@pytest.mark.asyncio
async def test_restored_active_level_does_not_refire_on_same_value():
    evaluator = AlertEvaluator(_co2_thresholds())
    evaluator.restore_active_state("sensor-01", "co2_ppm", AlertLevel.LEVEL2)

    transition = await evaluator.evaluate("sensor-01", "co2_ppm", 2100, TS)

    assert transition is None
    assert evaluator.get_state("sensor-01", "co2_ppm").current_level == AlertLevel.LEVEL2


def test_restore_rows_skips_resolved_unknown_and_malformed(monkeypatch):
    from app.services import alert_service

    evaluator = AlertEvaluator(_co2_thresholds())
    monkeypatch.setattr(alert_service, "_evaluator", evaluator)
    count = alert_service.restore_active_alert_rows([
        _row(),
        _row(source_node_id="sensor-02", status="resolved"),
        _row(source_node_id="sensor-03", alert_key="connection_lost"),
        {"incomplete": "row"},
    ])

    assert count == 1
    assert evaluator.get_state("sensor-01", "co2_ppm").current_level == AlertLevel.LEVEL2
    assert ("sensor-02", "co2_ppm") not in evaluator._states
    assert ("sensor-03", "connection_lost") not in evaluator._states


def test_restore_rows_before_evaluator_init_is_noop(monkeypatch):
    from app.services import alert_service

    monkeypatch.setattr(alert_service, "_evaluator", None)
    assert alert_service.restore_active_alert_rows([_row()]) == 0


@pytest.mark.asyncio
async def test_runtime_restore_uses_one_query_for_both_states(monkeypatch):
    from app.services import alert_publisher, alert_service

    rows = [_row()]
    publisher = alert_publisher.AlertEventPublisher(mqtt_client=None)
    evaluator = AlertEvaluator(_co2_thresholds())
    monkeypatch.setattr(alert_publisher, "_publisher", publisher)
    monkeypatch.setattr(alert_service, "_evaluator", evaluator)

    calls = 0

    async def load_once():
        nonlocal calls
        calls += 1
        return rows

    monkeypatch.setattr(publisher, "_load_latest_alert_rows", load_once)

    assert await alert_publisher.restore_runtime_alert_state() == (1, 1)
    assert calls == 1
    assert publisher._active_alert_ids[("sensor-01", "co2_ppm")] == (
        "01AAAAAAAAAAAAAAAAAAAAAAAA", TS,
    )
    assert evaluator.get_state("sensor-01", "co2_ppm").current_level == AlertLevel.LEVEL2


@pytest.mark.asyncio
async def test_runtime_restore_failure_is_visible_but_nonfatal(monkeypatch, caplog):
    from app.services import alert_publisher

    publisher = alert_publisher.AlertEventPublisher(mqtt_client=None)
    monkeypatch.setattr(alert_publisher, "_publisher", publisher)

    async def explode():
        raise RuntimeError("db down")

    monkeypatch.setattr(publisher, "_load_latest_alert_rows", explode)

    assert await alert_publisher.restore_runtime_alert_state() == (0, 0)
    assert "runtime alert restore failed" in caplog.text
