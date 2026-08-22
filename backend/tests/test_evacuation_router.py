"""위험 가중 경로 계산 (FR-802/803, EXP-8).

저장소에 실제로 든 `config/space_topology.yaml` 을 그래프로 쓴다. 테스트 전용
그래프를 따로 만들면 시연에 쓰는 그래프는 검증되지 않은 채로 남는다.

그 그래프의 손계산 (비용 = length_m x traverse_factor x hazard_multiplier):

    exit.trunk-fwd  ← ladder(14 x 2.5 = 35) ← nav.ladder.fwd.bottom
    nav.ladder.fwd.bottom ← walk(2) ← nav.floor.fwd        ⇒ fwd 에서 출구까지 37
    nav.floor.mid ← walk(26) ← nav.floor.fwd               ⇒ mid 에서 전방까지 63
    nav.floor.aft ← walk(2) + ladder(35)                   ⇒ aft 에서 후방까지 37
    nav.floor.mid ← walk(26) ← nav.floor.aft               ⇒ mid 에서 후방까지 63

중앙 통로에서 두 출구가 **정확히 63.0 으로 동점**이다. 의도된 설계이고, priority
tie-break 와 경로 안정성을 시험하는 지점이 여기다.
"""
from __future__ import annotations

import math

import pytest

from app.models.evacuation import HazardZone, NavTopology
from app.services.evacuation_router import (
    BLOCKED,
    Position2D,
    _segment_circle_intersects,
    compute_route,
    edge_hazard_multiplier,
)
from app.services.evacuation_topology import load_topology_file


@pytest.fixture(scope="module")
def topology() -> NavTopology:
    return load_topology_file()


def zone(zone_id: str, x: float, y: float, r: float, level: str) -> HazardZone:
    return HazardZone(zone_id=zone_id, center_x_m=x, center_y_m=y, radius_m=r, level=level)


def waypoint_ids(result) -> list[str | None]:
    return [w.nav_node_id for w in result.waypoints]


# ============================================================
# 1. 선분-원 교차 — 비용 함수의 기반
# ============================================================

def test_circle_crossing_the_middle_of_a_segment_is_detected():
    """양 끝점만 검사하면 놓치는 경우. 통로 한가운데 고인 가스가 정확히 이 형태다."""
    # 선분 (0,0)-(10,0), 원 중심 (5,0) 반지름 1 — 양 끝점은 원 밖이다.
    assert math.hypot(0 - 5, 0) > 1 and math.hypot(10 - 5, 0) > 1
    assert _segment_circle_intersects(0, 0, 10, 0, 5, 0, 1) is True


def test_circle_beside_the_segment_is_not_detected():
    assert _segment_circle_intersects(0, 0, 10, 0, 5, 3, 1) is False


def test_circle_touching_an_endpoint_is_detected():
    assert _segment_circle_intersects(0, 0, 10, 0, 11, 0, 1.5) is True


def test_overlapping_zones_take_the_maximum_not_the_product(topology):
    """여러 구역과 겹치면 최댓값을 쓴다 (§3.2).

    곱하면 작은 level1 세 개(1.5^3 = 3.375)가 치명 구역보다 비싸지는 역전이 생긴다.
    """
    edge = next(e for e in topology.nav_edges if e.edge_id == "e001")  # fwd(4,0)-mid(30,0)
    node_xy = {n.nav_node_id: (n.x_m, n.y_m) for n in topology.nav_nodes}
    zones = [
        zone("z1", 10, 0, 2, "level1_caution"),
        zone("z2", 17, 0, 2, "level1_caution"),
        zone("z3", 24, 0, 2, "level1_caution"),
    ]
    assert edge_hazard_multiplier(edge, node_xy, zones) == 1.5


def test_level3_zone_blocks_the_edge(topology):
    edge = next(e for e in topology.nav_edges if e.edge_id == "e001")
    node_xy = {n.nav_node_id: (n.x_m, n.y_m) for n in topology.nav_nodes}
    zones = [zone("z", 17, 0, 3, "level3_critical")]
    assert edge_hazard_multiplier(edge, node_xy, zones) == BLOCKED
    # 완화 모드에서는 유한한 큰 값이 된다 (§3.5).
    assert edge_hazard_multiplier(edge, node_xy, zones, relaxed=True) == 50.0


# ============================================================
# 2. EXP-8 — 손계산 최적 경로와 일치
# ============================================================

def test_safe_route_matches_hand_calculation(topology):
    result = compute_route(topology, [], Position2D(29.4, 0.6))

    assert result.route_status == "safe"
    assert result.entry_nav_node_id == "nav.floor.mid"
    assert result.target_exit_id == "trunk-fwd"
    assert result.total_cost == 63.0          # 26 + 2 + 14x2.5
    assert result.total_length_m == 42.0      # 26 + 2 + 14
    assert result.estimated_seconds == 79     # 63 / 0.8 walk_speed
    assert result.hazard_multiplier_max == 1.0
    assert waypoint_ids(result) == [
        None,
        "nav.floor.mid",
        "nav.floor.fwd",
        "nav.ladder.fwd.bottom",
        "nav.exit.trunk-fwd",
    ]


def test_first_waypoint_is_the_workers_actual_position(topology):
    """스냅된 노드가 아니라 실측 위치여야 한다 (§3.3 MUST).

    경로가 작업자에게서 떨어져 시작하면 화면상 어디로 가라는 건지 알 수 없다.
    """
    result = compute_route(topology, [], Position2D(29.4, 0.6))
    first = result.waypoints[0]
    assert first.nav_node_id is None
    assert (first.x_m, first.y_m) == (29.4, 0.6)


def test_ladder_segment_is_marked(topology):
    """사다리 구간이 표시되어야 3D 트윈이 수직으로 그린다."""
    result = compute_route(topology, [], Position2D(29.4, 0.6))
    kinds = [w.edge_kind_to_next for w in result.waypoints]
    assert kinds[-2] == "ladder"
    assert kinds[-1] is None  # 마지막 waypoint 는 다음 간선이 없다


# ============================================================
# 3. EXP-8.1 — 위험 구역이 경로를 바꾼다
# ============================================================

def test_level2_zone_pushes_the_route_to_the_other_exit(topology):
    """전방 통로가 비싸지면 후방 트렁크로 간다.

    mid→fwd 는 26 x 5.0 = 130 이 되어 전방 경로가 167, 후방은 그대로 63 이다.
    """
    zones = [zone("z", 17, 0, 3, "level2_warning")]
    result = compute_route(topology, zones, Position2D(29.4, 0.6))

    assert result.target_exit_id == "trunk-aft"
    assert result.total_cost == 63.0
    # 고른 경로 자체는 위험 구역을 지나지 않으므로 safe 다.
    assert result.route_status == "safe"
    assert result.hazard_multiplier_max == 1.0


def test_level3_zone_blocks_and_reroutes(topology):
    zones = [zone("z", 17, 0, 3, "level3_critical")]
    result = compute_route(topology, zones, Position2D(29.4, 0.6))

    assert result.route_status == "safe"
    assert result.target_exit_id == "trunk-aft"
    assert "nav.floor.fwd" not in waypoint_ids(result)


def test_detour_through_the_starboard_bypass(topology):
    """이 기능의 핵심 — 가장 가까운 출구가 막히면 멀리 돌아간다.

    선미 작업자 기준 후방 트렁크가 37 로 가장 싸다. 그 접근로와 중앙 통로를 모두
    level3 로 막으면 우현 우회로를 타고 전방으로 나가야 한다.

        aft →(26.5 x 1.5) stbd →(26.5) fwd →(2) ladder →(35) exit  = 103.25
    """
    # 반경은 의도한 구간만 덮도록 좁게 잡는다. aft-trunk 를 1.5 로 키우면
    # nav.floor.aft(56,0) 까지 닿아 우회로(e004)마저 막혀 no_safe_route 가 된다.
    zones = [
        zone("aft-trunk", 57, 0, 0.5, "level3_critical"),   # e007 차단
        zone("mid-run", 43, 0, 1.5, "level3_critical"),      # e002 차단
        zone("stbd-leak", 43, 2.5, 2, "level1_caution"),     # e004 위 level1
    ]
    result = compute_route(topology, zones, Position2D(54.0, 0.8))

    assert result.entry_nav_node_id == "nav.floor.aft"
    assert result.target_exit_id == "trunk-fwd"
    assert result.route_status == "degraded"
    assert result.hazard_multiplier_max == 1.5
    assert "passes_hazard_level1" in result.warnings
    assert result.total_length_m == 69.0
    assert result.total_cost == 103.25
    assert "nav.floor.stbd" in waypoint_ids(result)


# ============================================================
# 4. EXP-8.2 — 전 출구 차단
# ============================================================

def test_all_exits_blocked_still_returns_a_route(topology):
    """경로를 숨기지 않는다 (§3.5). 대피 중에 빈 화면을 주는 것이 최악이다."""
    zones = [
        zone("fwd-trunk", 3, 0, 2, "level3_critical"),
        zone("aft-trunk", 57, 0, 2, "level3_critical"),
    ]
    result = compute_route(topology, zones, Position2D(29.4, 0.6))

    assert result.route_status == "no_safe_route"
    assert result.waypoints, "최소 위험 경로가 비어 있다"
    assert result.hazard_multiplier_max == 50.0
    assert "passes_hazard_level3" in result.warnings
    # 이 반경이면 트렁크 하단 주변 구간이 전부 걸린다 — 중앙 통로(e001),
    # 하단 접근로(e005), 그리고 **사다리(e006)까지**. 사다리는 x·y 가 같고 z 만
    # 변하므로 평면에서 한 점으로 접히고, 그 점이 구역 안에 들어온다.
    # 트렁크 바닥에 가스가 고이면 기어 올라갈 수 없다는 뜻이라 물리적으로도 맞다.
    # 63 x 50 — 경로 전체가 완화된 차단 비용을 문다.
    assert result.total_cost == 3150.0
    assert {b.exit_id for b in result.blocked_exits} == {"trunk-fwd", "trunk-aft"}
    assert all(b.reason == "hazard_level3" for b in result.blocked_exits)


def test_vertical_ladder_collapses_to_a_point_in_plan(topology):
    """사다리는 평면에서 길이 0 인 선분이다. 하단을 덮는 구역이 사다리도 막는다.

    의도된 동작이다. 다만 조용히 일어나면 "왜 사다리가 막혔지"를 알 수 없으므로
    여기서 명시적으로 잠근다.
    """
    ladder = next(e for e in topology.nav_edges if e.edge_id == "e006")
    node_xy = {n.nav_node_id: (n.x_m, n.y_m) for n in topology.nav_nodes}
    assert node_xy[ladder.from_node_id] == node_xy[ladder.to_node_id]

    at_base = [zone("z", 2, 0, 0.5, "level3_critical")]
    assert edge_hazard_multiplier(ladder, node_xy, at_base) == BLOCKED


def test_no_usable_exit_is_no_safe_route(topology):
    """관리자가 전 출구를 닫은 경우. 위험이 아니라 설정이다."""
    closed = topology.model_copy(deep=True)
    for exit_ in closed.exits:
        exit_.is_usable = False

    result = compute_route(closed, [], Position2D(29.4, 0.6))

    assert result.route_status == "no_safe_route"
    assert {b.reason for b in result.blocked_exits} == {"disabled"}


def test_disconnected_graph_is_unavailable_not_no_safe_route(topology):
    """끊긴 그래프는 위험 상황이 아니라 데이터 문제다. 구분해야 한다 —
    no_safe_route 는 level3 경보를 발령하는데, 설정 오류로 경보를 울리면 안 된다."""
    broken = topology.model_copy(deep=True)
    for edge in broken.nav_edges:
        if edge.edge_id in {"e005", "e006", "e007", "e008"}:
            edge.is_usable = False

    result = compute_route(broken, [], Position2D(29.4, 0.6))

    assert result.route_status == "unavailable"
    assert result.unavailable_reason == "no_reachable_exit"


# ============================================================
# 5. EXP-8.3 — 결정론 (경로 안정성의 전제)
# ============================================================

def test_tie_is_broken_by_exit_priority_deterministically(topology):
    """중앙 통로에서 두 출구는 정확히 동점이다. tie-break 가 없으면 재계산할
    때마다 목표가 바뀌어 화면이 요동친다."""
    results = [compute_route(topology, [], Position2D(30.0, 0.0)) for _ in range(5)]
    assert {r.target_exit_id for r in results} == {"trunk-fwd"}  # priority 1
    assert {r.total_cost for r in results} == {63.0}


def test_priority_actually_decides_the_tie(topology):
    """priority 를 뒤집으면 목표도 뒤집혀야 한다 — 우연히 순서가 맞은 게 아니다."""
    flipped = topology.model_copy(deep=True)
    for exit_ in flipped.exits:
        exit_.priority = 1 if exit_.exit_id == "trunk-aft" else 2

    result = compute_route(flipped, [], Position2D(30.0, 0.0))
    assert result.target_exit_id == "trunk-aft"
    assert result.total_cost == 63.0


# ============================================================
# 6. 입력 결손 (§6.1, §3.3)
# ============================================================

def test_missing_position_is_unavailable(topology):
    result = compute_route(topology, [], None)
    assert result.route_status == "unavailable"
    assert result.unavailable_reason == "no_position"
    assert result.waypoints == []


def test_far_from_the_graph_is_off_graph(topology):
    """억지로 붙이지 않는다 (§3.3). 5m 넘게 떨어진 사람에게 그리는 경로는
    실제로 지나갈 수 없는 길일 수 있다."""
    result = compute_route(topology, [], Position2D(30.0, 40.0))
    assert result.route_status == "unavailable"
    assert result.unavailable_reason == "off_graph"


def test_snap_uses_only_the_assumed_level(topology):
    """UWB 가 2D 라 층을 모른다. 층을 섞으면 사다리 위 노드에 붙어 경로가
    공중에서 시작한다."""
    result = compute_route(topology, [], Position2D(2.0, 0.0))
    # (2,0) 에 가장 가까운 노드는 L1 인 exit.trunk-fwd 와 좌표가 같지만,
    # L0 의 ladder.fwd.bottom 에 붙어야 한다.
    assert result.entry_nav_node_id == "nav.ladder.fwd.bottom"


def test_missing_hazard_data_is_surfaced(topology):
    """위험 정보 없이 계산한 경로를 '안전'으로만 보여주면 안 된다 (§6.1)."""
    result = compute_route(topology, [], Position2D(29.4, 0.6), hazard_data_available=False)
    assert "hazard_data_missing" in result.warnings


def test_long_snap_distance_is_warned(topology):
    result = compute_route(topology, [], Position2D(54.0, 0.8))
    assert result.snap_distance_m == 2.15
    assert "long_snap_distance" in result.warnings


# ============================================================
# 7. 통행 불가 구간
# ============================================================

def test_unusable_edge_is_excluded(topology):
    """점검으로 닫은 사다리는 지나갈 수 없다. 다른 출구로 가야 한다."""
    patched = topology.model_copy(deep=True)
    for edge in patched.nav_edges:
        if edge.edge_id == "e006":  # 전방 트렁크 사다리
            edge.is_usable = False

    result = compute_route(patched, [], Position2D(29.4, 0.6))
    assert result.target_exit_id == "trunk-aft"
    assert "nav.ladder.fwd.bottom" not in waypoint_ids(result)
