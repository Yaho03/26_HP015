"""비상 탈출 경로 서비스 (FR-801~808).

지금 담당하는 범위는 **통행 구조 적재와 기능 가용성 판정**이다 (B2). 경로 계산
자체(다중 소스 Dijkstra, 위험 가중, 히스테리시스)는 B3 에서 이 모듈에 들어온다.

── 왜 이 서비스만 예외를 삼키는가 ──────────────────────────────────────
`alert_service.init()` 은 실패를 그대로 전파시켜 기동을 실패시킨다. 경보 판정이
죽은 채로 서버가 "정상" 기동하면 아무도 모르기 때문이다 (이슈 #109/#154).

경로 기능은 반대로 간다. 토폴로지 YAML 에 오타가 났다고 센서 수집과 가스 경보까지
멈추면 훨씬 더 중요한 안전 기능을 잃는다. 그래서 **경로 기능만 끄고 서버는 뜬다**
(12_EVACUATION_ROUTE_SPEC §6.3).

두 정책의 차이를 만드는 것은 "조용한가"다. 이 모듈은 꺼질 때 세 곳에 흔적을 남긴다.

  1. `logger.error` — 로그
  2. `/health` 의 `evacuation.enabled=false` + `reason` — 기계가 읽는 곳
  3. 대시보드 배너 — 사람이 보는 곳

셋 다 사유를 담는다. #154 가 나빴던 것은 실패했다는 사실이 **어디에도** 남지
않았다는 점이지, 실패를 삼킨 것 자체가 아니다.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from ulid import ULID

from app.config import settings
from app.models.evacuation import HazardZone, NavTopology, RouteResult, TopologyStatus
from app.repositories import nav_repository
from app.services import evacuation_hazards, evacuation_router, evacuation_topology
from app.services.evacuation_coordinates import to_ship_visual
from app.services.evacuation_router import Position2D

logger = logging.getLogger(__name__)

# 기동 전 기본값. init() 이 아직 안 돌았으면 "꺼져 있고 사유는 미초기화"다.
# enabled=True 를 기본값으로 두면 init 이 실패한 뒤에도 켜진 것처럼 보인다.
_status = TopologyStatus(enabled=False, reason="아직 초기화되지 않았다")
_topology: NavTopology | None = None


async def init() -> None:
    """통행 구조를 읽고 검사한 뒤 DB 에 반영한다.

    실패해도 예외를 던지지 않는다 (위 모듈 주석 참고). 대신 상태와 사유를 남긴다.
    """
    global _status, _topology

    topology, errors = evacuation_topology.load_and_validate()

    if topology is None:
        reason = _summarize(errors)
        _topology = None
        _status = TopologyStatus(enabled=False, reason=reason)
        logger.error(
            "evacuation route disabled — 통행 구조 검증 실패: %s "
            "(센서 수집과 가스 경보는 정상 동작한다)",
            reason,
        )
        return

    try:
        await nav_repository.replace_topology(topology)
    except Exception as exc:  # noqa: BLE001 — 사유를 화면까지 전달해야 한다
        reason = f"통행 구조를 DB 에 반영하지 못했다: {exc}"
        _topology = None
        _status = TopologyStatus(enabled=False, reason=reason)
        logger.error("evacuation route disabled — %s", reason)
        return

    _topology = topology
    _status = TopologyStatus(
        enabled=True,
        reason=None,
        # 실측 도면이 들어오기 전까지는 항상 가정값이다 (OQ-V5). 화면이 이 사실을
        # 배지로 표시하는 근거가 된다.
        provisional=True,
        node_count=len(topology.nav_nodes),
        edge_count=len(topology.nav_edges),
        exit_count=len(topology.exits),
    )
    logger.info(
        "evacuation topology loaded — 노드 %d, 엣지 %d, 출구 %d (실측 미반영 가정값)",
        _status.node_count,
        _status.edge_count,
        _status.exit_count,
    )


def _summarize(errors: list[str]) -> str:
    """검증 오류를 한 문장으로 줄인다. /health 응답과 배너에 그대로 실린다.

    전부 싣지 않는 이유는 오류 하나가 연쇄로 수십 개를 만들 수 있어서다. 처음
    세 개와 총 개수면 무엇을 고쳐야 하는지 알기에 충분하고, 전체는 로그에 있다.
    """
    if not errors:
        return "알 수 없는 오류"
    head = "; ".join(errors[:3])
    if len(errors) > 3:
        head += f" (외 {len(errors) - 3}건)"
    return head


def status() -> TopologyStatus:
    """`/health` 와 대시보드가 읽는 현재 상태."""
    return _status


def is_enabled() -> bool:
    return _status.enabled


def get_topology() -> NavTopology | None:
    """적재된 통행 구조. 꺼져 있으면 None.

    B3 의 경로 계산이 이걸 입력으로 받는다. None 을 빈 그래프로 바꿔서 돌려주지
    않는다 — 빈 그래프는 "출구가 없다"로 읽혀서 no_safe_route 경보를 발령하게 되고,
    그건 기능이 꺼진 것과 전혀 다른 의미다.
    """
    return _topology


def reset_for_test() -> None:
    """테스트가 모듈 전역 상태를 초기화할 때 쓴다."""
    global _status, _topology
    _status = TopologyStatus(enabled=False, reason="아직 초기화되지 않았다")
    _topology = None
    _routes.clear()


def set_topology_for_test(topology: NavTopology) -> None:
    """DB 없이 경로 계산만 시험할 때 쓴다."""
    global _status, _topology
    _topology = topology
    _status = TopologyStatus(
        enabled=True,
        node_count=len(topology.nav_nodes),
        edge_count=len(topology.nav_edges),
        exit_count=len(topology.exits),
    )


# ─────────────────────────────────────────────────────────────────────────────
# 경로 채택과 교체 (§3.4)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class ActiveRoute:
    """지금 화면에 떠 있는 경로.

    route_id 는 "이 경로를 채택했다"는 결정에 붙는다. 재계산할 때마다 새로 발급하면
    사고 조사 이력(evacuation_routes)이 초당 몇 건씩 쌓이고, 화면은 바뀐 게 없는데
    바뀐 것처럼 보인다. 실제로 교체될 때만 새로 발급한다.
    """

    route_id: str
    result: RouteResult
    computed_at: datetime
    position: Position2D
    switch_reason: str


_routes: dict[str, ActiveRoute] = {}


def get_active_route(node_id: str) -> ActiveRoute | None:
    return _routes.get(node_id)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _recompute_cost(result: RouteResult, zones: list[HazardZone]) -> float | None:
    """현재 경로를 **지금의** 위험 구역으로 다시 값매김한다.

    비교 대상이 옛 비용이면 안 된다. 가스가 새로 찬 통로를 지나는 경로는 계산
    당시에는 쌌지만 지금은 비싸다. 옛 값과 비교하면 새 경로가 아무리 나아도
    85% 문턱을 넘지 못해 위험한 경로에 머무르게 된다.
    """
    topology = _topology
    if topology is None or not result.waypoints:
        return None

    edge_by_pair = {}
    for edge in topology.nav_edges:
        edge_by_pair[(edge.from_node_id, edge.to_node_id)] = edge
        if edge.bidirectional:
            edge_by_pair[(edge.to_node_id, edge.from_node_id)] = edge

    node_xy = {n.nav_node_id: (n.x_m, n.y_m) for n in topology.nav_nodes}
    graph_nodes = [w.nav_node_id for w in result.waypoints if w.nav_node_id]

    total = 0.0
    for current, following in zip(graph_nodes, graph_nodes[1:]):
        edge = edge_by_pair.get((current, following))
        if edge is None or not edge.is_usable:
            # 통로가 사라졌다. 무한대로 봐서 즉시 교체를 부른다.
            return float("inf")
        multiplier = evacuation_router.edge_hazard_multiplier(edge, node_xy, zones)
        if multiplier == evacuation_router.BLOCKED:
            return float("inf")
        total += edge.length_m * edge.traverse_factor * multiplier
    return total


def decide_replacement(
    current: ActiveRoute | None,
    candidate: RouteResult,
    zones: list[HazardZone],
    *,
    switch_ratio: float | None = None,
) -> str | None:
    """경로를 교체할 것인가. 교체하면 switch_reason, 유지하면 None.

    매번 최적 경로를 그대로 채택하면 비용이 비슷한 두 경로 사이에서 화면이 좌우로
    요동친다. 대피 중인 작업자에게 그건 최악이다 (§3.4).
    """
    ratio = settings.evacuation_route_switch_ratio if switch_ratio is None else switch_ratio

    if current is None:
        return "initial"

    # 상태가 달라졌으면 비용과 무관하게 보여줘야 한다. safe 였다가 no_safe_route 가
    # 된 것은 "조금 더 비싸진" 것이 아니라 전혀 다른 상황이다.
    if current.result.route_status != candidate.route_status:
        return "hazard_changed"

    # 작업자가 그래프의 다른 지점으로 옮겨갔다. 옛 경로를 유지하면 이미 지나온
    # 노드로 되돌아가는 선이 그려진다.
    if current.result.entry_nav_node_id != candidate.entry_nav_node_id:
        return "position_moved"

    current_cost = _recompute_cost(current.result, zones)
    if current_cost is None or current_cost == float("inf"):
        # 지금 쓰는 경로가 차단 구간을 지나게 됐다. 비율을 무시하고 즉시 바꾼다.
        return "route_blocked"

    candidate_cost = candidate.total_cost
    if candidate_cost is None:
        return None
    if candidate_cost < current_cost * ratio:
        return "hazard_changed"
    return None


def compute_and_decide(
    node_id: str,
    position: Position2D | None,
    *,
    zones: list[HazardZone] | None = None,
    hazard_data_available: bool | None = None,
    now: datetime | None = None,
) -> tuple[ActiveRoute, bool]:
    """경로를 계산하고 교체 여부를 정한 뒤 현재 경로를 돌려준다.

    두 번째 값은 "바뀌었는가"다. B4 의 브로드캐스트가 이 값을 보고 발행 여부를
    정한다 — 바뀌지 않은 경로를 매번 밀어내면 화면이 깜빡인다.
    """
    if zones is None or hazard_data_available is None:
        zones, hazard_data_available = evacuation_hazards.current_zones()

    topology = _topology
    if topology is None:
        # 기능이 꺼져 있다. "안전 경로 없음"이 아니라 "산출 불가"다 — 전자는
        # level3 경보를 발령하는데, 설정 문제로 경보를 울리면 안 된다.
        result = RouteResult(
            route_status="unavailable",
            unavailable_reason="topology_invalid",
        )
    else:
        result = evacuation_router.compute_route(
            topology,
            zones,
            position,
            max_snap_distance_m=settings.evacuation_max_snap_distance_m,
            walk_speed_mps=settings.evacuation_walk_speed_mps,
            hazard_data_available=hazard_data_available,
        )

    current = _routes.get(node_id)
    reason = decide_replacement(current, result, zones)
    timestamp = now or _now()

    if reason is None and current is not None:
        # 경로는 그대로 두되 첫 waypoint 만 실제 위치로 갱신한다. 그러지 않으면
        # 선이 작업자에게서 떨어져 시작한다 (§3.3 MUST).
        if position is not None and current.result.waypoints:
            current.result.waypoints[0].x_m = position.x_m
            current.result.waypoints[0].y_m = position.y_m
            current.position = position
        return current, False

    adopted = ActiveRoute(
        route_id=str(ULID()),
        result=result,
        computed_at=timestamp,
        position=position or Position2D(0.0, 0.0),
        switch_reason=reason or "initial",
    )
    _routes[node_id] = adopted
    return adopted, True


def position_from_measurement(
    x_m: float,
    y_m: float,
    source_coordinate_system: str | None = None,
    sampled_at: datetime | None = None,
    *,
    now: datetime | None = None,
) -> Position2D | None:
    """측위 결과를 경로 좌표계의 위치로 바꾼다. 너무 오래됐으면 None (§6.1).

    오래된 위치로 경로를 그리면 이미 그 자리에 없는 사람에게 길을 지시하게 된다.
    """
    if sampled_at is not None:
        reference = now or _now()
        if sampled_at.tzinfo is None:
            sampled_at = sampled_at.replace(tzinfo=timezone.utc)
        age_s = (reference - sampled_at).total_seconds()
        if age_s > settings.evacuation_position_max_age_s:
            return None

    system = source_coordinate_system or settings.location_source_coordinate_system
    ship_x, ship_y = to_ship_visual(x_m, y_m, system)
    return Position2D(ship_x, ship_y)


def should_recompute_for_move(node_id: str, position: Position2D) -> bool:
    """위치 변화가 재계산을 부를 만한가 (§3.4).

    측위는 초당 여러 번 들어온다. 매번 Dijkstra 를 돌릴 이유가 없고, 필터를 거쳐도
    남는 수 cm 의 흔들림 때문에 경로가 계속 재계산되면 히스테리시스가 무의미해진다.
    """
    current = _routes.get(node_id)
    if current is None:
        return True
    moved = (
        (current.position.x_m - position.x_m) ** 2
        + (current.position.y_m - position.y_m) ** 2
    ) ** 0.5
    return moved >= settings.evacuation_recompute_min_move_m
