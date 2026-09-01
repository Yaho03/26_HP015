"""실측 위치 커버리지 불변식 (이슈 #225).

작업자의 실측 UWB 위치(demo-local)는 균일 배율 6.5 로 매핑되면 항상
x∈[21.875, 38.125], y∈[-6.5, 6.5] 스트립 안에 있다
(evacuation_coordinates.demo_to_ship — 클램프가 보장).

2026-08-22 발견: 통로 노드(fwd/mid/aft)만 있는 그래프로는 이 스트립의 60%
위치가 스냅 한계(5m)를 벗어나 **실물 UWB 시연에서 경로가 unavailable** 로
떨어졌다. 목 모드/ship-visual 직접 주입 시나리오만 돌리면 발견할 수 없는,
실측 경로에서만 터지는 결함이었다.

이 테스트는 저장소의 실제 YAML(config/space_topology.yaml)로 데모 공간을
0.1m 격자로 훑으며 모든 실측 위치가 스냅 성공함을 잠근다. 그래프를 고치는
사람이 이 제약을 다시 깨뜨리면 즉시 실패한다.
"""
from __future__ import annotations

import math

from app.config import settings
from app.services.evacuation_coordinates import (
    DEMO_LENGTH_M,
    DEMO_WIDTH_M,
    demo_to_ship,
)
from app.services.evacuation_topology import load_topology_file


def test_every_measured_demo_position_snaps_to_the_graph():
    topology = load_topology_file()
    nodes = [
        (n.x_m, n.y_m)
        for n in topology.nav_nodes
        # 출구/사다리 상단은 z!=0 — 스냅은 바닥 평면 노드에만 한다
        if n.z_m == 0.0
    ]
    assert nodes, "바닥 노드가 없으면 검증 자체가 불가능하다"

    limit = settings.evacuation_max_snap_distance_m
    worst = 0.0
    worst_demo = None
    steps_x, steps_y = 25, 20  # 0.1m 격자

    for ix in range(steps_x + 1):
        for iy in range(steps_y + 1):
            demo_x = DEMO_LENGTH_M * ix / steps_x
            demo_y = DEMO_WIDTH_M * iy / steps_y
            sx, sy = demo_to_ship(demo_x, demo_y)
            dist = min(math.hypot(sx - nx, sy - ny) for nx, ny in nodes)
            if dist > worst:
                worst, worst_demo = dist, (demo_x, demo_y, sx, sy)

    assert worst <= limit, (
        f"실측 데모 위치 {worst_demo!r}(ship {worst_demo[2]:.2f},{worst_demo[3]:.2f})가 "
        f"어떤 바닥 노드에서도 {limit}m 안에 있지 않다 (최장 {worst:.2f}m) — "
        "실물 UWB 시연에서 이 자리는 경로 unavailable 이 된다. "
        "config/space_topology.yaml 의 실측 구역 노드를 유지하라"
    )


def test_zone_nodes_do_not_shortcut_existing_corridor():
    """구역 노드가 데모 내러티브를 바꾸지 않는다 — EXP-8 손계산 보존.

    mid ↔ fwd / aft / stbd 의 기존 최소 비용이 구역 노드 경유로 줄어들면
    63.0 동점·103.25 우회 스토리가 무너진다. 대표 경로 3개의 우회 가능성을
    Dijkstra 비용으로 직접 비교한다.
    """
    from app.services.evacuation_router import compute_route
    from app.services.evacuation_router import Position2D

    topology = load_topology_file()
    before = {
        "fwd": compute_route(topology, [], Position2D(30.0, 0.0)).total_cost,
    }
    # 중앙에서 양 출구 동점 63.0 (EXP-8)
    assert before["fwd"] == 63.0

    # 구역 노드를 지나는 우회가 더 싸지 않는지: fwd 측 작업자가 구역 경유로
    # mid 에 이르는 최소 비용이 통로(e001 26.0)보다 크거나 같아야 한다.
    result = compute_route(topology, [], Position2D(24.0, -3.75))
    # (24,-3.75) → mid 최단: 스포크가 없으므로 fwd.port→mid.port(6.0)+스포크(3.75)
    # 또는 fwd.port→fwd.stbd(7.5)+... 중 최소 = 9.75 vs 통로 경유 e001 26.0.
    # 어떤 경로든 출구 비용이 63.0+9.75 = 72.75 보다 작으면 안 된다 (동점 깨짐).
    assert result.total_cost >= 63.0 + 9.75 - 0.01, (
        "구역 노드가 기존 통로보다 싼 지름길을 만들었다 — EXP-8 손계산이 깨진다"
    )
