"""작업자 명부 + 웨어러블 배정 API (이슈 #136, FR-306).

- GET    /api/workers                 명부 조회
- POST   /api/workers                 등록
- PATCH  /api/workers/{worker_id}     수정
- DELETE /api/workers/{worker_id}     삭제 (배정 이력도 함께 삭제)
- GET    /api/workers/assignments     현재 배정 전체 (노드 → 사람)
- POST   /api/workers/{worker_id}/assign   노드 배정
- POST   /api/workers/nodes/{node_id}/release  배정 종료
- GET    /api/workers/nodes/{node_id}/history  배정 이력

인증은 붙지 않는다. 작업자는 로그인 주체가 아니고(PRODUCT.md), 이 API 를 누가
호출할 수 있는지 통제하는 것은 인증 도입(#133) 때 화이트리스트로 다룬다.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from app.dependencies.auth import require_role, verify_csrf
from app.models.worker import (
    AssignedWorker,
    Assignment,
    AssignmentCreate,
    Worker,
    WorkerCreate,
    WorkerUpdate,
)
from app.repositories import worker_repository
from app.repositories.worker_repository import DuplicateEmployeeNo, NodeAlreadyAssigned

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/workers", tags=["workers"])


# 고정 경로를 /{worker_id} 보다 먼저 선언한다. 순서가 뒤바뀌면 "assignments" 가
# worker_id 로 해석돼 422 가 난다.
@router.get("/assignments", response_model=list[AssignedWorker])
async def list_assignments():
    return await worker_repository.list_active()


@router.get("", response_model=list[Worker])
async def list_workers():
    return await worker_repository.list_all()


@router.post("", response_model=Worker, status_code=201)
async def create_worker(
    payload: WorkerCreate,
    _supervisor=Depends(require_role("admin", "supervisor")),
    _csrf: None = Depends(verify_csrf),
):
    try:
        return await worker_repository.create(payload)
    except DuplicateEmployeeNo:
        raise HTTPException(status_code=409, detail=f"이미 등록된 사번입니다: {payload.employee_no}")


@router.patch("/{worker_id}", response_model=Worker)
async def update_worker(
    worker_id: int,
    payload: WorkerUpdate,
    _supervisor=Depends(require_role("admin", "supervisor")),
    _csrf: None = Depends(verify_csrf),
):
    try:
        worker = await worker_repository.update(worker_id, payload)
    except DuplicateEmployeeNo:
        raise HTTPException(status_code=409, detail=f"이미 등록된 사번입니다: {payload.employee_no}")
    if worker is None:
        raise HTTPException(status_code=404, detail="작업자를 찾을 수 없습니다")
    return worker


@router.delete("/{worker_id}", status_code=204)
async def delete_worker(
    worker_id: int,
    _supervisor=Depends(require_role("admin", "supervisor")),
    _csrf: None = Depends(verify_csrf),
):
    if not await worker_repository.delete(worker_id):
        raise HTTPException(status_code=404, detail="작업자를 찾을 수 없습니다")


@router.post("/{worker_id}/assign", response_model=Assignment, status_code=201)
async def assign_node(
    worker_id: int,
    payload: AssignmentCreate,
    _supervisor=Depends(require_role("admin", "supervisor")),
    _csrf: None = Depends(verify_csrf),
):
    if await worker_repository.get(worker_id) is None:
        raise HTTPException(status_code=404, detail="작업자를 찾을 수 없습니다")
    try:
        assignment = await worker_repository.assign(worker_id, payload.node_id)
    except NodeAlreadyAssigned:
        raise HTTPException(
            status_code=409,
            detail=f"{payload.node_id} 에 이미 배정된 작업자가 있습니다. 먼저 배정을 해제하세요.",
        )
    logger.info("worker %d assigned to %s", worker_id, payload.node_id)
    return assignment


@router.post("/nodes/{node_id}/release", response_model=Assignment)
async def release_node(
    node_id: str,
    _supervisor=Depends(require_role("admin", "supervisor")),
    _csrf: None = Depends(verify_csrf),
):
    assignment = await worker_repository.release(node_id)
    if assignment is None:
        raise HTTPException(status_code=404, detail=f"{node_id} 에 배정된 작업자가 없습니다")
    logger.info("assignment released for %s", node_id)
    return assignment


@router.get("/nodes/{node_id}/history", response_model=list[Assignment])
async def node_history(node_id: str):
    return await worker_repository.history(node_id)
