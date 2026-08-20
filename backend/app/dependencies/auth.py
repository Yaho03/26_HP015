"""FastAPI 인증 의존성 (AUTH-2, 이슈 #132).

- get_current_user: 세션 쿠키를 검증해 CurrentUser 를 주입한다.
- require_role: RBAC 게이트 팩토리 (AUTH-3/#133 에서 각 라우터에 붙는다).
- verify_csrf: 상태 변경 요청의 double-submit 토큰 검증 (FR-608).
"""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from app.models.user import UserOut
from app.repositories.user_repository import UserRow
from app.services import auth_service

SESSION_COOKIE = "hp015_session"
CSRF_COOKIE = "hp015_csrf"
CSRF_HEADER = "X-CSRF-Token"


async def _bearer_user(request: Request) -> UserRow:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    try:
        session = await auth_service.validate_session(token)
    except auth_service.SessionExpired:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired",
        )
    request.state.session_token = token
    request.state.csrf_token = session.csrf_token
    return session.user


CurrentUser = Annotated[UserRow, Depends(_bearer_user)]


def require_role(*allowed: str):
    """허용 역할 게이트. require_role('admin', 'supervisor') 식으로 쓴다."""

    async def _gate(user: CurrentUser) -> UserOut:
        if user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient role",
            )
        return user.to_out()

    return _gate


def verify_csrf(request: Request, user: CurrentUser) -> None:
    """double-submit 검증 — 쿠키 값과 헤더 값이 서버 발급 토큰과 일치해야 한다.

    CurrentUser 를 선행 의존성으로 둬 검증 순서를 보장한다 — 세션 검증이
    먼저여야 request.state.csrf_token 이 채워진다.
    """
    server_token = getattr(request.state, "csrf_token", None)
    header_token = request.headers.get(CSRF_HEADER)
    cookie_token = request.cookies.get(CSRF_COOKIE)
    if not server_token or header_token != server_token or cookie_token != server_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF token missing or invalid",
        )
