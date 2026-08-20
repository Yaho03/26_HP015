"""RBAC 매트릭스 통합 테스트 — 실제 DB + 실제 HTTP (AUTH-3, 이슈 #133).

완료 조건:
1. 화이트리스트(/health, /api/auth/login) 외 모든 경로가 무인증 시 401
2. 무인증 PUT /api/thresholds → 401 (#116 P1-15)
3. supervisor/viewer 의 임계값 수정 → 403
4. 역할 매트릭스 전 셀 검증 (FR-602)
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

TEST_PASSWORD = "authz-matrix-password"


@pytest.fixture
async def anon(db_pool):
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def role_client(role: str, db_pool) -> AsyncClient:
    """해당 역할로 로그인한 클라이언트. csrf 헤더 헬퍼를 함께 단다."""
    from app.main import app

    username = f"authz-{role}"
    pool = db.get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO users (username, password_hash, display_name, role)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (username) DO UPDATE SET password_hash = EXCLUDED.password_hash
            """,
            username, auth_service.hash_password(TEST_PASSWORD), username, role,
        )

    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test")
    resp = await client.post(
        "/api/auth/login", json={"username": username, "password": TEST_PASSWORD}
    )
    assert resp.status_code == 200, f"{role} 로그인 실패: {resp.text}"
    csrf = resp.json()["csrf_token"]
    client.headers["X-CSRF-Token"] = csrf
    client.cookies.set("hp015_csrf", csrf)
    return client


@pytest.fixture
async def admin(db_pool):
    c = await role_client("admin", db_pool)
    yield c
    await c.aclose()


@pytest.fixture
async def supervisor(db_pool):
    c = await role_client("supervisor", db_pool)
    yield c
    await c.aclose()


@pytest.fixture
async def viewer(db_pool):
    c = await role_client("viewer", db_pool)
    yield c
    await c.aclose()


# ============================================================
# 1. 화이트리스트 외 전 경로 무인증 401 (파라미터라이즈)
# ============================================================

def _http_routes():
    from app.main import app
    from app.dependencies.auth import PUBLIC_PATHS
    from fastapi.routing import APIRoute

    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue  # WebSocketRoute — AUTH-4(#134) 범위
        if route.path in PUBLIC_PATHS:
            continue
        for method in route.methods:
            if method == "HEAD":
                continue
            yield pytest.param(route.path, method, id=f"{method} {route.path}")


@pytest.mark.parametrize("path,method", list(_http_routes()))
@pytest.mark.asyncio
async def test_every_non_public_route_requires_auth(anon, path, method):
    """앱 게이트는 라우트 파라미터 검증보다 먼저 401 을 내야 한다."""
    resp = await anon.request(method, path)
    assert resp.status_code == 401, (
        f"{method} {path} 가 무인증으로 {resp.status_code} — 화이트리스트 누출"
    )


@pytest.mark.asyncio
async def test_health_is_public(anon):
    assert (await anon.get("/health")).status_code == 200


@pytest.mark.asyncio
async def test_login_is_public(anon):
    """로그인 경로는 게이트를 통과해 자격증명 오류로 응답해야 한다."""
    resp = await anon.post(
        "/api/auth/login", json={"username": "nobody", "password": "x"}
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid username or password"


# ============================================================
# 2. 임계값 수정 권한 (#116 P1-15)
# ============================================================

async def put_threshold(client: AsyncClient, value: float = 1001.0):
    return await client.put(
        "/api/thresholds/co2_ppm/level1_caution",
        json={
            "enter_threshold": value,
            "exit_threshold": value - 50,
            "enter_for_ms": 3000,
            "exit_for_ms": 5000,
        },
    )


@pytest.mark.asyncio
async def test_admin_can_update_thresholds(admin):
    resp = await put_threshold(admin)
    assert resp.status_code == 200, resp.text
    assert resp.json()["enter_threshold"] == 1001.0


@pytest.mark.asyncio
async def test_supervisor_cannot_update_thresholds(supervisor):
    assert (await put_threshold(supervisor)).status_code == 403


@pytest.mark.asyncio
async def test_viewer_cannot_update_thresholds(viewer):
    assert (await put_threshold(viewer)).status_code == 403


@pytest.mark.asyncio
async def test_threshold_update_requires_csrf(admin):
    admin.headers.pop("X-CSRF-Token")
    resp = await put_threshold(admin)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_all_roles_can_read_thresholds(admin, supervisor, viewer):
    for client in (admin, supervisor, viewer):
        assert (await client.get("/api/thresholds")).status_code == 200


# ============================================================
# 3. 역할 매트릭스 나머지 셀
# ============================================================

@pytest.mark.asyncio
async def test_metrics_admin_only(admin, supervisor, viewer):
    assert (await admin.get("/api/metrics")).status_code == 200
    assert (await supervisor.get("/api/metrics")).status_code == 403
    assert (await viewer.get("/api/metrics")).status_code == 403


@pytest.mark.asyncio
async def test_csv_export_supervisor_or_above(admin, supervisor, viewer):
    query = {
        "node_id": "sensor-01",
        "metric": "co2_ppm",
        "start": "2026-08-01T00:00:00Z",
        "end": "2026-08-02T00:00:00Z",
    }
    assert (await admin.get("/api/sensor-data/export", params=query)).status_code == 200
    assert (await supervisor.get("/api/sensor-data/export", params=query)).status_code == 200
    assert (await viewer.get("/api/sensor-data/export", params=query)).status_code == 403


@pytest.mark.asyncio
async def test_worker_crud_supervisor_or_above(admin, supervisor, viewer):
    payload = {"employee_no": f"authz-{id(object())}", "name": "테스트"}
    assert (await supervisor.post("/api/workers", json=payload)).status_code == 201
    assert (await admin.post("/api/workers", json=payload)).status_code == 409  # 사번 중복 = 권한 통과
    assert (await viewer.post("/api/workers", json=payload)).status_code == 403


@pytest.mark.asyncio
async def test_worker_reads_available_to_all_roles(admin, supervisor, viewer):
    for client in (admin, supervisor, viewer):
        assert (await client.get("/api/workers")).status_code == 200


@pytest.mark.asyncio
async def test_demo_control_admin_only(supervisor, viewer):
    # 기능이 비활성이라도 권한 검사가 먼저다 — 비관리자는 403.
    assert (await supervisor.get("/api/demo/scenarios")).status_code == 403
    assert (await viewer.post("/api/demo/run", json={"scenario": "x"})).status_code == 403
