"""위험 가중 최소비용 경로 계산 (FR-802/803, 12_EVACUATION_ROUTE_SPEC §3).

**순수 모듈이다.** DB 도 전역 상태도 건드리지 않는다. 같은 입력이면 같은 결과가
나온다. 경로 교체 히스테리시스처럼 "직전에 무엇을 보여줬는가"에 의존하는 결정은
호출부(evacuation_service)가 맡는다 — 그래야 손계산과 대조하는 테스트가 가능하다
(EXP-8).

── 왜 역방향 다중 소스인가 ─────────────────────────────────────────────
구하려는 값은 "각 노드에서 출구까지의 최소 비용"이다. 출구마다 정방향 Dijkstra 를
돌리면 출구 수만큼 반복하게 된다. 대신 **사용 가능한 출구 전부를 거리 0 의 소스로
두고 간선을 거꾸로 따라가면** 한 번의 실행으로 모든 노드의 답이 나온다 (§3.1).

노드가 수십 개 규모라 A* 휴리스틱의 이득이 없다. Dijkstra 로 충분하다.
"""
from __future__ import annotations

import heapq
import math
from dataclasses import dataclass

from app.models.evacuation import (
    BlockedExit,
    HazardZone,
    NavEdge,
    NavTopology,
    RouteResult,
    RouteWaypoint,
)

# 위험 등급별 통행 비용 배수 (§3.2).
# level3 는 차단이다 — 대안이 있으면 절대 지나가지 않는다.
HAZARD_MULTIPLIER: dict[str, float] = {
    "level1_caution": 1.5,
    "level2_warning": 5.0,
}
BLOCKED = math.inf

# 전 출구가 막혔을 때만 쓰는 완화값 (§3.5). 무한대를 유한한 큰 수로 바꿔
# "최소 위험 경로"를 뽑아낸다. 50 은 level2(5.0)보다 10배 비싸므로, 지날 수 있는
# level2 우회로가 하나라도 있으면 그쪽이 반드시 선택된다.
RELAXED_BLOCKED_MULTIPLIER = 50.0

DEFAULT_MAX_SNAP_DISTANCE_M = 5.0
DEFAULT_WALK_SPEED_MPS = 0.8


@dataclass(frozen=True)
class Position2D:
    """작업자의 실측 위치 (ship-visual, 평면). UWB 가 2D 라 z 는 쓰지 않는다."""

    x_m: float
    y_m: float


def _segment_circle_intersects(
    ax: float, ay: float, bx: float, by: float, cx: float, cy: float, r: float
) -> bool:
    """선분 AB 가 중심 C 반지름 r 인 원과 만나는가.

    선분 위에서 원 중심에 가장 가까운 점까지의 거리를 본다. 양 끝점만 검사하면
    구간 한가운데를 가로지르는 원을 놓친다 — 통로 중간에 가스가 고인 경우가 정확히
    그 형태다.
    """
    abx, aby = bx - ax, by - ay
    seg_len_sq = abx * abx + aby * aby
    if seg_len_sq == 0.0:
        return math.hypot(ax - cx, ay - cy) <= r

    # C 를 AB 위에 정사영한 매개변수 t 를 [0,1] 로 자른다.
    t = ((cx - ax) * abx + (cy - ay) * aby) / seg_len_sq
    t = max(0.0, min(1.0, t))
    closest_x = ax + t * abx
    closest_y = ay + t * aby
    return math.hypot(closest_x - cx, closest_y - cy) <= r


def edge_hazard_multiplier(
    edge: NavEdge,
    node_xy: dict[str, tuple[float, float]],
    zones: list[HazardZone],
    *,
    relaxed: bool = False,
) -> float:
    """이 구간에 걸리는 위험 가중치.

    여러 구역과 겹치면 **곱이 아니라 최댓값**을 쓴다 (§3.2). 곱하면 작은 level1
    구역 세 개(1.5^3 = 3.4)가 치명 구역 하나보다 싸지거나, 반대로 사소한 구역이
    여러 개 겹쳤다는 이유로 통행 불가에 가까워지는 역전이 생긴다.
    """
    ax, ay = node_xy[edge.from_node_id]
    bx, by = node_xy[edge.to_node_id]

    worst = 1.0
    for zone in zones:
        if not _segment_circle_intersects(ax, ay, bx, by, zone.center_x_m, zone.center_y_m, zone.radius_m):
            continue
        if zone.level == "level3_critical":
            multiplier = RELAXED_BLOCKED_MULTIPLIER if relaxed else BLOCKED
        else:
            multiplier = HAZARD_MULTIPLIER.get(zone.level, 1.0)
        worst = max(worst, multiplier)
    return worst


@dataclass
class _Graph:
    """비용이 매겨진 역방향 인접 리스트.

    reverse[v] = [(u, cost, edge)] — "u 에서 v 로 갈 수 있고 그 비용이 cost".
    출구에서 시작해 이걸 따라가면 각 노드의 '출구까지 최소 비용'이 나온다.
    """

    reverse: dict[str, list[tuple[str, float, NavEdge]]]
    forward_cost: dict[tuple[str, str], tuple[float, NavEdge]]


def _build_graph(
    topology: NavTopology,
    zones: list[HazardZone],
    *,
    relaxed: bool,
) -> _Graph:
    node_xy = {n.nav_node_id: (n.x_m, n.y_m) for n in topology.nav_nodes}
    reverse: dict[str, list[tuple[str, float, NavEdge]]] = {
        n.nav_node_id: [] for n in topology.nav_nodes
    }
    forward_cost: dict[tuple[str, str], tuple[float, NavEdge]] = {}

    for edge in topology.nav_edges:
        if not edge.is_usable:
            continue  # 점검·폐쇄된 통로는 그래프에 없다.
        multiplier = edge_hazard_multiplier(edge, node_xy, zones, relaxed=relaxed)
        cost = edge.length_m * edge.traverse_factor * multiplier
        if cost == BLOCKED:
            continue  # 차단된 구간은 아예 놓지 않는다.

        pairs = [(edge.from_node_id, edge.to_node_id)]
        if edge.bidirectional:
            pairs.append((edge.to_node_id, edge.from_node_id))
        for u, v in pairs:
            reverse[v].append((u, cost, edge))
            # 같은 노드 쌍에 여러 간선이 있으면 싼 쪽만 남긴다.
            prev = forward_cost.get((u, v))
            if prev is None or cost < prev[0]:
                forward_cost[(u, v)] = (cost, edge)

    return _Graph(reverse=reverse, forward_cost=forward_cost)


def _dijkstra_to_exits(
    graph: _Graph,
    exit_nodes: list[tuple[str, int, str]],
) -> tuple[dict[str, float], dict[str, str], dict[str, str]]:
    """출구 전체를 소스로 하는 역방향 Dijkstra 한 번.

    exit_nodes: (nav_node_id, priority, exit_id) 목록.

    반환: dist(출구까지 최소 비용), next_hop(다음에 갈 노드), via_exit(도달할 출구).

    우선순위 큐에 (비용, 출구 priority, 노드) 를 넣는다. 비용이 같을 때 priority 가
    낮은 출구가 먼저 확정되므로, 동점인 두 출구 사이에서 목표가 매번 바뀌는 일이
    없다 — 중앙 통로에서 전방·후방 트렁크가 정확히 동점인 골격이 그 경우다.
    """
    dist: dict[str, float] = {}
    next_hop: dict[str, str] = {}
    via_exit: dict[str, str] = {}

    heap: list[tuple[float, int, str]] = []
    for node_id, priority, exit_id in exit_nodes:
        if node_id in dist:
            continue
        heapq.heappush(heap, (0.0, priority, node_id))
        via_exit[node_id] = exit_id

    settled: set[str] = set()
    while heap:
        cost, priority, node = heapq.heappop(heap)
        if node in settled:
            continue
        settled.add(node)
        dist[node] = cost

        for prev_node, edge_cost, _edge in graph.reverse.get(node, ()):
            if prev_node in settled:
                continue
            new_cost = cost + edge_cost
            known = dist.get(prev_node)
            if known is not None and known <= new_cost:
                continue
            # 아직 확정 전이므로 잠정값을 갱신한다. heap 에 중복이 쌓이지만
            # settled 검사로 걸러지고, 노드 수십 개 규모에서는 문제가 되지 않는다.
            if prev_node not in dist or new_cost < dist[prev_node]:
                dist[prev_node] = new_cost
                next_hop[prev_node] = node
                via_exit[prev_node] = via_exit[node]
                heapq.heappush(heap, (new_cost, priority, prev_node))

    return dist, next_hop, via_exit


def _snap(
    topology: NavTopology, position: Position2D, assumed_level_id: str
) -> tuple[str | None, float]:
    """작업자 위치를 가장 가까운 nav_node 에 붙인다.

    비계 층을 가정한 노드만 후보로 둔다. UWB 가 2D 라 작업자가 위층에 있어도
    바닥으로 읽히는데, 여기서 층을 섞으면 사다리 위 노드에 스냅되어 경로가
    공중에서 시작한다.
    """
    best_id: str | None = None
    best_dist = math.inf
    for node in topology.nav_nodes:
        if node.level_id != assumed_level_id:
            continue
        d = math.hypot(node.x_m - position.x_m, node.y_m - position.y_m)
        if d < best_dist:
            best_dist, best_id = d, node.nav_node_id
    return best_id, best_dist


def _walk(
    graph: _Graph,
    next_hop: dict[str, str],
    start: str,
    exit_node_ids: set[str],
) -> list[tuple[str, NavEdge | None]] | None:
    """next_hop 을 따라 출구까지 걸어가며 (노드, 다음 간선) 목록을 만든다.

    노드 수를 상한으로 두고 끊는다. 정상적인 Dijkstra 결과에는 사이클이 없지만,
    입력이 이상할 때 무한 루프로 서버를 멈추는 것보다 경로를 포기하는 편이 낫다.
    """
    path: list[tuple[str, NavEdge | None]] = []
    current = start
    limit = len(graph.reverse) + 1
    while limit > 0:
        limit -= 1
        if current in exit_node_ids:
            path.append((current, None))
            return path
        nxt = next_hop.get(current)
        if nxt is None:
            return None
        edge_entry = graph.forward_cost.get((current, nxt))
        if edge_entry is None:
            return None
        path.append((current, edge_entry[1]))
        current = nxt
    return None


def compute_route(
    topology: NavTopology,
    zones: list[HazardZone],
    position: Position2D | None,
    *,
    assumed_level_id: str = "L0",
    max_snap_distance_m: float = DEFAULT_MAX_SNAP_DISTANCE_M,
    walk_speed_mps: float = DEFAULT_WALK_SPEED_MPS,
    hazard_data_available: bool = True,
) -> RouteResult:
    """작업자 위치에서 사용 가능한 출구까지의 위험 가중 최소비용 경로.

    실패해도 예외를 던지지 않는다. `route_status` 와 `unavailable_reason` 으로
    말한다 — 대피 화면에서 예외는 빈 화면이 되고, 빈 화면이 최악이다.
    """
    warnings: list[str] = []
    if not hazard_data_available:
        # 위험 정보 없이 계산한 경로를 "안전"으로 보여주면 안 된다 (§6.1).
        warnings.append("hazard_data_missing")

    if position is None:
        return RouteResult(
            route_status="unavailable",
            unavailable_reason="no_position",
            assumed_level_id=assumed_level_id,
            warnings=warnings,
        )

    blocked_exits = [
        BlockedExit(exit_id=x.exit_id, reason="disabled")
        for x in topology.exits
        if not x.is_usable
    ]
    usable_exits = [x for x in topology.exits if x.is_usable]
    node_ids = topology.node_ids
    exit_sources = [
        (x.nav_node_id, x.priority, x.exit_id) for x in usable_exits if x.nav_node_id in node_ids
    ]

    entry, snap_distance = _snap(topology, position, assumed_level_id)
    if entry is None or snap_distance > max_snap_distance_m:
        # 억지로 붙이지 않는다 (§3.3). 그래프에서 5m 넘게 떨어진 사람에게 그리는
        # 경로는 실제로 지나갈 수 없는 길일 수 있다.
        return RouteResult(
            route_status="unavailable",
            unavailable_reason="off_graph",
            assumed_level_id=assumed_level_id,
            entry_nav_node_id=entry,
            snap_distance_m=None if entry is None else round(snap_distance, 2),
            blocked_exits=blocked_exits,
            warnings=warnings,
        )

    if not exit_sources:
        return RouteResult(
            route_status="no_safe_route",
            assumed_level_id=assumed_level_id,
            entry_nav_node_id=entry,
            snap_distance_m=round(snap_distance, 2),
            blocked_exits=blocked_exits,
            warnings=warnings,
        )

    # 1차 — level3 는 차단. 대안이 있으면 절대 지나가지 않는다.
    result = _solve(
        topology, zones, entry, exit_sources, position, snap_distance,
        assumed_level_id=assumed_level_id, walk_speed_mps=walk_speed_mps,
        relaxed=False, warnings=warnings, disabled_exits=blocked_exits,
    )
    if result is not None:
        return result

    # 2차 — 전 출구가 막혔다. BLOCKED 를 완화해 최소 위험 경로를 뽑는다 (§3.5).
    # 경로를 숨기지 않는다. 대피 중에 빈 화면을 주는 것이 최악의 설계다.
    relaxed_result = _solve(
        topology, zones, entry, exit_sources, position, snap_distance,
        assumed_level_id=assumed_level_id, walk_speed_mps=walk_speed_mps,
        relaxed=True, warnings=warnings, disabled_exits=blocked_exits,
    )
    if relaxed_result is not None:
        relaxed_result.route_status = "no_safe_route"
        relaxed_result.blocked_exits = blocked_exits + [
            BlockedExit(exit_id=x.exit_id, reason="hazard_level3") for x in usable_exits
        ]
        if "passes_hazard_level3" not in relaxed_result.warnings:
            relaxed_result.warnings.append("passes_hazard_level3")
        return relaxed_result

    # 완화해도 못 간다 — 위험이 아니라 그래프가 끊긴 것이다.
    return RouteResult(
        route_status="unavailable",
        unavailable_reason="no_reachable_exit",
        assumed_level_id=assumed_level_id,
        entry_nav_node_id=entry,
        snap_distance_m=round(snap_distance, 2),
        blocked_exits=blocked_exits
        + [BlockedExit(exit_id=x.exit_id, reason="unreachable") for x in usable_exits],
        warnings=warnings,
    )


def _solve(
    topology: NavTopology,
    zones: list[HazardZone],
    entry: str,
    exit_sources: list[tuple[str, int, str]],
    position: Position2D,
    snap_distance: float,
    *,
    assumed_level_id: str,
    walk_speed_mps: float,
    relaxed: bool,
    warnings: list[str],
    disabled_exits: list[BlockedExit],
) -> RouteResult | None:
    """한 번의 Dijkstra + 경로 복원. 도달 불가면 None."""
    graph = _build_graph(topology, zones, relaxed=relaxed)
    dist, next_hop, via_exit = _dijkstra_to_exits(graph, exit_sources)

    if entry not in dist or dist[entry] == BLOCKED:
        return None

    exit_node_ids = {node_id for node_id, _p, _e in exit_sources}
    path = _walk(graph, next_hop, entry, exit_node_ids)
    if path is None:
        return None

    node_by_id = {n.nav_node_id: n for n in topology.nav_nodes}
    node_xy = {n.nav_node_id: (n.x_m, n.y_m) for n in topology.nav_nodes}

    # seq 0 은 스냅된 노드가 아니라 작업자의 **실제 위치**다 (§3.3 MUST).
    # 화면에서 경로가 작업자와 떨어져 시작하면 어디로 가라는 건지 알 수 없다.
    entry_node = node_by_id[entry]
    waypoints: list[RouteWaypoint] = [
        RouteWaypoint(
            seq=0,
            nav_node_id=None,
            x_m=position.x_m,
            y_m=position.y_m,
            z_m=entry_node.z_m,
            level_id=assumed_level_id,
            edge_kind_to_next="walk",
            label="현재 위치",
        )
    ]

    total_length = 0.0
    total_cost = 0.0
    hazard_max = 1.0
    for index, (node_id, edge) in enumerate(path):
        node = node_by_id[node_id]
        waypoints.append(
            RouteWaypoint(
                seq=index + 1,
                nav_node_id=node_id,
                x_m=node.x_m,
                y_m=node.y_m,
                z_m=node.z_m,
                level_id=node.level_id,
                edge_kind_to_next=edge.kind.value if edge is not None else None,
                label=node.label,
            )
        )
        if edge is not None:
            multiplier = edge_hazard_multiplier(edge, node_xy, zones, relaxed=relaxed)
            total_length += edge.length_m
            total_cost += edge.length_m * edge.traverse_factor * multiplier
            hazard_max = max(hazard_max, multiplier)

    # 소요 시간에는 위험 가중을 넣지 않는다. 가스가 짙다고 사람이 느려지는 게
    # 아니다 — 가중치는 "어느 길로 갈까"를 정할 때만 쓰는 값이다 (§4.1).
    walk_cost = sum(
        edge.length_m * edge.traverse_factor for _n, edge in path if edge is not None
    )
    estimated_seconds = int(round(walk_cost / walk_speed_mps)) if walk_speed_mps > 0 else None

    route_warnings = list(warnings)
    for level, threshold in (("passes_hazard_level1", 1.5), ("passes_hazard_level2", 5.0)):
        if math.isclose(hazard_max, threshold):
            route_warnings.append(level)
    if snap_distance > 2.0 and "long_snap_distance" not in route_warnings:
        route_warnings.append("long_snap_distance")

    return RouteResult(
        route_status="degraded" if hazard_max > 1.0 else "safe",
        assumed_level_id=assumed_level_id,
        target_exit_id=via_exit.get(entry),
        entry_nav_node_id=entry,
        snap_distance_m=round(snap_distance, 2),
        total_length_m=round(total_length, 2),
        total_cost=round(total_cost, 2),
        estimated_seconds=estimated_seconds,
        hazard_multiplier_max=hazard_max,
        waypoints=waypoints,
        blocked_exits=list(disabled_exits),
        warnings=route_warnings,
    )
