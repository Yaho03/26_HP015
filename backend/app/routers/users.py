"""사용자 관리 API (AUTH-10, 이슈 #140; FR-602/FR-605).

- GET    /api/users                    목록 (admin)
- POST   /api/users                    생성 (admin) — 임시 비밀번호 없이 지정
- PATCH  /api/users/{id}               역할/활성 변경 (admin)
- POST   /api/users/{id}/reset-password 비밀번호 초기화 (admin) — 임시 비밀번호
                                        1회 반환, must_change_password=true,
                                        기존 세션 전부 폐기

모든 변경은 감사 로그에 남는다. 자기 자신의 admin 역할을 떼는 실수를 막기
위해 마지막 활성 admin 은 비활성화/강등할 수 없다.
"""
from __future__ import annotations

import logging
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request

from app.dependencies.auth import require_role, verify_csrf
from app.models.user import (
    PasswordResetResult,
    UserAdminOut,
    UserCreateRequest,
    UserUpdateRequest,
)
from app.repositories import audit_repository, user_repository
from app.services import auth_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/users", tags=["users"])


def _to_admin_out(user) -> UserAdminOut:
    return UserAdminOut(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        role=user.role,
        is_active=user.is_active,
        must_change_password=user.must_change_password,
        failed_login_attempts=user.failed_login_attempts,
        locked_until=user.locked_until,
    )


async def _actor(request: Request):
    actor = getattr(request.state, "user", None)
    return (
        actor.id if actor else None,
        actor.username if actor else "unknown",
    )


async def _assert_not_last_admin(user_id: int, *, deactivating: bool = False, new_role: str | None = None) -> None:
    """마지막 활성 admin 보호 — 잠그면 시스템 전체를 관리할 수 없게 된다."""
    target = await user_repository.get_by_id(user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")
    if not target.is_active or target.role != "admin":
        return  # 대상이 이미 활성 admin 이 아니면 제약 없음
    if not deactivating and new_role is None:
        return
    admins = [u for u in await user_repository.list_all() if u.role == "admin" and u.is_active]
    if len(admins) <= 1:
        raise HTTPException(
            status_code=409,
            detail="마지막 활성 관리자는 비활성화하거나 강등할 수 없습니다",
        )


@router.get("", response_model=list[UserAdminOut])
async def list_users(_admin=Depends(require_role("admin"))):
    return [_to_admin_out(u) for u in await user_repository.list_all()]


@router.post("", response_model=UserAdminOut, status_code=201)
async def create_user(
    payload: UserCreateRequest,
    request: Request,
    _admin=Depends(require_role("admin")),
    _csrf: None = Depends(verify_csrf),
):
    existing = await user_repository.get_by_username(payload.username)
    if existing is not None:
        raise HTTPException(status_code=409, detail=f"이미 존재하는 사용자입니다: {payload.username}")
    user = await user_repository.create_user(
        payload.username,
        auth_service.hash_password(payload.password),
        role=payload.role,
        must_change_password=True,
    )
    actor_id, actor_name = await _actor(request)
    await audit_repository.record(
        actor_id=actor_id,
        actor_name=actor_name,
        action="user.create",
        target=payload.username,
        detail={"role": payload.role},
    )
    return _to_admin_out(user)


@router.patch("/{user_id}", response_model=UserAdminOut)
async def update_user(
    user_id: int,
    payload: UserUpdateRequest,
    request: Request,
    _admin=Depends(require_role("admin")),
    _csrf: None = Depends(verify_csrf),
):
    await _assert_not_last_admin(
        user_id, deactivating=payload.is_active is False, new_role=payload.role
    )
    user = await user_repository.update_user(
        user_id, role=payload.role, is_active=payload.is_active
    )
    if user is None:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")
    if payload.is_active is False:
        await user_repository.revoke_all_for_user(user_id)
    actor_id, actor_name = await _actor(request)
    await audit_repository.record(
        actor_id=actor_id,
        actor_name=actor_name,
        action="user.update",
        target=user.username,
        detail={"role": payload.role, "is_active": payload.is_active},
    )
    return _to_admin_out(user)


@router.post("/{user_id}/reset-password", response_model=PasswordResetResult)
async def reset_password(
    user_id: int,
    request: Request,
    _admin=Depends(require_role("admin")),
    _csrf: None = Depends(verify_csrf),
):
    target = await user_repository.get_by_id(user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")

    temporary = secrets.token_urlsafe(12)
    await user_repository.update_password(
        user_id, auth_service.hash_password(temporary), must_change=True
    )
    await user_repository.reset_login_failures(user_id)
    await user_repository.revoke_all_for_user(user_id)

    actor_id, actor_name = await _actor(request)
    await audit_repository.record(
        actor_id=actor_id,
        actor_name=actor_name,
        action="user.password_reset",
        target=target.username,
    )
    refreshed = await user_repository.get_by_id(user_id)
    return PasswordResetResult(
        user=_to_admin_out(refreshed),
        temporary_password=temporary,
    )
