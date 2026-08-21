"""감사 로그 통합 테스트 — 실제 DB (AUTH-5, 이슈 #135).

완료 조건:
- 임계값 변경 시 detail 에 before/after 기록
- 로그인 성공/실패·로그아웃·작업자 변경 기록
- 계정 삭제 후에도 actor_name 으로 추적 가능 (비정규화 검증)
- GET /api/audit-log 는 admin 전용 + 필터 동작
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app import db
from app.services import auth_service

pytestmark = pytest.mark.skipif(
    not __import__("os").getenv("TEST_TIMESCALE_URL", ""),
    reason="TEST_TIMESCALE_URL 이 없어 통합 테스트를 건너뜁니다",
)

TEST_PASSWORD = "audit-test-password"


@pytest.fixture
async def client(db_pool):
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def _make_admin(client: AsyncClient, username: str = "audit-admin") -> None:
    pool = db.get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO users (username, password_hash, display_name, role)
            VALUES ($1, $2, $3, 'admin')
            ON CONFLICT (username) DO UPDATE SET password_hash = EXCLUDED.password_hash
            """,
            username, auth_service.hash_password(TEST_PASSWORD), username,
        )
    resp = await client.post(
        "/api/auth/login", json={"username": username, "password": TEST_PASSWORD}
    )
    assert resp.status_code == 200
    csrf = resp.json()["csrf_token"]
    client.headers["X-CSRF-Token"] = csrf
    client.cookies.set("hp015_csrf", csrf)


@pytest.mark.asyncio
async def test_login_success_and_failure_recorded(client):
    await _make_admin(client)

    rows = await _fetch(client, action="login")
    actions = {r["action"] for r in rows}
    assert "login.success" in actions

    await client.post(
        "/api/auth/login", json={"username": "audit-admin", "password": "wrong"}
    )
    rows = await _fetch(client, action="login")
    actions = {r["action"] for r in rows}
    assert "login.failure" in actions


async def _fetch(client: AsyncClient, **params) -> list[dict]:
    resp = await client.get("/api/audit-log", params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_threshold_update_records_before_after(client):
    await _make_admin(client)

    resp = await client.put(
        "/api/thresholds/co2_ppm/level1_caution",
        json={
            "enter_threshold": 1234.0,
            "exit_threshold": 1100.0,
            "direction": "above",
            "enter_for_ms": 3000,
            "exit_for_ms": 5000,
        },
    )
    assert resp.status_code == 200

    rows = await _fetch(client, action="threshold.update")
    assert rows, "임계값 변경이 감사 로그에 없다"
    detail = rows[0]["detail"]
    assert detail["after"]["enter_threshold"] == 1234.0
    assert detail["before"] is not None
    assert detail["before"]["enter_threshold"] != 1234.0
    assert rows[0]["actor_name"] == "audit-admin"
    assert rows[0]["target"] == "co2_ppm/level1_caution"


@pytest.mark.asyncio
async def test_worker_lifecycle_recorded(client):
    await _make_admin(client)

    created = await client.post(
        "/api/workers", json={"employee_no": "AUD-001", "name": "감대상"}
    )
    assert created.status_code == 201
    worker_id = created.json()["id"]

    assigned = await client.post(
        f"/api/workers/{worker_id}/assign", json={"node_id": "wearable-01"}
    )
    assert assigned.status_code == 201

    rows = await _fetch(client, action="worker")
    actions = {r["action"] for r in rows}
    assert {"worker.create", "worker.assign"} <= actions


@pytest.mark.asyncio
async def test_actor_name_survives_account_deletion(client):
    """FR-605 — 계정이 삭제돼도 actor_name 으로 행위자 추적이 가능하다."""
    await _make_admin(client)
    await client.put(
        "/api/thresholds/co2_ppm/level2_warning",
        json={
            "enter_threshold": 2222.0,
            "exit_threshold": 2100.0,
            "direction": "above",
            "enter_for_ms": 3000,
            "exit_for_ms": 5000,
        },
    )

    # 계정 삭제 (cascade 로 세션은 사라져도 audit_log 행은 남는다 — FK 가 아님)
    pool = db.get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM users WHERE username = 'audit-admin'")

    client.headers.pop("X-CSRF-Token", None)
    client.cookies.clear()

    # 새 관리자로 조회
    await _make_admin(client, username="audit-admin2")
    rows = await _fetch(client, action="threshold.update", actor_name="audit-admin")
    assert rows, "삭제된 계정의 감사 이력도 actor_name 으로 조회되어야 한다"


@pytest.mark.asyncio
async def test_audit_log_endpoint_admin_only(client):
    await _make_admin(client)
    assert (await client.get("/api/audit-log")).status_code == 200

    pool = db.get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO users (username, password_hash, display_name, role)
            VALUES ('audit-viewer', $1, 'v', 'viewer')
            ON CONFLICT (username) DO UPDATE SET password_hash = EXCLUDED.password_hash
            """,
            auth_service.hash_password(TEST_PASSWORD),
        )
    await client.post("/api/auth/logout")
    resp = await client.post(
        "/api/auth/login", json={"username": "audit-viewer", "password": TEST_PASSWORD}
    )
    assert resp.status_code == 200
    assert (await client.get("/api/audit-log")).status_code == 403
