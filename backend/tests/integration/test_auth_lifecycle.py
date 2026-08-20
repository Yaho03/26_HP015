"""인증 라이프사이클 통합 테스트 — 실제 DB + 실제 HTTP 스택 (AUTH-2, 이슈 #132).

이슈 #124의 교훈(경계면 mock 은 P0 를 못 잡는다)을 인증에 그대로 적용한다.
쿠키 속성·세션 만료·CSRF 는 실제 DB 와 실제 쿠키 파싱을 거쳐야만 검증된다.

앱 lifespan(MQTT 구독 등)은 여기서 돌리지 않는다 — 인증 경로와 무관하다.
DB 만 테스트 인스턴스에 연결한다.
"""
from __future__ import annotations

from datetime import timedelta

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app import db
from app.config import settings
from app.services import auth_service

pytestmark = pytest.mark.skipif(
    not __import__("os").getenv("TEST_TIMESCALE_URL", ""),
    reason="TEST_TIMESCALE_URL 이 없어 통합 테스트를 건너뜁니다",
)


TEST_PASSWORD = "integ-test-password-1"


@pytest.fixture
async def client(db_pool):
    """테스트 DB 에 붙은 앱 클라이언트. db_pool 이 마이그레이션까지 적용한다."""
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def client2(db_pool):
    """같은 앱에 붙은 두 번째 클라이언트 — '다른 기기' 세션을 흉내낸다."""
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def create_user(username: str, role: str = "viewer", *, must_change: bool = False) -> int:
    pool = db.get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO users (username, password_hash, display_name, role, must_change_password)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (username) DO UPDATE SET password_hash = EXCLUDED.password_hash
            RETURNING id
            """,
            username, auth_service.hash_password(TEST_PASSWORD), username, role, must_change,
        )


async def age_session(client: AsyncClient, field: str, delta: timedelta) -> None:
    """세션 행의 created/expires/last_seen 시각을 임의로 늙린다."""
    assert field in {"created_at", "expires_at", "last_seen_at"}
    token = client.cookies.get("hp015_session")
    assert token, "로그인 먼저"
    pool = db.get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            f"UPDATE sessions SET {field} = {field} - $2::interval "
            "WHERE session_hash = $1",
            auth_service.hash_token(token), delta,
        )


async def login(client: AsyncClient, username: str) -> httpx.Response:
    return await client.post(
        "/api/auth/login",
        json={"username": username, "password": TEST_PASSWORD},
    )


@pytest.mark.asyncio
async def test_login_sets_httponly_cookie_and_me_returns_user(client):
    user_id = await create_user("integ-alice", "supervisor")
    resp = await login(client, "integ-alice")
    assert resp.status_code == 200

    set_cookie = resp.headers.get("set-cookie", "")
    assert "hp015_session=" in set_cookie
    assert "httponly" in set_cookie.lower()
    assert "samesite=lax" in set_cookie.lower()

    me = await client.get("/api/auth/me")
    assert me.status_code == 200
    body = me.json()
    assert body["username"] == "integ-alice"
    assert body["role"] == "supervisor"
    assert body["id"] == user_id


@pytest.mark.asyncio
async def test_wrong_password_401_without_cookie(client):
    await create_user("integ-bob")
    resp = await client.post(
        "/api/auth/login", json={"username": "integ-bob", "password": "nope"}
    )
    assert resp.status_code == 401
    assert "hp015_session" not in resp.cookies


@pytest.mark.asyncio
async def test_logout_invalidates_session(client):
    await create_user("integ-carol")
    await login(client, "integ-carol")
    assert (await client.get("/api/auth/me")).status_code == 200

    out = await client.post("/api/auth/logout")
    assert out.status_code == 204

    # 로그아웃 후 동일 쿠키로 401 (이슈 완료 조건).
    assert (await client.get("/api/auth/me")).status_code == 401


@pytest.mark.asyncio
async def test_me_without_session_401(client):
    assert (await client.get("/api/auth/me")).status_code == 401


@pytest.mark.asyncio
async def test_idle_expiry_after_8h(client):
    """유휴 만료: last_seen_at 을 9시간 늙리면 401 (FR-604: 8h)."""
    settings.session_idle_ttl_hours = 8.0
    await create_user("integ-idle")
    await login(client, "integ-idle")
    await age_session(client, "last_seen_at", timedelta(hours=9))
    assert (await client.get("/api/auth/me")).status_code == 401


@pytest.mark.asyncio
async def test_idle_not_expired_within_8h(client):
    await create_user("integ-active")
    await login(client, "integ-active")
    await age_session(client, "last_seen_at", timedelta(hours=7))
    assert (await client.get("/api/auth/me")).status_code == 200


@pytest.mark.asyncio
async def test_absolute_expiry_after_12h(client):
    """절대 만료: expires_at 이 지나면 last_seen 이 최신이어도 401."""
    await create_user("integ-abs")
    await login(client, "integ-abs")
    # 마지막 활동은 방금(유휴 만료 아님)이지만 발급이 13시간 전.
    await age_session(client, "expires_at", timedelta(hours=13))
    await age_session(client, "created_at", timedelta(hours=13))
    assert (await client.get("/api/auth/me")).status_code == 401


@pytest.mark.asyncio
async def test_password_change_revokes_all_sessions(client, client2):
    await create_user("integ-dave")
    first = await login(client, "integ-dave")
    second = await login(client2, "integ-dave")
    csrf_token = second.json()["csrf_token"]

    changed = await client2.post(
        "/api/auth/password",
        json={"current_password": TEST_PASSWORD, "new_password": "new-password-123"},
        headers={"X-CSRF-Token": csrf_token},
        cookies={"hp015_csrf": csrf_token},
    )
    assert changed.status_code == 204

    # 다른 기기(첫 세션)도 폐기됐다 — 비밀번호 변경은 전 세션 무효화.
    assert (await client.get("/api/auth/me")).status_code == 401
    assert (await client2.get("/api/auth/me")).status_code == 401

    # 새 비밀번호로 재로그인 가능.
    resp = await client.post(
        "/api/auth/login", json={"username": "integ-dave", "password": "new-password-123"}
    )
    assert resp.status_code == 200
    assert first.status_code == 200


@pytest.mark.asyncio
async def test_password_change_requires_csrf(client):
    await create_user("integ-csrf")
    await login(client, "integ-csrf")

    changed = await client.post(
        "/api/auth/password",
        json={"current_password": TEST_PASSWORD, "new_password": "new-password-123"},
        # X-CSRF-Token 헤더 없음 → 403
    )
    assert changed.status_code == 403
    # 세션은 여전히 유효 — CSRF 거부는 로그아웃이 아니다.
    assert (await client.get("/api/auth/me")).status_code == 200


@pytest.mark.asyncio
async def test_password_never_leaks_in_responses(client):
    """FR-603 — password_hash 가 어떤 응답에도 등장하지 않는다."""
    await create_user("integ-secret")
    resp = await login(client, "integ-secret")
    assert "password_hash" not in resp.text

    me = await client.get("/api/auth/me")
    assert "password_hash" not in me.text
