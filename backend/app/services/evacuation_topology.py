"""통행 구조 로더 + 검증기 (FR-801/FR-806, 12_EVACUATION_ROUTE_SPEC §2, §6.3).

`config/space_topology.yaml` 을 읽어 `NavTopology` 로 만들고, 그래프가 경로 계산에
쓸 만한지 검사한다.

── 왜 검증이 필요한가 ──────────────────────────────────────────────────
nav graph 는 사람이 수기로 작성한다 (§7 한계 #1). 노드 하나를 오타 내면 Dijkstra 는
조용히 그 노드를 건너뛴 경로를 내놓는다. 잘못된 대피 경로는 경로가 없는 것보다
나쁘다 — 관제사가 그것을 믿고 지시하기 때문이다. 그래서 기동 시 한 번 전수 검사하고,
통과하지 못하면 경로 기능 자체를 켜지 않는다.

── 실패해도 서버는 뜬다 ────────────────────────────────────────────────
검증 실패는 예외를 던지지 않는다. 토폴로지가 틀렸다고 센서 수집과 가스 경보까지
멈추면 안 된다 — 그쪽이 훨씬 더 중요한 안전 기능이다 (§6.3).

다만 **조용히 꺼지지는 않는다.** 이슈 #154(경보 엔진 무음 사망)의 교훈이다.
로그·`/health`·대시보드 배너 세 곳에 사유가 드러난다.
"""
from __future__ import annotations

import logging
from collections import deque
from pathlib import Path

import yaml
from pydantic import ValidationError

from app.config import settings
from app.models.evacuation import NavTopology

logger = logging.getLogger(__name__)

DEFAULT_TOPOLOGY_RELPATH = Path("config") / "space_topology.yaml"


class TopologyError(Exception):
    """파일을 읽어 NavTopology 로 만드는 데 실패했다. 사람이 읽을 수 있는 메시지를 담는다."""


def topology_path() -> Path:
    """토폴로지 파일 경로.

    설정이 비어 있으면 저장소 루트의 config/space_topology.yaml 을 쓴다.
    backend/app/services/ 에서 세 단계 위가 저장소 루트다.
    """
    if settings.evacuation_topology_path:
        return Path(settings.evacuation_topology_path)
    return Path(__file__).resolve().parents[3] / DEFAULT_TOPOLOGY_RELPATH


def load_topology_file(path: Path | None = None) -> NavTopology:
    """YAML 을 읽어 NavTopology 로 만든다. 실패하면 TopologyError."""
    target = path or topology_path()

    if not target.exists():
        raise TopologyError(f"토폴로지 파일이 없다: {target}")

    try:
        raw = yaml.safe_load(target.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise TopologyError(f"YAML 파싱 실패 ({target.name}): {exc}") from exc

    if not isinstance(raw, dict):
        raise TopologyError(f"토폴로지 최상위가 매핑이 아니다 ({target.name})")

    try:
        return NavTopology.model_validate(raw)
    except ValidationError as exc:
        # pydantic 의 기본 메시지는 길고 영어라 /health 에 그대로 싣기 어렵다.
        # 어느 필드가 틀렸는지만 뽑아 짧게 만든다.
        details = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:5]
        )
        raise TopologyError(f"토폴로지 형식 오류 ({target.name}): {details}") from exc


def validate_topology(topology: NavTopology) -> list[str]:
    """그래프 무결성 검사. 문제를 사람이 읽을 수 있는 문장 리스트로 돌려준다.

    빈 리스트면 통과다. 예외를 던지지 않는 이유는 호출부가 "왜 껐는지"를 화면에
    표시해야 하기 때문이다.
    """
    errors: list[str] = []

    if topology.coordinate_system != "ship-visual":
        # FILL 프리셋 좌표가 들어오면 축마다 배율이 달라 거리가 왜곡되고,
        # "가장 가까운 출구"가 실제와 다른 출구로 나온다 (ADR-010).
        errors.append(
            f"좌표계가 ship-visual 이 아니다: {topology.coordinate_system!r}. "
            "경로 계산은 균일 배율에서만 성립한다."
        )

    errors.extend(_duplicate_ids(topology))

    node_ids = topology.node_ids
    level_ids = {lv.level_id for lv in topology.levels}

    for node in topology.nav_nodes:
        if level_ids and node.level_id not in level_ids:
            errors.append(f"노드 {node.nav_node_id}: 정의되지 않은 층 {node.level_id!r}")

    for edge in topology.nav_edges:
        for side, ref in (("from", edge.from_node_id), ("to", edge.to_node_id)):
            if ref not in node_ids:
                errors.append(f"엣지 {edge.edge_id}: {side} 노드 {ref!r} 가 없다")
        if edge.from_node_id == edge.to_node_id:
            errors.append(f"엣지 {edge.edge_id}: 자기 자신을 잇는다")

    for exit_ in topology.exits:
        if exit_.nav_node_id not in node_ids:
            errors.append(f"출구 {exit_.exit_id}: 노드 {exit_.nav_node_id!r} 가 없다")

    if not topology.exits:
        errors.append("출구가 하나도 없다. 대피 경로를 계산할 대상이 없다.")
    elif not any(e.is_usable for e in topology.exits):
        errors.append("사용 가능한 출구가 하나도 없다 (전부 is_usable=false).")

    # 참조가 깨진 상태에서 연결성을 따지면 의미 없는 오류가 쏟아진다. 여기서 끊는다.
    if errors:
        return errors

    errors.extend(_connectivity(topology))
    return errors


def _duplicate_ids(topology: NavTopology) -> list[str]:
    """중복 id. 나중 것이 앞의 것을 덮어써 조용히 사라지는 노드가 생긴다."""
    out: list[str] = []
    for label, ids in (
        ("노드", [n.nav_node_id for n in topology.nav_nodes]),
        ("엣지", [e.edge_id for e in topology.nav_edges]),
        ("출구", [x.exit_id for x in topology.exits]),
    ):
        seen: set[str] = set()
        dupes: set[str] = set()
        for i in ids:
            (dupes if i in seen else seen).add(i)
        for d in sorted(dupes):
            out.append(f"{label} id 가 중복이다: {d!r}")
    return out


def _adjacency(topology: NavTopology) -> dict[str, set[str]]:
    """사용 가능한 엣지만으로 만든 인접 리스트.

    bidirectional=false 는 한 방향만 놓는다 (사다리 하향 전용 같은 경우).
    is_usable=false 인 엣지는 통행 불가이므로 그래프에서 아예 뺀다.
    """
    adj: dict[str, set[str]] = {n.nav_node_id: set() for n in topology.nav_nodes}
    for edge in topology.nav_edges:
        if not edge.is_usable:
            continue
        adj[edge.from_node_id].add(edge.to_node_id)
        if edge.bidirectional:
            adj[edge.to_node_id].add(edge.from_node_id)
    return adj


def _connectivity(topology: NavTopology) -> list[str]:
    """고아 노드와 출구 도달 가능성.

    "출구까지 갈 수 있는가"는 순방향이 아니라 **역방향** 탐색으로 본다. 출구를
    출발점으로 두고 엣지를 거꾸로 따라가면, 한 번의 BFS 로 모든 노드의 도달
    가능 여부가 나온다. 노드마다 정방향 탐색을 돌릴 이유가 없다.
    """
    errors: list[str] = []
    adj = _adjacency(topology)

    orphans = sorted(nid for nid, nbrs in adj.items() if not nbrs)
    for nid in orphans:
        errors.append(f"노드 {nid}: 연결된 통행 구간이 없다 (고아 노드)")

    # 역방향 인접: v -> u 가 있으면 reverse[v] 에 u 를 넣는다.
    reverse: dict[str, set[str]] = {nid: set() for nid in adj}
    for u, neighbours in adj.items():
        for v in neighbours:
            reverse[v].add(u)

    usable_exit_nodes = {x.nav_node_id for x in topology.exits if x.is_usable}
    reached: set[str] = set()
    queue = deque(usable_exit_nodes)
    reached |= usable_exit_nodes
    while queue:
        current = queue.popleft()
        for prev in reverse.get(current, ()):
            if prev not in reached:
                reached.add(prev)
                queue.append(prev)

    stranded = sorted(set(adj) - reached)
    if stranded:
        errors.append(
            "출구에 도달할 수 없는 노드가 있다: " + ", ".join(stranded[:5])
            + (f" 외 {len(stranded) - 5}개" if len(stranded) > 5 else "")
        )

    # 아무도 들어올 수 없는 출구. 존재는 하지만 대피에 쓸 수 없다.
    for exit_ in topology.exits:
        if not exit_.is_usable:
            continue
        if not reverse.get(exit_.nav_node_id):
            errors.append(f"출구 {exit_.exit_id}: 이 출구로 들어오는 통행 구간이 없다")

    return errors


def load_and_validate(path: Path | None = None) -> tuple[NavTopology | None, list[str]]:
    """읽고 검사한다. 실패해도 예외를 던지지 않고 (None, [사유]) 를 돌려준다.

    호출부(evacuation_service.init)가 서버를 세우지 않고 경로 기능만 끄기 위한
    형태다. 예외로 만들면 lifespan 에서 try/except 를 다시 쓰게 되고, 그 자리가
    바로 이슈 #154 가 났던 자리다.
    """
    try:
        topology = load_topology_file(path)
    except TopologyError as exc:
        return None, [str(exc)]

    errors = validate_topology(topology)
    if errors:
        return None, errors
    return topology, []
