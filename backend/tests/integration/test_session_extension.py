"""세션 유휴 연장 — 활성 경보 중 만료 방지 통합 테스트 (AUTH-7, 이슈 #137).

완료 조건: 세션 만료 상태에서 L3 경보 발생 시 경보 모달·알림음 정상 동작.
여기서 검증 가능한 백엔드 부분: 유휴 만료된 세션이 활성 L2+ 경보 중에는
만료되지 않고 자동 연장된다 (FR-607). 오버레이 UI는 App 컴포넌트 계약.
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from app import db
from app.services import auth_service

pytestmark = pytest.mark.skipif(
    not __import__("os").getenv("TEST_TIMESCALE_URL", ""),
    reason="TEST_TIMESCALE_URL 이 없어 통합 테스트를 건너뜁니다",
)

TEST_PASSWORD = "authz7-password"


@pytest.fixture
async def client(db_pool):
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def _login(client: AsyncClient, username: str = "authz7-user") -> None:
    pool = db.get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO users (username, password_hash, display_name, role)
            VALUES ($1, $2, $3, 'viewer')
            ON CONFLICT (username) DO UPDATE SET password_hash = EXCLUDED.password_hash
            """,
            username, auth_service.hash_password(TEST_PASSWORD), username,
        )
    resp = await client.post(
        "/api/auth/login", json={"username": username, "password": TEST_PASSWORD}
    )
    assert resp.status_code == 200


def _token(client: AsyncClient) -> str:
    token = client.cookies.get("hp015_session")
    assert token
    return token


async def _age_idle(client: AsyncClient, hours: float) -> None:
    token = _token(client)
    pool = db.get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE sessions SET last_seen_at = last_seen_at - $2::interval "
            "WHERE session_hash = $1",
            auth_service.hash_token(token), timedelta(hours=hours),
        )


async def _set_active_alert(level: str) -> None:
    """alert_events 에 활성 경보 1건을 남긴다 (발행 경로를 우회한 직접 삽입)."""
    pool = db.get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO alert_events (message_id, alert_id, source_node_id, alert_key,
                                      alert_type, level, trigger_value, threshold,
                                      metric, message, status, activated_at,
                                      published_at, schema_version)
            VALUES ($1, $2, 'sensor-01', 'sensor-01:co2_ppm', 'threshold', $3,
                    5100, 5000, 'co2_ppm', '테스트 경보', 'active', now(), now(), '1.1')
            """,
            f"authz7-{level}", f"authz7-{level}", level,
        )


async def _clear_active_alerts() -> None:
    pool = db.get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM alert_events WHERE message_id LIKE 'authz7-%'"
        )


@pytest.mark.asyncio
async def test_idle_expired_session_survives_while_l2_active(client):
    """활성 L2+ 경보 중에는 유휴 만료가 적용되지 않는다 (FR-607)."""
    await _login(client)
    await _set_active_alert("level2_warning")
    try:
        await _age_idle(client, hours=9)  # 유휴 8h 초과
        resp = await client.get("/api/auth/me")
        assert resp.status_code == 200, "경보 중에는 세션이 자동 연장되어야 한다"
    finally:
        await _clear_active_alerts()


@pytest.mark.asyncio
async def test_idle_expired_session_denied_without_alerts(client):
    """경보가 없으면 기존대로 유휴 만료가 적용된다 (연장이 남용되면 안 된다)."""
    await _login(client)
    await _clear_active_alerts()
    await _age_idle(client, hours=9)
    assert (await client.get("/api/auth/me")).status_code == 401


@pytest.mark.asyncio
async def test_absolute_expiry_still_applies_during_alert(client):
    """활성 경보 중에도 절대 만료(12h)는 유지된다 — 무한 세션 방지."""
    await _login(client)
    await _set_active_alert("level3_critical")
    try:
        token = _token(client)
        pool = db.get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE sessions SET expires_at = expires_at - $2::interval, "
                "created_at = created_at - $2::interval "
                "WHERE session_hash = $1",
                auth_service.hash_token(token), timedelta(hours=13),
            )
        assert (await client.get("/api/auth/me")).status_code == 401
    finally:
        await _clear_active_alerts()
