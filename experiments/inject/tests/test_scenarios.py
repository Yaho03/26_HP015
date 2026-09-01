"""이슈 #82: 시나리오 데이터 생성 — TDD 테스트.

시나리오: CO2 경보, H2S 경보, 낙하, O2 저농도, 오프라인.
각 시나리오는 (topic, payload) 튜플의 리스트를 반환한다.
"""
from __future__ import annotations

import inspect
import math
from datetime import datetime, timezone

import pytest

from scenarios import (
    DEMO_SPACE_DEPTH_M,
    DEMO_SPACE_WIDTH_M,
    GAS_SPREAD_BASELINE_PPM,
    GAS_SPREAD_PROFILE,
    LOCATION_HZ,
    NORMAL_CEILINGS,
    SCENARIOS,
    WALK_SPEED_MPS,
    co2_warning,
    exposure_h2s_danger,
    gas_spread,
    fall_detection,
    h2s_warning,
    node_offline,
    normal_steady,
    o2_low,
    worker_walk,
)


def test_all_scenarios_registered():
    expected = {
        "co2_warning",
        "h2s_warning",
        "fall_detection",
        "o2_low",
        "node_offline",
        "normal_steady",
        "worker_walk",
        "gas_spread",
        "exposure_h2s_danger",
        "worker_walk_uwb",
    }
    assert set(SCENARIOS.keys()) == expected


def test_exposure_h2s_danger_keeps_four_node_samples_fresh_and_marks_simulation():
    start = datetime(2026, 8, 25, 12, 0, 0, tzinfo=timezone.utc)
    for node_id in ("sensor-01", "sensor-02", "sensor-03", "sensor-04"):
        messages = exposure_h2s_danger(
            start=start, node_id=node_id, duration_seconds=2,
        )
        gas = [payload for topic, payload in messages if topic.endswith("/gas")]
        assert len(gas) == 3
        assert all(p["simulation"]["scenario_id"] == "exposure_h2s_danger" for p in gas)
        expected_h2s = 4.0 if node_id == "sensor-03" else gas[0]["data"]["h2s_ppm"]
        assert gas[-1]["data"]["h2s_ppm"] == expected_h2s

    source_messages = exposure_h2s_danger(
        start=start, node_id="sensor-03", duration_seconds=2,
    )
    assert any(topic == "wearable/wearable-01/location" for topic, _ in source_messages)
    assert any(topic == "wearable/wearable-01/vital" for topic, _ in source_messages)
    locations = [
        payload["data"] for topic, payload in source_messages
        if topic == "wearable/wearable-01/location"
    ]
    assert all(location["x_m"] == 2.2 and location["y_m"] == 1.7 for location in locations)


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


def test_normal_steady_stays_below_level1_thresholds():
    """Scenario 1(정상 상태 모니터링) — 어떤 값도 L1 진입 임계값에 닿으면 안 된다."""
    start = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
    messages = normal_steady(start=start, node_id="sensor-01", duration_seconds=120)
    assert messages
    for topic, payload in messages:
        if "data" not in payload:
            continue
        for metric, ceiling in NORMAL_CEILINGS.items():
            value = payload["data"].get(metric)
            if value is not None:
                assert value < ceiling, f"{topic} {metric}={value} 가 정상 범위를 벗어남"


def test_normal_steady_covers_all_six_card_metrics():
    """모니터링 카드가 표시하는 노드 지표 6종이 전부 채워져야 한다."""
    start = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
    messages = normal_steady(start=start, node_id="sensor-01", duration_seconds=10)
    seen = set()
    for _, payload in messages:
        seen.update(payload.get("data", {}).keys())
    assert {
        "co2_ppm",
        "co_ppm",
        "h2s_ppm",
        "temperature_c",
        "humidity_pct",
        "gas_resistance_ohm",
    } <= seen


def test_normal_steady_splits_gas_and_env_topics():
    """04_DATA_CONTRACT 3.1 — 가스는 /gas, 온습도는 /env 로 나눠 발행한다."""
    start = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
    messages = normal_steady(start=start, node_id="sensor-02", duration_seconds=10)
    topics = {m[0] for m in messages}
    assert topics == {
        "sensors/sensor-02/gas",
        "sensors/sensor-02/env",
    }
    for topic, payload in messages:
        if topic.endswith("/env"):
            assert "co2_ppm" not in payload["data"]
            assert "temperature_c" in payload["data"]
        else:
            assert "co2_ppm" in payload["data"]


def test_normal_steady_duration_controls_message_count():
    start = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
    short = normal_steady(start=start, node_id="sensor-01", duration_seconds=10)
    long = normal_steady(start=start, node_id="sensor-01", duration_seconds=60)
    assert len(long) > len(short)


def test_scenarios_leave_connection_status_to_the_runner():
    """연결 상태는 ScenarioRunner 가 낸다 (test_injector).

    시나리오가 각자 내면 새 시나리오를 추가할 때 빠뜨리기 쉽고, 실제로
    gas_spread 를 포함한 8개가 빠져 노드가 "연결 끊김" 으로 남았다.
    연결 전이 자체를 시연하는 node_offline 만 예외다.
    """
    start = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
    for name, fn in SCENARIOS.items():
        if name == "node_offline":
            continue
        params = inspect.signature(fn).parameters
        kwargs = {"start": start, "run_id": "r"}
        if "node_id" in params:
            kwargs["node_id"] = "sensor-01"
        if "node_ids" in params:
            kwargs["node_ids"] = ["sensor-01"]
        if "sec" in params:
            kwargs["sec"] = 1
        topics = {topic for topic, _ in fn(**kwargs)}
        assert not any(t.endswith("/connection") for t in topics), name


def test_normal_steady_differs_per_node():
    """4개 카드가 똑같은 숫자로 보이면 화면 검증이 안 된다."""
    start = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)

    def first_co2(node_id: str) -> float:
        for topic, payload in normal_steady(
            start=start, node_id=node_id, duration_seconds=10
        ):
            if topic.endswith("/gas"):
                return payload["data"]["co2_ppm"]
        raise AssertionError("gas 메시지 없음")

    values = {first_co2(n) for n in ("sensor-01", "sensor-02", "sensor-03", "sensor-04")}
    assert len(values) == 4, f"노드별 기준값이 겹침: {values}"


def test_normal_steady_timestamps_advance():
    start = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
    messages = normal_steady(start=start, node_id="sensor-01", duration_seconds=30)
    gas_times = [
        payload["sampled_at"] for topic, payload in messages if topic.endswith("/gas")
    ]
    assert gas_times == sorted(gas_times)
    assert len(set(gas_times)) == len(gas_times), "sampled_at 중복"


def _walk(duration_seconds: int = 20):
    start = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
    return worker_walk(
        start=start, node_id="wearable-01", duration_seconds=duration_seconds
    )


def test_worker_walk_uses_location_topic_only():
    assert {t for t, _ in _walk()} == {"wearable/wearable-01/location"}


def test_worker_walk_payload_matches_location_schema_fields():
    """schemas/wearable-location.schema.json 의 data 는 additionalProperties: false 다."""
    required = {
        "x_m", "y_m", "z_m", "coordinate_system",
        "method", "anchor_count", "quality_score", "is_filtered",
    }
    for _, payload in _walk():
        assert set(payload["data"].keys()) == required


def test_worker_walk_holds_schema_constants():
    """z_m const 0.0 / coordinate_system const model-local / method const ds_twr."""
    for _, payload in _walk():
        data = payload["data"]
        assert data["z_m"] == 0.0, "PRD 측위는 2D 고정 — z_m 은 항상 0.0"
        assert data["coordinate_system"] == "model-local"
        assert data["method"] == "ds_twr"
        assert 3 <= data["anchor_count"] <= 4
        assert 0.0 <= data["quality_score"] <= 1.0
        assert isinstance(data["is_filtered"], bool)


def test_worker_walk_stays_inside_demo_space():
    """05_DIGITAL_TWIN_SPEC — demo-local 공간은 2.5m x 2.0m 다."""
    for _, payload in _walk():
        data = payload["data"]
        assert 0.0 <= data["x_m"] <= DEMO_SPACE_WIDTH_M, data["x_m"]
        assert 0.0 <= data["y_m"] <= DEMO_SPACE_DEPTH_M, data["y_m"]


def test_worker_walk_meets_5hz_success_criterion():
    """09_DEMO_SCENARIOS Scenario 3 성공 기준 — 위치 업데이트 5Hz 이상."""
    assert LOCATION_HZ >= 5
    duration = 20
    messages = _walk(duration)
    assert len(messages) >= duration * 5


def test_worker_walk_steps_are_walking_speed_not_teleports():
    """한 스텝 이동거리가 보행 속도와 맞아야 LocationFilter 가 이상치로 버리지 않는다."""
    positions = [(p["data"]["x_m"], p["data"]["y_m"]) for _, p in _walk()]
    max_step = WALK_SPEED_MPS / LOCATION_HZ
    for (x0, y0), (x1, y1) in zip(positions, positions[1:]):
        step = math.hypot(x1 - x0, y1 - y0)
        assert step <= max_step + 1e-9, f"{step:.3f}m 이동 — 순간이동으로 거부됨"


def test_worker_walk_actually_moves():
    positions = {(p["data"]["x_m"], p["data"]["y_m"]) for _, p in _walk()}
    assert len(positions) > 50, "위치가 거의 안 변하면 추적 시연이 안 된다"


def test_worker_walk_duration_controls_message_count():
    assert len(_walk(40)) > len(_walk(10))


def _spread_co2(node_id: str, duration_seconds: int = 180) -> list[float]:
    start = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
    return [
        payload["data"]["co2_ppm"]
        for topic, payload in gas_spread(
            start=start, node_id=node_id, duration_seconds=duration_seconds
        )
        if topic.endswith("/gas")
    ]


def test_gas_spread_source_keeps_worker_position_fresh_for_evacuation():
    start = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
    messages = gas_spread(start=start, node_id="sensor-03", duration_seconds=30)
    topics = {t for t, _ in messages}
    assert topics == {
        "sensors/sensor-03/gas",
        "wearable/wearable-01/location",
        "wearable/wearable-01/vital",
    }

    location_payloads = [
        payload for topic, payload in messages if topic.endswith("/location")
    ]
    assert location_payloads
    assert {payload["node_id"] for payload in location_payloads} == {"wearable-01"}
    assert all(
        payload["simulation"]["scenario_id"] == "gas_spread"
        for payload in location_payloads
    )


def test_gas_spread_non_source_nodes_do_not_duplicate_worker_position():
    start = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
    messages = gas_spread(start=start, node_id="sensor-01", duration_seconds=30)
    assert {t for t, _ in messages} == {"sensors/sensor-01/gas"}


def test_gas_spread_starts_from_normal_baseline():
    """모든 노드가 정상에서 출발해야 확산 전/후가 눈에 보인다."""
    for node_id in GAS_SPREAD_PROFILE:
        assert _spread_co2(node_id)[0] == GAS_SPREAD_BASELINE_PPM


def test_gas_spread_source_node_reaches_critical():
    assert max(_spread_co2("sensor-03")) >= 5000, "누출원은 L3 에 도달해야 한다"


def test_gas_spread_peak_falls_off_with_distance():
    """누출원에서 멀수록 정점 농도가 낮아야 분포가 방향을 갖는다."""
    peaks = [max(_spread_co2(n)) for n in ("sensor-03", "sensor-01", "sensor-04", "sensor-02")]
    assert peaks == sorted(peaks, reverse=True), peaks


def test_gas_spread_arrival_is_staggered():
    """도달 시각이 같으면 히트맵이 한 번에 물들어 확산으로 보이지 않는다."""
    def peak_index(node_id: str) -> int:
        values = _spread_co2(node_id)
        return values.index(max(values))

    order = [peak_index(n) for n in ("sensor-03", "sensor-01", "sensor-04", "sensor-02")]
    assert order == sorted(order), order
    assert len(set(order)) == 4, f"도달 시각이 겹침: {order}"


def test_gas_spread_returns_to_baseline():
    """환기 후 정상 복귀까지 담아야 시연 한 번으로 전체 흐름이 보인다."""
    for node_id in GAS_SPREAD_PROFILE:
        assert _spread_co2(node_id)[-1] == GAS_SPREAD_BASELINE_PPM, node_id


def test_gas_spread_unknown_node_stays_at_baseline():
    """프로파일에 없는 노드는 조용히 정상값만 낸다."""
    values = _spread_co2("sensor-09")
    assert set(values) == {GAS_SPREAD_BASELINE_PPM}


def test_gas_spread_duration_controls_message_count():
    assert len(_spread_co2("sensor-03", 240)) > len(_spread_co2("sensor-03", 60))


def test_all_scenarios_accept_run_id():
    start = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
    for name, gen in SCENARIOS.items():
        messages = gen(start=start, node_id="sensor-01", run_id="test-run")
        if messages:
            _, payload = messages[0]
            if "simulation" in payload and payload["simulation"]:
                assert payload["simulation"]["run_id"] == "test-run", f"{name} run_id 누락"
