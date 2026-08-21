"""비상 탈출 경로 API (FR-801~808, 12_EVACUATION_ROUTE_SPEC §4.2).

- GET   /api/evacuation/route/{node_id}   현재 경로 (초기 로드)
- GET   /api/evacuation/topology          nav graph 전체 (평면도 렌더용)
- PUT   /api/evacuation/topology          토폴로지 교체 (admin)
- PATCH /api/evacuation/exits/{exit_id}   출구 is_usable 토글 (supervisor+)
- GET   /api/evacuation/history           과거 경로 이력 (사고 조사)

조회는 전역 게이트(enforce_authentication)로 인증만 확인한다 — viewer 이상이면
누구나 본다. 대피 경로를 못 보게 막아서 얻을 안전은 없다.

상태를 바꾸는 두 엔드포인트는 권한과 CSRF 를 모두 요구하고 감사 로그를 남긴다.
출구를 닫는 조작은 사람을 다른 길로 보내는 결정이므로 누가 했는지 남아야 한다.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.dependencies.auth import require_role, verify_csrf
from app.models.evacuation import NavTopology
from app.models.user import UserOut
from app.repositories import audit_repository, nav_repository
from app.services import evacuation_service, evacuation_topology

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/evacuation", tags=["evacuation"])


class ExitUsableUpdate(BaseModel):
    is_usable: bool
    # 왜 닫는지 남긴다. 점검인지 사고인지 구분되지 않으면 이력이 쓸모없다.
    reason: str = ""


def _require_enabled() -> None:
    """경로 기능이 꺼져 있으면 409. 404 가 아니다 — 경로가 없는 게 아니라
    기능이 설정되지 않은 것이고, 사유는 /health 가 말해준다."""
    if not evacuation_service.is_enabled():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=evacuation_service.status().reason or "탈출 경로 기능이 비활성 상태다",
        )


@router.get("/topology")
async def get_topology():
    """평면도가 그릴 nav graph.

    메모리의 것을 돌려준다. DB 를 다시 읽지 않는 이유는 기동 시 YAML → DB →
    메모리가 한 번에 맞춰지고, 출구 토글만 양쪽을 함께 갱신하기 때문이다.
    """
    _require_enabled()
    topology = evacuation_service.get_topology()
    assert topology is not None  # _require_enabled 가 보장한다
    return topology.model_dump()


@router.put("/topology", dependencies=[Depends(verify_csrf)])
async def replace_topology(
    topology: NavTopology,
    user: UserOut = Depends(require_role("admin")),
):
    """토폴로지를 통째로 교체한다. **검증을 통과할 때만** 적용한다.

    검증을 건너뛰면 관리자가 실수로 끊긴 그래프를 올린 순간 경로 기능이
    죽는다. 그때는 이미 늦다 — 대피 상황에서 발견하게 된다.
    """
    errors = evacuation_topology.validate_topology(topology)
    if errors:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": "통행 구조 검증 실패", "errors": errors},
        )

    await nav_repository.replace_topology(topology)
    evacuation_service.set_topology(topology)
    await evacuation_service.recompute_all("topology_changed")

    await audit_repository.record(
        actor_id=getattr(user, "id", None),
        actor_name=getattr(user, "username", "unknown"),
        action="evacuation.topology.replace",
        target="space_topology",
        detail={
            "nodes": len(topology.nav_nodes),
            "edges": len(topology.nav_edges),
            "exits": len(topology.exits),
        },
    )
    return {"applied": True, "nodes": len(topology.nav_nodes)}


@router.patch("/exits/{exit_id}", dependencies=[Depends(verify_csrf)])
async def set_exit_usable(
    exit_id: str,
    body: ExitUsableUpdate,
    user: UserOut = Depends(require_role("admin", "supervisor")),
):
    """출구를 열거나 닫는다. 점검·폐쇄를 반영하는 운영 조작이다."""
    _require_enabled()

    updated = await nav_repository.set_exit_usable(exit_id, body.is_usable)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="출구가 없다")

    changed = evacuation_service.set_exit_usable_in_memory(exit_id, body.is_usable)
    if changed:
        # 출구가 닫히면 그 출구로 가던 사람은 지금 당장 다른 길로 가야 한다.
        await evacuation_service.recompute_all("topology_changed")

    await audit_repository.record(
        actor_id=getattr(user, "id", None),
        actor_name=getattr(user, "username", "unknown"),
        action="evacuation.exit.toggle",
        target=exit_id,
        detail={"is_usable": body.is_usable, "reason": body.reason},
    )
    return {"exit_id": exit_id, "is_usable": body.is_usable}


@router.get("/route/{node_id}")
async def get_route(node_id: str):
    """현재 경로. 프론트가 초기 로드에서 한 번 받고, 이후는 WebSocket 이 갱신한다."""
    active = evacuation_service.get_active_route(node_id)
    if active is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="이 노드에 대해 계산된 경로가 없다",
        )
    return evacuation_service.to_message(node_id, active)


@router.get("/history")
async def get_history(
    node_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
):
    """경로 교체 이력. 사고 조사에서 "그때 시스템이 무엇을 지시했는가"를 되짚는다."""
    return await nav_repository.list_route_history(node_id, limit)
