"""감사 로그 조회 API (AUTH-5, 이슈 #135; FR-605).

- GET /api/audit-log — admin 전용. action(전방 일치)/actor_name/기간 필터.

기록 자체는 각 라우터(auth/thresholds/workers)가 담당한다.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.dependencies.auth import require_role
from app.repositories import audit_repository

router = APIRouter(prefix="/api/audit-log", tags=["audit-log"])


@router.get("")
async def get_audit_log(
    action: Optional[str] = Query(None, max_length=64),
    actor_name: Optional[str] = Query(None, max_length=64),
    start: Optional[datetime] = Query(None),
    end: Optional[datetime] = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    _admin=Depends(require_role("admin")),
):
    return await audit_repository.query(
        action=action,
        actor_name=actor_name,
        start=start,
        end=end,
        limit=limit,
    )
