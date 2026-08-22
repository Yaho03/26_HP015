"""FastAPI 인증 의존성 (AUTH-2, 이슈 #132).

- get_current_user: 세션 쿠키를 검증해 CurrentUser 를 주입한다.
- require_role: RBAC 게이트 팩토리 (AUTH-3/#133 에서 각 라우터에 붙는다).
- verify_csrf: 상태 변경 요청의 double-submit 토큰 검증 (FR-608).
"""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from starlette.requests import HTTPConnection

from app.models.user import UserOut
from app.repositories.user_repository import UserRow
from app.services import auth_service

SESSION_COOKIE = "hp015_session"
CSRF_COOKIE = "hp015_csrf"
CSRF_HEADER = "X-CSRF-Token"


async def _bearer_user(request: Request) -> UserRow:
    # 앱 게이트(enforce_authentication)가 이미 검증했다면 재검증하지 않는다 —
    # 요청당 DB 왕복을 두 번 하지 않는다.
    cached = getattr(request.state, "user", None)
    if cached is not None:
        return cached
    return await _load_user(request)


CurrentUser = Annotated[UserRow, Depends(_bearer_user)]


# 화이트리스트 외 모든 HTTP 경로는 인증이 필요하다 (AUTH-3, 이슈 #133).
# WebSocket(/ws)은 HTTP 의존성을 타지 않는다 — AUTH-4(#134)가 핸드셰이크에서
# 따로 검증한다.
PUBLIC_PATHS = frozenset({"/health", "/api/auth/login"})

# must_change_password 상태에서도 접근 가능한 경로 (AUTH-9, FR-610).
# 비밀번호 변경 전 다른 API 접근을 차단한다 — 부트스트랩 계정의 초기
# 비밀번호가 .env 유출 등으로 알려져 있어도, 교체 전에는 아무것도 못 하게
# 한다. me 는 프론트가 상태를 알 수 있게 허용하고, WS 도 경보 가시성
# (FR-607)을 위해 읽기 스트림을 유지한다... 단 WS 인증은 validate_session 을
# 그대로 통과하므로 여기 목록에 /ws 는 없다 (HTTP 게이트만 본다).
PASSWORD_CHANGE_ALLOWED_PATHS = frozenset(
    {"/api/auth/me", "/api/auth/password", "/api/auth/logout"}
)


async def enforce_authentication(request: HTTPConnection) -> None:
    """앱 전체 인증 게이트 — app.dependencies 에 등록된다.

    라우트별 Depends 를 빠뜨린 경로가 새어 나가는 것을 구조적으로 막는다.
    #125 정리 때 no-op Depends 를 지운 것과 정반대 방향: 이번엔 실제 검증이
    들어있고, 빠뜨리면 기본 거부다.
    """
    if request.url.path in PUBLIC_PATHS:
        return
    user = await _load_user(request)
    if (
        user.must_change_password
        and request.url.path not in PASSWORD_CHANGE_ALLOWED_PATHS
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Password change required",
        )
    request.state.user = user


async def _load_user(request: HTTPConnection) -> UserRow:
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


async def authenticate_ws(ws) -> UserRow | None:
    """WebSocket 핸드셰이크 인증 (AUTH-4, 이슈 #134).

    브라우저 WebSocket API 는 커스텀 헤더를 못 붙인다 — 그래서 세션 쿠키로
    인증한다 (ADR-007 이 쿠키 세션을 고른 결정적 이유). 핸드셰이크 쿠키는
    자동으로 따라온다.
    """
    token = ws.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    try:
        session = await auth_service.validate_session(token)
    except auth_service.SessionExpired:
        return None
    return session.user
