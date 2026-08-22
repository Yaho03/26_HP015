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
from app.models.alert import AlertLevel, AlertTransition
from app.models.evacuation import HazardZone, NavTopology, RouteResult, TopologyStatus
from app.repositories import nav_repository
from app.services import (
    alert_service,
    evacuation_hazards,
    evacuation_router,
    evacuation_topology,
    location_service,
)
from app.services.evacuation_coordinates import to_ship_visual
from app.services.evacuation_router import Position2D
from app.services.ws_manager import manager

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

    # 토폴로지가 살아 있을 때만 위치를 구독한다. 꺼져 있는데 구독하면 측위마다
    # unavailable 경로를 만들어 브로드캐스트하게 된다.
    location_service.add_observer(_on_filtered_position)


async def _on_filtered_position(pos) -> None:
    """location_service 가 필터링을 마친 위치를 넘겨준다."""
    await on_position_update(
        pos.node_id,
        pos.x,
        pos.y,
        pos.timestamp,
        settings.location_source_coordinate_system,
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


def set_topology(topology: NavTopology) -> None:
    """메모리의 통행 구조를 갈아끼운다 (PUT /api/evacuation/topology).

    DB 반영은 호출부가 먼저 한다. 순서가 뒤바뀌면 메모리는 새 그래프인데 DB 는
    옛 그래프인 상태로 재기동 시 되돌아간다.
    """
    global _status, _topology
    _topology = topology
    _status = TopologyStatus(
        enabled=True,
        node_count=len(topology.nav_nodes),
        edge_count=len(topology.nav_edges),
        exit_count=len(topology.exits),
    )


# 테스트가 쓰던 이름을 유지한다.
set_topology_for_test = set_topology


def set_exit_usable_in_memory(exit_id: str, is_usable: bool) -> bool:
    """출구 하나의 가용 여부를 메모리에도 반영한다. 실제로 바뀌었으면 True.

    DB 만 고치면 다음 재기동 전까지 경로 계산이 옛 상태를 본다 — 관리자가 닫은
    출구로 사람을 계속 보내게 된다.
    """
    topology = _topology
    if topology is None:
        return False
    for exit_ in topology.exits:
        if exit_.exit_id == exit_id:
            if exit_.is_usable == is_usable:
                return False
            exit_.is_usable = is_usable
            return True
    return False


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


def active_route_nodes() -> list[str]:
    """활성 경로가 있는 노드 목록 (WS snapshot hydration, 이슈 #209).

    경로는 route_id 가 바뀔 때만 발행되므로, 재연결 시 snapshot 없이는 안정
    상태의 현재 경로를 화면이 영영 못 받는다.
    """
    return sorted(_routes)


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

    # 목표 출구가 닫혔다. 지나는 통로의 비용은 그대로여도 그 길로 보내면 안 된다 —
    # 도착해서야 잠긴 해치를 마주하게 된다. 간선 비용만 보는 아래 비교로는 이 경우가
    # 절대 잡히지 않는다 (출구를 닫아도 간선은 그대로 열려 있다).
    target_id = current.result.target_exit_id
    if target_id and _topology is not None:
        target = next((x for x in _topology.exits if x.exit_id == target_id), None)
        if target is None or not target.is_usable:
            return "topology_changed"

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


def to_message(node_id: str, active: ActiveRoute) -> dict:
    """WebSocket / REST 페이로드. schemas/evacuation-route.schema.json 을 따른다.

    worker_id / worker_name 은 배정이 없으면 비운다 (§6.1). 경로는 노드에 대해
    계산되고 사람은 그 노드를 차고 있을 뿐이라, 배정이 없다고 경로를 안 그릴
    이유가 없다.
    """
    result = active.result
    payload: dict = {
        "type": "evacuation_route",
        "route_id": active.route_id,
        "node_id": node_id,
        "computed_at": active.computed_at.isoformat().replace("+00:00", "Z"),
        "route_status": result.route_status,
        "coordinate_system": "ship-visual",
        "assumed_level_id": result.assumed_level_id,
        "target_exit_id": result.target_exit_id,
        "entry_nav_node_id": result.entry_nav_node_id,
        "snap_distance_m": result.snap_distance_m,
        "total_length_m": result.total_length_m,
        "total_cost": result.total_cost,
        "estimated_seconds": result.estimated_seconds,
        "hazard_multiplier_max": result.hazard_multiplier_max,
        "switch_reason": active.switch_reason,
        "waypoints": [w.model_dump() for w in result.waypoints],
        "blocked_exits": [b.model_dump() for b in result.blocked_exits],
        "warnings": list(result.warnings),
    }
    if result.unavailable_reason:
        payload["unavailable_reason"] = result.unavailable_reason
    return payload


async def _publish(node_id: str, active: ActiveRoute) -> None:
    """경로를 화면으로 내보내고 이력에 남긴다.

    브로드캐스트 실패가 경로 계산을 깨면 안 된다. 구독자가 없거나 소켓이 죽은
    것은 정상 상황이다.
    """
    try:
        await manager.broadcast(to_message(node_id, active))
    except Exception:
        logger.exception("evacuation route broadcast 실패 (node=%s)", node_id)

    result = active.result
    await nav_repository.record_route(
        route_id=active.route_id,
        node_id=node_id,
        worker_id=None,
        worker_name="",
        computed_at=active.computed_at,
        route_status=result.route_status,
        target_exit_id=result.target_exit_id,
        total_length_m=result.total_length_m,
        total_cost=result.total_cost,
        switch_reason=active.switch_reason,
        waypoints=[w.model_dump() for w in result.waypoints],
        blocked_exits=[b.model_dump() for b in result.blocked_exits],
    )


# 노드별 직전 route_status. 경보는 상태가 **바뀔 때만** 발령한다 —
# 재계산마다 발령하면 초당 몇 건씩 같은 경보가 쌓인다.
_last_status: dict[str, str] = {}


async def _sync_no_safe_route_alert(node_id: str, active: ActiveRoute) -> None:
    """안전 경로가 사라졌다는 사실을 경보로 올린다 (§3.5 MUST).

    화면을 보고 있지 않은 감독자에게도 닿아야 하므로 배너만으로는 부족하다.
    """
    status_now = active.result.route_status
    previous = _last_status.get(node_id)
    if previous == status_now:
        return
    _last_status[node_id] = status_now

    entering = status_now == "no_safe_route"
    leaving = previous == "no_safe_route" and not entering
    if not (entering or leaving):
        return

    try:
        await alert_service.handle_transition(
            AlertTransition(
                node_id=node_id,
                # alert_key 는 metric 에서 나온다 (alert_publisher). 가스 지표가
                # 아니라 상황 자체가 키다.
                metric="no_safe_route",
                from_level=AlertLevel.LEVEL3 if leaving else AlertLevel.NORMAL,
                to_level=AlertLevel.NORMAL if leaving else AlertLevel.LEVEL3,
                value=active.result.total_cost or 0.0,
                threshold=0.0,
                timestamp=active.computed_at,
            )
        )
    except Exception:
        logger.exception("no_safe_route 경보 발행 실패 (node=%s)", node_id)


async def on_position_update(
    node_id: str,
    x_m: float,
    y_m: float,
    sampled_at: datetime | None = None,
    source_coordinate_system: str | None = None,
) -> None:
    """측위가 갱신될 때 호출된다. 필요하면 다시 계산하고 바뀌었을 때만 발행한다.

    웨어러블이 아닌 노드는 무시한다. 고정 센서는 대피하지 않는다.
    """
    if not node_id.startswith("wearable-"):
        return
    if not is_enabled():
        return

    position = position_from_measurement(x_m, y_m, source_coordinate_system, sampled_at)
    if position is None:
        # 위치가 오래됐다. 경로를 지우는 대신 stale 상태로 알린다 (§6.1).
        active, changed = compute_and_decide(node_id, None)
        active.result.unavailable_reason = "stale_position"
        if changed:
            await _publish(node_id, active)
        return

    if not should_recompute_for_move(node_id, position):
        return

    active, changed = compute_and_decide(node_id, position)
    if changed:
        await _publish(node_id, active)
        await _sync_no_safe_route_alert(node_id, active)


async def recompute_all(reason: str = "hazard_changed") -> None:
    """위험 구역이나 토폴로지가 바뀌었을 때 전 노드를 다시 계산한다 (§3.4).

    위치는 그대로여도 주변이 달라졌으면 경로가 달라진다.
    """
    if not is_enabled():
        return
    for node_id in list(_routes):
        current = _routes[node_id]
        active, changed = compute_and_decide(node_id, current.position)
        if changed:
            await _publish(node_id, active)
            await _sync_no_safe_route_alert(node_id, active)


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
