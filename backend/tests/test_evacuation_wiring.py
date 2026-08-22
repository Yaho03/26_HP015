"""경로 배선 — 좌표 변환, 위험 구역 공급, 경로 교체 히스테리시스 (§2.4, §3.2, §3.4).

경로 계산 자체는 test_evacuation_router.py 가 맡는다. 여기서는 "언제 다시 계산하고
언제 화면을 바꾸는가"를 본다. EXP-8.3 (비용이 비슷한 두 경로 사이에서 경로 교체
2회 이하)이 이 파일에 있다.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models.alert import AlertLevel
from app.models.evacuation import HazardZone
from app.services import evacuation_hazards, evacuation_service
from app.services.evacuation_coordinates import (
    UNIFORM_SCALE,
    demo_to_ship,
    to_ship_visual,
)
from app.services.evacuation_router import Position2D
from app.services.evacuation_topology import load_topology_file


@pytest.fixture
def topology():
    return load_topology_file()


@pytest.fixture(autouse=True)
def clean_state():
    evacuation_service.reset_for_test()
    yield
    evacuation_service.reset_for_test()


def zone(zone_id: str, x: float, y: float, r: float, level: str) -> HazardZone:
    return HazardZone(zone_id=zone_id, center_x_m=x, center_y_m=y, radius_m=r, level=level)


# ============================================================
# 1. 좌표 변환 (ADR-010, §2.4)
# ============================================================

def test_uniform_scale_is_bounded_by_width():
    """폭이 먼저 차서 배율이 결정된다. 길이 기준(24배)을 쓰면 형상이 늘어난다."""
    assert UNIFORM_SCALE == 6.5


def test_demo_centre_maps_to_hold_centre():
    """축소 공간의 한가운데는 화물창의 한가운데다. 프론트 mapDemoToShip 과 같은 값."""
    assert demo_to_ship(1.25, 1.0) == (30.0, 0.0)


def test_demo_corners_map_to_the_uniform_target_rect():
    assert demo_to_ship(0.0, 0.0) == (21.875, -6.5)
    assert demo_to_ship(2.5, 2.0) == (38.125, 6.5)


def test_out_of_range_position_is_clamped_inside_the_hull():
    """측위 오차로 공간 밖 좌표가 와도 선체 밖에 사람을 그리지 않는다."""
    assert demo_to_ship(-5.0, -5.0) == (21.875, -6.5)
    assert demo_to_ship(99.0, 99.0) == (38.125, 6.5)


def test_ship_visual_input_is_not_mapped_twice():
    """시연 시나리오가 ship-visual 을 직접 발행할 수 있다. 다시 확대하면 안 된다."""
    assert to_ship_visual(30.0, 0.0, "ship-visual") == (30.0, 0.0)
    assert to_ship_visual(1.25, 1.0, "demo-local") == (30.0, 0.0)


# ============================================================
# 2. 위험 구역 공급 (§3.2, ADR-005)
# ============================================================

def test_sensor_positions_are_parsed(monkeypatch):
    monkeypatch.setattr(
        evacuation_hazards.settings,
        "evacuation_sensor_positions",
        "sensor-01:15,-3.25;sensor-02:45,3.25",
    )
    assert evacuation_hazards.sensor_positions() == {
        "sensor-01": (15.0, -3.25),
        "sensor-02": (45.0, 3.25),
    }


def test_malformed_sensor_entry_is_skipped_not_fatal(monkeypatch):
    """센서 하나의 오타 때문에 위험 구역 전체가 사라지면 화면은 조용히
    '위험 없음'으로 보인다."""
    monkeypatch.setattr(
        evacuation_hazards.settings,
        "evacuation_sensor_positions",
        "sensor-01:15,-3.25;쓰레기;sensor-02:45,3.25",
    )
    assert set(evacuation_hazards.sensor_positions()) == {"sensor-01", "sensor-02"}


def test_normal_nodes_do_not_become_zones():
    zones = evacuation_hazards.zones_from_levels({"sensor-01": AlertLevel.NORMAL})
    assert zones == []


def test_zone_takes_the_node_position_and_configured_radius(monkeypatch):
    monkeypatch.setattr(
        evacuation_hazards.settings, "evacuation_sensor_positions", "sensor-01:15,-3.25"
    )
    monkeypatch.setattr(evacuation_hazards.settings, "evacuation_hazard_radius_m", 4.0)

    zones = evacuation_hazards.zones_from_levels({"sensor-01": AlertLevel.LEVEL2})

    assert len(zones) == 1
    assert (zones[0].center_x_m, zones[0].center_y_m) == (15.0, -3.25)
    assert zones[0].radius_m == 4.0
    assert zones[0].level == "level2_warning"


def test_node_without_a_known_position_is_skipped(monkeypatch):
    """웨어러블처럼 고정 좌표가 없는 노드가 섞여 들어오는 것이 정상이다.
    위험 구역은 '가스가 어디에 있는가'이지 사람이 있는 자리가 아니다."""
    monkeypatch.setattr(
        evacuation_hazards.settings, "evacuation_sensor_positions", "sensor-01:15,-3.25"
    )
    zones = evacuation_hazards.zones_from_levels({"wearable-01": AlertLevel.LEVEL3})
    assert zones == []


def test_configured_radius_actually_reaches_the_walkway(monkeypatch, topology):
    """기본 반경이 센서선(y=±3.25)에서 통행로(y=0)까지 닿아야 한다.

    사양서의 0.5m 를 그대로 쓰면 어떤 경보가 떠도 경로가 바뀌지 않아 FR-803 이
    죽은 코드가 된다. 근거는 미확보지만(config.py 참고) 최소한 기능이 동작은
    해야 하고, 그 조건을 여기서 잠근다.
    """
    from app.config import settings
    from app.services.evacuation_router import edge_hazard_multiplier

    monkeypatch.setattr(
        evacuation_hazards.settings,
        "evacuation_sensor_positions",
        "sensor-01:15,-3.25",
    )
    zones = evacuation_hazards.zones_from_levels({"sensor-01": AlertLevel.LEVEL2})

    edge = next(e for e in topology.nav_edges if e.edge_id == "e001")  # fwd-mid, y=0
    node_xy = {n.nav_node_id: (n.x_m, n.y_m) for n in topology.nav_nodes}
    assert settings.evacuation_hazard_radius_m >= 3.25
    assert edge_hazard_multiplier(edge, node_xy, zones) == 5.0


# ============================================================
# 3. 위치 신선도 (§6.1)
# ============================================================

def test_stale_position_is_rejected():
    """오래된 위치로 경로를 그리면 이미 그 자리에 없는 사람에게 길을 지시한다."""
    now = datetime(2026, 8, 21, 3, 0, 0, tzinfo=timezone.utc)
    stale = now - timedelta(seconds=30)
    assert evacuation_service.position_from_measurement(
        1.25, 1.0, "demo-local", stale, now=now
    ) is None


def test_fresh_position_is_mapped():
    now = datetime(2026, 8, 21, 3, 0, 0, tzinfo=timezone.utc)
    fresh = now - timedelta(seconds=2)
    position = evacuation_service.position_from_measurement(
        1.25, 1.0, "demo-local", fresh, now=now
    )
    assert position == Position2D(30.0, 0.0)


def test_naive_timestamp_is_treated_as_utc():
    """tz 없는 시각이 들어와도 비교가 터지지 않아야 한다."""
    now = datetime(2026, 8, 21, 3, 0, 0, tzinfo=timezone.utc)
    naive = datetime(2026, 8, 21, 2, 59, 58)
    assert evacuation_service.position_from_measurement(
        1.25, 1.0, "demo-local", naive, now=now
    ) is not None


# ============================================================
# 4. 재계산 트리거 (§3.4)
# ============================================================

def test_first_position_always_recomputes():
    assert evacuation_service.should_recompute_for_move("wearable-01", Position2D(30, 0)) is True


def test_tiny_movement_does_not_trigger_recompute(topology):
    """측위는 초당 여러 번 들어오고 필터를 거쳐도 수 cm 가 흔들린다. 매번
    다시 계산하면 히스테리시스가 무의미해진다."""
    evacuation_service.set_topology_for_test(topology)
    evacuation_service.compute_and_decide(
        "wearable-01", Position2D(30.0, 0.0), zones=[], hazard_data_available=True
    )
    assert evacuation_service.should_recompute_for_move(
        "wearable-01", Position2D(30.1, 0.0)
    ) is False


def test_half_metre_movement_triggers_recompute(topology):
    evacuation_service.set_topology_for_test(topology)
    evacuation_service.compute_and_decide(
        "wearable-01", Position2D(30.0, 0.0), zones=[], hazard_data_available=True
    )
    assert evacuation_service.should_recompute_for_move(
        "wearable-01", Position2D(30.6, 0.0)
    ) is True


# ============================================================
# 5. EXP-8.3 — 경로 교체 히스테리시스
# ============================================================

def test_first_route_is_adopted(topology):
    evacuation_service.set_topology_for_test(topology)
    route, changed = evacuation_service.compute_and_decide(
        "wearable-01", Position2D(30.0, 0.0), zones=[], hazard_data_available=True
    )
    assert changed is True
    assert route.switch_reason == "initial"
    assert route.result.target_exit_id == "trunk-fwd"


def test_identical_recomputation_does_not_replace(topology):
    """입력이 같으면 경로도 같다. route_id 가 매번 바뀌면 사고 조사 이력이
    초당 몇 건씩 쌓이고 화면은 바뀐 게 없는데 바뀐 것처럼 보인다."""
    evacuation_service.set_topology_for_test(topology)
    first, _ = evacuation_service.compute_and_decide(
        "wearable-01", Position2D(30.0, 0.0), zones=[], hazard_data_available=True
    )
    second, changed = evacuation_service.compute_and_decide(
        "wearable-01", Position2D(30.0, 0.0), zones=[], hazard_data_available=True
    )
    assert changed is False
    assert second.route_id == first.route_id


def test_oscillating_cost_does_not_flip_the_route(topology):
    """EXP-8.3 — 비용이 비슷한 두 경로 사이에서 30초간 교체 2회 이하.

    중앙 통로에서 두 출구는 정확히 63.0 동점이다. 전방 통로에 level1 구역이
    들어왔다 나갔다 하면 63 ↔ 76 사이를 오간다. 히스테리시스가 없으면 매번
    목표 출구가 뒤집힌다.
    """
    evacuation_service.set_topology_for_test(topology)
    flicker = [zone("z", 17, 0, 3, "level1_caution")]

    switches = 0
    # 30초 동안 2초 주기 재계산 = 15회. 매회 위험 구역이 붙었다 떨어진다.
    for tick in range(15):
        zones = flicker if tick % 2 == 0 else []
        _route, changed = evacuation_service.compute_and_decide(
            "wearable-01", Position2D(30.0, 0.0), zones=zones, hazard_data_available=True
        )
        if changed:
            switches += 1

    assert switches <= 2, f"경로가 {switches}회 교체됐다 — 화면이 요동친다"


def test_blocked_route_is_replaced_immediately(topology):
    """지금 쓰는 경로가 차단 구간을 지나게 되면 비율을 무시하고 즉시 바꾼다."""
    evacuation_service.set_topology_for_test(topology)
    first, _ = evacuation_service.compute_and_decide(
        "wearable-01", Position2D(30.0, 0.0), zones=[], hazard_data_available=True
    )
    assert first.result.target_exit_id == "trunk-fwd"

    blocking = [zone("z", 17, 0, 3, "level3_critical")]  # e001 차단
    second, changed = evacuation_service.compute_and_decide(
        "wearable-01", Position2D(30.0, 0.0), zones=blocking, hazard_data_available=True
    )

    assert changed is True
    assert second.switch_reason in {"route_blocked", "hazard_changed"}
    assert second.result.target_exit_id == "trunk-aft"
    assert second.route_id != first.route_id


def test_status_change_always_replaces(topology):
    """safe 였다가 no_safe_route 가 된 것은 '조금 비싸진' 것이 아니다."""
    evacuation_service.set_topology_for_test(topology)
    evacuation_service.compute_and_decide(
        "wearable-01", Position2D(30.0, 0.0), zones=[], hazard_data_available=True
    )

    both_trunks = [
        zone("f", 3, 0, 2, "level3_critical"),
        zone("a", 57, 0, 2, "level3_critical"),
    ]
    route, changed = evacuation_service.compute_and_decide(
        "wearable-01", Position2D(30.0, 0.0), zones=both_trunks, hazard_data_available=True
    )

    assert changed is True
    assert route.result.route_status == "no_safe_route"


def test_moving_to_another_graph_node_replaces(topology):
    """옛 경로를 유지하면 이미 지나온 노드로 되돌아가는 선이 그려진다."""
    evacuation_service.set_topology_for_test(topology)
    evacuation_service.compute_and_decide(
        "wearable-01", Position2D(30.0, 0.0), zones=[], hazard_data_available=True
    )
    route, changed = evacuation_service.compute_and_decide(
        "wearable-01", Position2D(5.0, 0.0), zones=[], hazard_data_available=True
    )
    assert changed is True
    assert route.switch_reason == "position_moved"
    assert route.result.entry_nav_node_id == "nav.floor.fwd"


def test_kept_route_still_follows_the_worker(topology):
    """경로를 유지해도 첫 waypoint 는 실제 위치를 따라가야 한다 (§3.3 MUST).
    그러지 않으면 선이 작업자에게서 떨어져 시작한다."""
    evacuation_service.set_topology_for_test(topology)
    evacuation_service.compute_and_decide(
        "wearable-01", Position2D(30.0, 0.0), zones=[], hazard_data_available=True
    )
    route, changed = evacuation_service.compute_and_decide(
        "wearable-01", Position2D(30.2, 0.1), zones=[], hazard_data_available=True
    )
    assert changed is False
    assert (route.result.waypoints[0].x_m, route.result.waypoints[0].y_m) == (30.2, 0.1)


def test_disabled_feature_yields_unavailable_not_no_safe_route():
    """토폴로지가 없는 것은 설정 문제다. no_safe_route 는 level3 경보를 발령하는데
    설정 오류로 경보를 울리면 안 된다."""
    route, _changed = evacuation_service.compute_and_decide(
        "wearable-01", Position2D(30.0, 0.0), zones=[], hazard_data_available=True
    )
    assert route.result.route_status == "unavailable"
    assert route.result.unavailable_reason == "topology_invalid"
