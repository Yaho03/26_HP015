"""인증 API — 로그인/로그아웃/세션 조회/비밀번호 변경 (AUTH-2, 이슈 #132).

- POST /api/auth/login     로그인 → 세션 쿠키(HttpOnly) + CSRF 토큰 쿠키
- POST /api/auth/logout    세션 폐기
- GET  /api/auth/me        현재 사용자
- POST /api/auth/password  비밀번호 변경 (모든 세션 폐기 → 재로그인)

CSRF 는 이 라우터의 login 을 제외하면 모든 상태 변경에 붙는다 (#133 부터
다른 라우터에도 적용). login 자체는 CSRF 대상이 아니다 — 아직 세션이 없어
double-submit 토큰이 존재하지 않는다. (Cross-Site 로그인 시도는 SameSite=Lax
쿠키 정책과 CORS 오리진 허용 목록으로 방어한다.)
"""
from __future__ import annotations

import logging
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.config import settings
from app.dependencies.auth import (
    CSRF_COOKIE,
    CurrentUser,
    SESSION_COOKIE,
    verify_csrf,
)
from app.models.user import LoginRequest, PasswordChangeRequest, SessionInfo
from app.repositories import audit_repository
from app.services import auth_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

# 로그인 IP rate limit (AUTH-10, 이슈 #140): 분당 10회. 초과하면 429.
# 계정 잠금이 '계정 단위' 방어라면 이것은 '출발지 단위' 방어다 — 존재하지 않는
# 여러 계정을 순회하는 스프레이 공격은 계정 잠금으로 못 막는다.
# 데모 규모(단일 인스턴스)라 메모리 카운터로 충분하다.
LOGIN_RATE_LIMIT_PER_MIN = 10
_login_attempts: dict[str, deque] = defaultdict(deque)


def _rate_limited(ip: str) -> bool:
    now = datetime.now(timezone.utc)
    window = _login_attempts[ip]
    while window and now - window[0] > timedelta(minutes=1):
        window.popleft()
    if len(window) >= LOGIN_RATE_LIMIT_PER_MIN:
        return True
    window.append(now)
    # 만료돼 텅 빈 다른 IP 의 키가 영구히 쌓이지 않게 가끔 치운다. ip 자신은
    # 방금 append 했으므로 살아남는다 — pop 후 append 하면 카운트가 유실된다.
    if len(_login_attempts) > 128:
        for stale in [k for k, v in _login_attempts.items() if not v]:
            _login_attempts.pop(stale, None)
    return False


def _client_ip(request: Request) -> str:
    """레이트리밋용 클라이언트 IP.

    배포 스택에서는 모든 HTTP 가 frontend 컨테이너의 nginx 를 거친다
    (backend 포트는 호스트에 노출하지 않는다, #151). request.client.host 는
    항상 nginx 컨테이너 IP 라 **전 사용자가 하나의 10회/분 버킷을 공유**하게
    된다 — 관리자 3명이 1분 안에 로그인하면 429. nginx 가 심는 X-Real-IP 를
    신뢰해 쓴다. 스푸핑은 compose 내부망 접근이 필요해 실질적으로 폐쇄망
    경계 안의 위험이다.
    """
    forwarded = request.headers.get("X-Real-IP")
    if forwarded:
        return forwarded
    return request.client.host if request.client else "unknown"


@router.post("/login", response_model=SessionInfo)
async def login(payload: LoginRequest, response: Response, request: Request):
    ip = _client_ip(request)
    if _rate_limited(ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts",
        )
    try:
        issued = await auth_service.login(payload.username, payload.password)
    except auth_service.InvalidCredentials:
        # 계정 존재 여부·비활성 여부를 응답으로 구분하지 않는다 (FR-609).
        await audit_repository.record(
            actor_id=None,
            actor_name=payload.username,
            action="login.failure",
            detail={"ip": request.client.host if request.client else None},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    await audit_repository.record(
        actor_id=issued.user.id,
        actor_name=issued.user.username,
        action="login.success",
        detail={"role": issued.user.role},
    )

    response.set_cookie(SESSION_COOKIE, issued.token, **auth_service.session_cookie_attributes())
    # CSRF 토큰은 JS 가 읽을 수 있어야 한다 (헤더로 되돌려 보내야 하므로).
    response.set_cookie(
        CSRF_COOKIE,
        issued.csrf_token,
        httponly=False,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )
    logger.info("login success (user=%s role=%s)", issued.user.username, issued.user.role)
    return SessionInfo(user=issued.user.to_out(), csrf_token=issued.csrf_token)


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response, user: CurrentUser):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        await auth_service.logout(token)
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    await audit_repository.record(
        actor_id=user.id, actor_name=user.username, action="logout"
    )
    logger.info("logout (user=%s)", user.username)


@router.get("/me")
async def me(user: CurrentUser):
    return user.to_out()


@router.post("/password", status_code=204)
async def change_password(
    payload: PasswordChangeRequest,
    request: Request,
    response: Response,
    user: CurrentUser,
    _: None = Depends(verify_csrf),
):
    try:
        await auth_service.change_password(user, payload.current_password, payload.new_password)
    except auth_service.InvalidCredentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password is incorrect",
        )
    # 변경 성공 → 모든 세션 폐기. 현재 쿠키도 지운다 (재로그인 유도).
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    await audit_repository.record(
        actor_id=user.id, actor_name=user.username, action="user.password_change"
    )
    logger.info("password changed (user=%s)", user.username)
