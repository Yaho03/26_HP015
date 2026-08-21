"""계정 잠금 + rate limit + 사용자 관리 통합 테스트 — 실DB (AUTH-10, 이슈 #140).

완료 조건:
- 5회 실패 후 올바른 비밀번호로도 401
- 잠금 해제(locked_until 경과) 후 정상 로그인
- 존재하지 않는 계정 vs 잘못된 비밀번호 응답 동일
- IP rate limit 분당 10회 → 429
- 사용자 CRUD 감사 로그
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from app import db
from app.services import auth_service
from app.routers.auth import _login_attempts

pytestmark = pytest.mark.skipif(
    not __import__("os").getenv("TEST_TIMESCALE_URL", ""),
    reason="TEST_TIMESCALE_URL 이 없어 통합 테스트를 건너뜁니다",
)

PASSWORD = "lockout-test-pw"


@pytest.fixture
async def client(db_pool):
    from app.main import app

    _login_attempts.clear()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


async def _create_user(username: str, role: str = "viewer") -> None:
    pool = db.get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO users (username, password_hash, display_name, role)
            VALUES ($1, $2, $1, $3)
            ON CONFLICT (username) DO UPDATE SET
                password_hash = EXCLUDED.password_hash,
                failed_login_attempts = 0,
                locked_until = NULL
            """,
            username, auth_service.hash_password(PASSWORD), role,
        )


async def _try_login(client: AsyncClient, username: str, password: str):
    return await client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )


@pytest.mark.asyncio
async def test_lockout_after_5_failures(client):
    await _create_user("lock-user")

    for i in range(5):
        resp = await _try_login(client, "lock-user", "wrong")
        assert resp.status_code == 401

    # 5회 실패 후 올바른 비밀번호로도 401 (완료 조건).
    resp = await _try_login(client, "lock-user", PASSWORD)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_lockout_release_after_10_minutes(client):
    await _create_user("unlock-user")
    for _ in range(5):
        await _try_login(client, "unlock-user", "wrong")

    pool = db.get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET locked_until = now() - interval '1 minute' "
            "WHERE username = 'unlock-user'"
        )

    resp = await _try_login(client, "unlock-user", PASSWORD)
    assert resp.status_code == 200, "잠금 해제 후 정상 로그인되어야 한다"


@pytest.mark.asyncio
async def test_four_failures_do_not_lock(client):
    await _create_user("almost-user")
    for _ in range(4):
        await _try_login(client, "almost-user", "wrong")
    resp = await _try_login(client, "almost-user", PASSWORD)
    assert resp.status_code == 200, "4회 실패는 아직 잠금 아니다"


@pytest.mark.asyncio
async def test_success_resets_failure_counter(client):
    await _create_user("reset-user")
    for _ in range(4):
        await _try_login(client, "reset-user", "wrong")
    assert (await _try_login(client, "reset-user", PASSWORD)).status_code == 200
    # 카운터 리셋 — 실패 4회가 다시 누적돼도 잠기지 않는다.
    for _ in range(4):
        await _try_login(client, "reset-user", "wrong")
    assert (await _try_login(client, "reset-user", PASSWORD)).status_code == 200


@pytest.mark.asyncio
async def test_unknown_account_and_wrong_password_indistinguishable(client):
    await _create_user("real-user")
    wrong = await _try_login(client, "real-user", "wrong")
    unknown = await _try_login(client, "ghost-user", "wrong")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["detail"] == unknown.json()["detail"]


@pytest.mark.asyncio
async def test_login_rate_limit_per_ip(client):
    """분당 10회 초과 → 429 (계정 존재 여부와 무관)."""
    for i in range(10):
        resp = await _try_login(client, f"ghost-{i}", "x")
        assert resp.status_code == 401
    limited = await _try_login(client, "any-user", "x")
    assert limited.status_code == 429


@pytest.mark.asyncio
async def test_user_management_crud_with_audit(client):
    await _create_user("mgmt-admin", "admin")
    resp = await _try_login(client, "mgmt-admin", PASSWORD)
    assert resp.status_code == 200
    csrf = resp.json()["csrf_token"]
    client.headers["X-CSRF-Token"] = csrf
    client.cookies.set("hp015_csrf", csrf)

    created = await client.post(
        "/api/users",
        json={"username": "new-supervisor", "password": "initial-pw-123", "role": "supervisor"},
    )
    assert created.status_code == 201
    user_id = created.json()["id"]
    assert created.json()["must_change_password"] is True

    patched = await client.patch(
        f"/api/users/{user_id}", json={"is_active": False}
    )
    assert patched.status_code == 200
    assert patched.json()["is_active"] is False

    reset = await client.post(f"/api/users/{user_id}/reset-password")
    assert reset.status_code == 200
    temp = reset.json()["temporary_password"]
    assert len(temp) >= 12

    audit = await client.get("/api/audit-log", params={"action": "user"})
    actions = {row["action"] for row in audit.json()}
    assert {"user.create", "user.update", "user.password_reset"} <= actions


@pytest.mark.asyncio
async def test_last_admin_cannot_be_demoted_or_deactivated(client):
    await _create_user("solo-admin", "admin")
    resp = await _try_login(client, "solo-admin", PASSWORD)
    csrf = resp.json()["csrf_token"]
    client.headers["X-CSRF-Token"] = csrf
    client.cookies.set("hp015_csrf", csrf)

    pool = db.get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM users WHERE username != 'solo-admin'")
        admin_id = await conn.fetchval(
            "SELECT id FROM users WHERE username = 'solo-admin'"
        )

    demote = await client.patch(f"/api/users/{admin_id}", json={"role": "viewer"})
    assert demote.status_code == 409

    deactivate = await client.patch(f"/api/users/{admin_id}", json={"is_active": False})
    assert deactivate.status_code == 409
