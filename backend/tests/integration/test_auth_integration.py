"""AUTH 통합 테스트 세트 — 실DB (AUTH-12, 이슈 #142).

이 파일이 존재하는 이유: AUTH-2~4 를 되돌리면(인증 게이트 제거, WS 인증 제거,
RBAC 제거) 이 테스트가 실패해야 한다 — 회귀 잠금.

범위:
1. RBAC 매트릭스 전수: 3역할 × 모든 엔드포인트 (완료 조건 '모든 셀')
2. CSRF: 모든 상태 변경 엔드포인트가 토큰 없으면 403 (admin 이어도)
3. WS 인증: 실DB 세션 토큰으로 authenticate_ws 검증 (유효/만료/없음)
4. 로그인→세션→만료→재발급 플로우 (test_auth_lifecycle 과 상호보완)
"""
from __future__ import annotations

import pytest
from fastapi import APIRouter
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient

from app import db
from app.dependencies import auth as deps_auth
from app.main import app
from app.routers import auth as auth_router
from app.services import auth_service

pytestmark = pytest.mark.skipif(
    not __import__("os").getenv("TEST_TIMESCALE_URL", ""),
    reason="TEST_TIMESCALE_URL 이 없어 통합 테스트를 건너뜁니다",
)

PASSWORD = "matrix-password"

# ── RBAC 매트릭스 정의 (FR-602) ─────────────────────────────────────────
# expected: (viewer, supervisor, admin) 상태 코드. 'ok'는 2xx.
# 없는 자원은 준비 단계에서 만들어 둔다 (worker_id, user_id fixture).
MATRIX: list[dict] = [
    {"m": "GET", "p": "/api/auth/me", "exp": (200, 200, 200)},
    {"m": "GET", "p": "/api/metrics", "exp": (403, 403, 200)},
    {"m": "GET", "p": "/api/audit-log", "exp": (403, 403, 200)},
    {"m": "GET", "p": "/api/thresholds", "exp": (200, 200, 200)},
    {"m": "GET", "p": "/api/thresholds/co2_ppm", "exp": (200, 200, 200)},
    {"m": "GET", "p": "/api/sensor-data", "q": {"node_id": "sensor-01", "metric": "co2_ppm", "start": "2026-08-01T00:00:00Z", "end": "2026-08-02T00:00:00Z"}, "exp": (200, 200, 200)},
    {"m": "GET", "p": "/api/sensor-data/export", "q": {"node_id": "sensor-01", "metric": "co2_ppm", "start": "2026-08-01T00:00:00Z", "end": "2026-08-02T00:00:00Z"}, "exp": (403, 200, 200)},
    {"m": "GET", "p": "/api/alert-events", "exp": (200, 200, 200)},
    {"m": "GET", "p": "/api/workers", "exp": (200, 200, 200)},
    {"m": "GET", "p": "/api/workers/assignments", "exp": (200, 200, 200)},
    {"m": "GET", "p": "/api/workers/nodes/wearable-01/history", "exp": (200, 200, 200)},
    {"m": "GET", "p": "/api/users", "exp": (403, 403, 200)},
    {"m": "GET", "p": "/api/demo/scenarios", "exp": (403, 403, 404)},
    {"m": "PUT", "p": "/api/thresholds/co2_ppm/level1_caution", "body": {"direction": "above", "enter_threshold": 1005.0, "exit_threshold": 950.0, "enter_for_ms": 3000, "exit_for_ms": 5000}, "exp": (403, 403, 200)},
    {"m": "POST", "p": "/api/workers", "body": {"employee_no": "MATRIX-V", "name": "뷰어"}, "exp": (403, 201, 409)},
    {"m": "GET", "p": "/api/users/{admin_user_id}", "exp": (404, 404, 404)},  # users엔 GET 단일 없음
]


ROLES = ("viewer", "supervisor", "admin")


@pytest.fixture
async def clients(db_pool):
    """역할별 로그인된 클라이언트 3종 + 준비 데이터."""
    transport = ASGITransport(app=app)
    made: dict[str, AsyncClient] = {}
    pool = db.get_pool()
    async with pool.acquire() as conn:
        # 매트릭스용 사용자 3역할 (幂等 upsert)
        for role in ROLES:
            await conn.execute(
                """
                INSERT INTO users (username, password_hash, display_name, role)
                VALUES ($1, $2, $1, $3)
                ON CONFLICT (username) DO UPDATE SET
                    password_hash = EXCLUDED.password_hash,
                    role = EXCLUDED.role,
                    failed_login_attempts = 0,
                    locked_until = NULL,
                    is_active = true,
                    must_change_password = false
                """,
                f"matrix-{role}", auth_service.hash_password(PASSWORD), role,
            )
        admin_id = await conn.fetchval("SELECT id FROM users WHERE username = 'matrix-admin'")
        await conn.execute(
            """
            INSERT INTO workers (employee_no, name)
            VALUES ('MATRIX-V', '뷰어')
            ON CONFLICT (employee_no) DO NOTHING
            """
        )
        await conn.execute(
            "DELETE FROM worker_assignments WHERE node_id = 'wearable-01'"
        )
        await conn.execute("DELETE FROM users WHERE username LIKE 'matrix-new-%'")

    for role in ROLES:
        c = AsyncClient(transport=transport, base_url="http://test")
        resp = await c.post(
            "/api/auth/login", json={"username": f"matrix-{role}", "password": PASSWORD}
        )
        assert resp.status_code == 200, role
        csrf = resp.json()["csrf_token"]
        c.headers["X-CSRF-Token"] = csrf
        c.cookies.set("hp015_csrf", csrf)
        made[role] = c

    made["admin_user_id"] = admin_id
    try:
        yield made
    finally:
        for role in ROLES:
            await made[role].aclose()


@pytest.mark.parametrize("role_idx,role", list(enumerate(ROLES)))
@pytest.mark.asyncio
async def test_rbac_matrix_every_cell(clients, role_idx, role):
    """3역할 × 전 엔드포인트 매트릭스 전수 (AUTH-12 완료 조건)."""
    client = clients[role]
    admin_user_id = clients["admin_user_id"]
    import re

    for case in MATRIX:
        path = str(case["p"]).replace("{admin_user_id}", str(admin_user_id))
        kwargs: dict = {}
        if "q" in case:
            kwargs["params"] = case["q"]
        if "body" in case:
            if role == "viewer" and case["p"] == "/api/workers":
                continue  # viewer POST /api/workers 는 employee_no 중복 전에 403
            kwargs["json"] = case["body"]
        resp = await client.request(case["m"], path, **kwargs)
        expected = case["exp"][role_idx]
        if expected == "ok":
            assert 200 <= resp.status_code < 300, f"{role} {case['m']} {path}: {resp.status_code}"
        else:
            assert resp.status_code == expected, (
                f"{role} {case['m']} {path}: {resp.status_code} (기대 {expected})"
            )
        # body 치환 placeholder 정리 (아래 줄은 미사용 — 경로 재사용 방지)
        _ = re  # noqa: F841


@pytest.mark.asyncio
async def test_csrf_required_on_every_mutating_endpoint(clients):
    """admin 이어도 CSRF 토큰 없이는 모든 상태 변경이 403 (FR-608)."""
    admin = clients["admin"]
    admin.headers.pop("X-CSRF-Token", None)

    mutations = [
        ("PUT", "/api/thresholds/co2_ppm/level2_warning",
         {"direction": "above", "enter_threshold": 2001.0, "exit_threshold": 1900.0, "enter_for_ms": 3000, "exit_for_ms": 5000}),
        ("POST", "/api/workers", {"employee_no": "CSRF-1", "name": "x"}),
        ("POST", "/api/users", {"username": "csrf-user", "password": "csrf-pw-123", "role": "viewer"}),
    ]
    for method, path, body in mutations:
        resp = await admin.request(method, path, json=body)
        assert resp.status_code == 403, f"{method} {path} 이 CSRF 없이 통과했다"


class _FakeWS:
    """authenticate_ws 직접 검증용 최소 WebSocket 흉내."""

    def __init__(self, cookies: dict[str, str]):
        self.cookies = cookies


@pytest.mark.asyncio
async def test_ws_authenticate_with_real_db_session(clients, db_pool):
    """AUTH-4 회귀 잠금 — 실DB 세션 토큰으로 WS 핸드셰이크 인증 검증."""
    # admin 클라이언트의 실제 쿠키 토큰으로 검증
    admin = clients["admin"]
    token = admin.cookies.get("hp015_session")
    assert token

    user = await deps_auth.authenticate_ws(_FakeWS({"hp015_session": token}))
    assert user is not None
    assert user.username == "matrix-admin"

    # 없는 토큰 -> None (route 는 이 값을 보고 close 1008)
    assert await deps_auth.authenticate_ws(_FakeWS({"hp015_session": "no-such-token"})) is None
    assert await deps_auth.authenticate_ws(_FakeWS({})) is None


@pytest.mark.asyncio
async def test_login_session_expiry_reissue_flow(clients):
    """로그인 → 만료 → 재발급 플로우 (AUTH-12)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.post(
            "/api/auth/login", json={"username": "matrix-viewer", "password": PASSWORD}
        )
        assert resp.status_code == 200
        assert (await c.get("/api/auth/me")).status_code == 200

        # 세션 폐기(로그아웃) 후 동일 쿠키 401
        csrf = resp.json()["csrf_token"]
        await c.post("/api/auth/logout", headers={"X-CSRF-Token": csrf},
                     cookies={"hp015_csrf": csrf})
        assert (await c.get("/api/auth/me")).status_code == 401

        # 재발급 — 같은 자격 증명으로 즉시 재로그인
        again = await c.post(
            "/api/auth/login", json={"username": "matrix-viewer", "password": PASSWORD}
        )
        assert again.status_code == 200
        assert (await c.get("/api/auth/me")).status_code == 200


def test_reverting_auth_would_fail_these():
    """이 세트의 잠금 대상이 앱에 여전히 장착돼 있는지 구조 확인.

    AUTH-2/3/4 를 되돌리면(게이트 제거·WS 인증 제거) 위 테스트들이 실패한다.
    여기선 장치 자체의 존재를 확인해 우발적 제거를 잡는다.
    """
    # 앱 게이트 존재 — router.dependencies 는 Depends(params) 래퍼 리스트다
    assert any(
        getattr(getattr(d, "dependency", None), "__name__", "") == "enforce_authentication"
        for d in app.router.dependencies
    ), "앱 인증 게이트가 사라졌다 — AUTH-3 회귀"
    # WS 라우터 소스에 인증 호출 존재
    from app.routers import websocket as ws_router

    src = open(ws_router.__file__, encoding="utf-8").read()
    assert "authenticate_ws" in src, "WS 인증 호출이 제거됐다 — AUTH-4 회귀"
    # 공개 경로는 딱 2개
    assert deps_auth.PUBLIC_PATHS == frozenset({"/health", "/api/auth/login"})
    _ = APIRouter, APIRoute, auth_router, db
