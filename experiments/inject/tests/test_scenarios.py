"""이슈 #82: 시나리오 데이터 생성 — TDD 테스트.

시나리오: CO2 경보, H2S 경보, 낙하, O2 저농도, 오프라인.
각 시나리오는 (topic, payload) 튜플의 리스트를 반환한다.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from scenarios import (
    SCENARIOS,
    co2_warning,
    fall_detection,
    h2s_warning,
    node_offline,
    o2_low,
)


def test_all_scenarios_registered():
    expected = {"co2_warning", "h2s_warning", "fall_detection", "o2_low", "node_offline"}
    assert set(SCENARIOS.keys()) == expected


def test_co2_warning_generates_escalating_messages():
    start = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
    messages = co2_warning(start=start, node_id="sensor-01")
    assert len(messages) > 0
    topics = [m[0] for m in messages]
    assert "sensors/sensor-01/gas" in topics


def test_co2_warning_includes_simulation_metadata():
    start = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
    messages = co2_warning(start=start, node_id="sensor-01")
    for _, payload in messages:
        assert payload["source_mode"] == "simulation"
        assert payload["simulation"]["scenario_id"] == "co2_warning"


def test_co2_warning_reaches_critical_level():
    """CO2 시나리오는 정상 → L1 → L2 → L3 → 정상 복귀를 시뮬레이션한다."""
    start = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
    messages = co2_warning(start=start, node_id="sensor-01")
    co2_values = []
    for topic, payload in messages:
        if "gas" in topic:
            co2_values.append(payload["data"].get("co2_ppm"))
    assert max(v for v in co2_values if v is not None) >= 5000, "L3 임계값(5000) 도달 필요"


def test_h2s_warning_scenario():
    start = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
    messages = h2s_warning(start=start, node_id="sensor-01")
    assert len(messages) > 0
    h2s_values = [
        payload["data"].get("h2s_ppm")
        for topic, payload in messages
        if "gas" in topic and "h2s_ppm" in payload["data"]
    ]
    assert max(h2s_values) >= 10, "L3 임계값(10ppm) 도달 필요"


def test_fall_detection_scenario_uses_wearable_topic():
    start = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
    messages = fall_detection(start=start, node_id="wearable-01")
    topics = [m[0] for m in messages]
    assert any("wearable/wearable-01/imu" in t for t in topics)


def test_o2_low_scenario_reaches_critical():
    start = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
    messages = o2_low(start=start, node_id="wearable-01")
    o2_values = [
        payload["data"].get("o2_pct")
        for topic, payload in messages
        if "vital" in topic and "o2_pct" in payload["data"]
    ]
    assert min(o2_values) <= 16.0, "L3 저농도 임계값(16%) 도달 필요"


def test_node_offline_scenario_publishes_connection_messages():
    start = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
    messages = node_offline(start=start, node_id="sensor-01")
    topics = [m[0] for m in messages]
    assert any("nodes/sensor-01/connection" in t for t in topics)
    statuses = [payload["status"] for _, payload in messages]
    assert "offline" in statuses


def test_all_scenarios_accept_run_id():
    start = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
    for name, gen in SCENARIOS.items():
        messages = gen(start=start, node_id="sensor-01", run_id="test-run")
        if messages:
            _, payload = messages[0]
            if "simulation" in payload and payload["simulation"]:
                assert payload["simulation"]["run_id"] == "test-run", f"{name} run_id 누락"
