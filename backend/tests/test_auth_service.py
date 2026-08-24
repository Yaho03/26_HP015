"""auth_service 단위 테스트 (AUTH-2, 이슈 #132).

해싱·토큰 처리·쿠키 속성·계정 열거 방지 타이밍 마스킹을 검증한다.
DB 가 필요한 경로(세션 발급)는 통합 테스트(tests/integration)에서 다룬다.
"""
from __future__ import annotations

import pytest

from app.config import settings
from app.services import auth_service


def test_hash_and_verify_round_trip():
    h = auth_service.hash_password("correct horse battery staple")
    assert h != "correct horse battery staple"
    assert auth_service.verify_password("correct horse battery staple", h)
    assert not auth_service.verify_password("wrong password", h)


def test_hash_is_salted_per_call():
    """같은 비밀번호도 호출마다 다른 해시 — 무지개 표 공격 표면 축소."""
    assert auth_service.hash_password("pw") != auth_service.hash_password("pw")


def test_verify_with_corrupted_hash_returns_false():
    """손상된 해시는 예외가 아니라 '실패'로 — 인증 거부가 안전 기본값."""
    assert not auth_service.verify_password("pw", "$argon2id$not-a-valid-hash")


@pytest.mark.asyncio
async def test_login_unknown_user_still_performs_hash_verification(monkeypatch):
    """계정 열거 방지 (FR-609): 없는 계정도 더미 해시 검증 1회를 수행한다.

    검증을 건너뛰면 '없는 계정' 응답이 항상 빨라져 타이밍으로 존재 여부를
    알아낼 수 있다.
    """
    calls = []

    def fake_verify(password, password_hash):
        calls.append(password_hash)
        return False

    async def fake_get_by_username(username):
        return None

    monkeypatch.setattr(auth_service, "verify_password", fake_verify)
    monkeypatch.setattr(
        auth_service.user_repository, "get_by_username", fake_get_by_username
    )

    with pytest.raises(auth_service.InvalidCredentials):
        await auth_service.login("ghost-user", "whatever")

    assert len(calls) == 1, "미등록 계정도 해시 검증 1회를 돌아야 타이밍이 일치한다"


def test_token_hash_is_sha256_hex():
    token = "abc123"
    h = auth_service.hash_token(token)
    assert len(h) == 64
    assert h == auth_service.hash_token(token)
    assert h != auth_service.hash_token("abc124")


def test_session_cookie_attributes_are_hardened():
    attrs = auth_service.session_cookie_attributes()
    assert attrs["httponly"] is True, "JS 접근 차단 (ADR-007 XSS 방어)"
    assert attrs["samesite"] == "lax", "CSRF 1차 방어"
    assert attrs["secure"] == settings.cookie_secure
    # max_age 는 절대 만료와 일치해야 쿠키가 세션보다 먼저 죽지 않는다.
    assert attrs["max_age"] == int(settings.session_absolute_ttl_hours * 3600)


# ============================================================
# 로그인 레이트리밋 — 프록시 IP 분리 + 카운트 보존 (코드 리뷰 2026-08-22)
# ============================================================

def _request_with(real_ip: str | None, client_host: str = "10.0.0.1"):
    from fastapi import Request

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/auth/login",
        "headers": ([(b"x-real-ip", real_ip.encode())] if real_ip else []),
        "query_string": b"",
        "client": (client_host, 12345),
    }
    return Request(scope)


def test_client_ip_prefers_nginx_real_ip():
    """배포 스택의 모든 HTTP 는 nginx 를 거친다 — client.host 는 죄다 nginx IP 다.
    X-Real-IP 를 안 쓰면 전 사용자가 하나의 10회/분 버킷을 공유한다."""
    from app.routers.auth import _client_ip

    assert _client_ip(_request_with("192.168.1.42")) == "192.168.1.42"
    assert _client_ip(_request_with(None)) == "10.0.0.1"


def test_rate_limit_buckets_are_per_ip():
    from app.routers import auth as auth_router

    auth_router._login_attempts.clear()
    for _ in range(10):
        assert auth_router._rate_limited("192.168.1.42") is False
    assert auth_router._rate_limited("192.168.1.42") is True
    # 다른 IP 는 별도 버킷 — nginx 공유 버킷 회귀 방지
    assert auth_router._rate_limited("192.168.1.43") is False
    auth_router._login_attempts.clear()


def test_rate_limit_cleanup_does_not_lose_live_counter():
    """정리 스윕이 살아 있는 카운터를 지우지 않는지 — pop 후 append 하면 카운트가
    유실되어 레이트리밋이 무력화된다(리뷰 중 작성 버그 방지)."""
    from datetime import datetime, timedelta, timezone

    from app.routers import auth as auth_router

    auth_router._login_attempts.clear()
    # 죽은 키 129개 (만료 창) + 살아 있는 키 1개
    old = datetime.now(timezone.utc) - timedelta(minutes=5)
    for i in range(129):
        d = auth_router._login_attempts[f"dead-{i}"]
        d.append(old)
    assert auth_router._rate_limited("alive") is False  # 스윕 트리거 (>128)

    for _ in range(9):
        assert auth_router._rate_limited("alive") is False
    assert auth_router._rate_limited("alive") is True  # 10회째 차단 — 카운트 보존
    auth_router._login_attempts.clear()
