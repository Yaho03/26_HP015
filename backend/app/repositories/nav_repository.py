"""nav graph DB 액세스 계층 (FR-801, 12_EVACUATION_ROUTE_SPEC §4.3).

YAML 이 소스이고 DB 는 사본이다. 그러면 왜 DB 에 넣나 —

1. `GET /api/evacuation/topology` 가 평면도를 그리려고 그래프를 통째로 요청한다.
   요청마다 YAML 을 다시 파싱하는 것보다 낫다.
2. 출구 `is_usable` 토글(§4.2 PATCH)은 관리자가 런타임에 바꾸는 값이다. 파일에
   되쓰면 실측 도면 교체와 운영 중 토글이 같은 파일에서 섞인다.

즉 **정적 구조는 YAML 이, 운영 중 상태는 DB 가** 소유한다.
"""
from __future__ import annotations

from app.db import get_pool
from app.models.evacuation import EvacuationExit, NavEdge, NavNode, NavTopology


async def replace_topology(topology: NavTopology) -> None:
    """DB 의 통행 구조를 통째로 갈아끼운다.

    부분 갱신(upsert)을 하지 않는 이유: YAML 에서 삭제된 노드가 DB 에 남으면
    경로가 존재하지 않는 통로를 지나가게 된다. 그건 조용히 잘못된 대피 지시가
    되므로, 없어진 것은 확실히 없어져야 한다.

    한 트랜잭션으로 묶는다. 중간에 실패해서 노드는 지워졌는데 엣지는 남은 상태로
    서버가 뜨면 참조 무결성이 깨진 그래프로 경로를 계산하게 된다.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            # nav_edges / evacuation_exits 는 nav_nodes 를 ON DELETE CASCADE 로
            # 참조하므로 노드만 지워도 따라 지워진다. 그래도 명시적으로 지운다 —
            # CASCADE 에 기대면 나중에 제약을 손볼 때 조용히 깨진다.
            await conn.execute("DELETE FROM evacuation_exits")
            await conn.execute("DELETE FROM nav_edges")
            await conn.execute("DELETE FROM nav_nodes")

            if topology.nav_nodes:
                await conn.executemany(
                    """
                    INSERT INTO nav_nodes (nav_node_id, kind, x_m, y_m, z_m, level_id, label)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    """,
                    [
                        (n.nav_node_id, n.kind.value, n.x_m, n.y_m, n.z_m, n.level_id, n.label)
                        for n in topology.nav_nodes
                    ],
                )

            if topology.nav_edges:
                await conn.executemany(
                    """
                    INSERT INTO nav_edges (edge_id, from_node_id, to_node_id, kind,
                                           length_m, traverse_factor, bidirectional,
                                           width_m, is_usable)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    """,
                    [
                        (
                            e.edge_id, e.from_node_id, e.to_node_id, e.kind.value,
                            e.length_m, e.traverse_factor, e.bidirectional,
                            e.width_m, e.is_usable,
                        )
                        for e in topology.nav_edges
                    ],
                )

            if topology.exits:
                await conn.executemany(
                    """
                    INSERT INTO evacuation_exits (exit_id, nav_node_id, kind,
                                                  is_usable, priority, label)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    """,
                    [
                        (x.exit_id, x.nav_node_id, x.kind.value, x.is_usable, x.priority, x.label)
                        for x in topology.exits
                    ],
                )


async def load_topology() -> NavTopology:
    """DB 에 저장된 통행 구조를 읽는다.

    `levels` 는 DB 에 두지 않는다 — 층 정의는 표시용 메타데이터일 뿐이고 경로
    계산에 쓰이지 않는다. 필요하면 YAML 쪽 값을 쓴다.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        node_rows = await conn.fetch(
            """
            SELECT nav_node_id, kind, x_m, y_m, z_m, level_id, label
            FROM nav_nodes ORDER BY nav_node_id
            """
        )
        edge_rows = await conn.fetch(
            """
            SELECT edge_id, from_node_id, to_node_id, kind, length_m,
                   traverse_factor, bidirectional, width_m, is_usable
            FROM nav_edges ORDER BY edge_id
            """
        )
        exit_rows = await conn.fetch(
            """
            SELECT exit_id, nav_node_id, kind, is_usable, priority, label
            FROM evacuation_exits ORDER BY priority, exit_id
            """
        )

    return NavTopology(
        nav_nodes=[NavNode(**dict(r)) for r in node_rows],
        nav_edges=[NavEdge(**dict(r)) for r in edge_rows],
        exits=[EvacuationExit(**dict(r)) for r in exit_rows],
    )


async def set_exit_usable(exit_id: str, is_usable: bool) -> bool:
    """출구 하나를 열고 닫는다. 대상이 없으면 False.

    점검·폐쇄를 반영하는 운영 조작이라 YAML 이 아니라 DB 만 바꾼다.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        status = await conn.execute(
            "UPDATE evacuation_exits SET is_usable = $2 WHERE exit_id = $1",
            exit_id,
            is_usable,
        )
    return status.endswith(" 1")
