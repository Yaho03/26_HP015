"""부트스트랩 계정 라이프사이클 통합 테스트 — 실DB (AUTH-9, 이슈 #139).

완료 조건:
- 환경 변수로 부트스트랩 계정 생성
- 최초 로그인 시 비밀번호 변경 전 다른 API 접근 차단 (403)
- 변경 후 정상 접근
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app import db
from app.config import settings
from app.repositories import user_repository
from app.services import auth_service

pytestmark = pytest.mark.skipif(
    not __import__("os").getenv("TEST_TIMESCALE_URL", ""),
    reason="TEST_TIMESCALE_URL 이 없어 통합 테스트를 건너뜁니다",
)


@pytest.fixture
async def client(db_pool):
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_bootstrap_account_full_lifecycle(client, monkeypatch):
    pool = db.get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM users WHERE username = 'boot-admin'")

    monkeypatch.setattr(settings, "bootstrap_admin_username", "boot-admin")
    monkeypatch.setattr(settings, "bootstrap_admin_password", "boot-initial-pw")

    assert await auth_service.bootstrap_admin() is True
    # 두 번째 호출은 사용자가 이미 있으므로 아무것도 하지 않는다.
    monkeypatch.setattr(settings, "bootstrap_admin_password", "attacker-new-pw")
    assert await auth_service.bootstrap_admin() is False
    row = await user_repository.get_by_username("boot-admin")
    assert row is not None and row.role == "admin"
    assert auth_service.verify_password("boot-initial-pw", row.password_hash)
    assert not auth_service.verify_password("attacker-new-pw", row.password_hash)

    # 최초 로그인 — 세션은 발급되되 must_change_password 가 내려온다.
    resp = await client.post(
        "/api/auth/login", json={"username": "boot-admin", "password": "boot-initial-pw"}
    )
    assert resp.status_code == 200
    assert resp.json()["user"]["must_change_password"] is True

    # me 는 허용 (프론트가 상태를 알아야 변경 폼을 띄운다).
    assert (await client.get("/api/auth/me")).status_code == 200

    # 다른 API 는 403 — 변경 전 차단 (완료 조건).
    blocked = await client.get("/api/thresholds")
    assert blocked.status_code == 403
    assert blocked.json()["detail"] == "Password change required"

    # 비밀번호 변경 (자기 자신은 허용).
    csrf = resp.json()["csrf_token"]
    changed = await client.post(
        "/api/auth/password",
        json={"current_password": "boot-initial-pw", "new_password": "rotated-pw-123"},
        headers={"X-CSRF-Token": csrf},
        cookies={"hp015_csrf": csrf},
    )
    assert changed.status_code == 204

    # 재로그인 → 차단 해제.
    again = await client.post(
        "/api/auth/login", json={"username": "boot-admin", "password": "rotated-pw-123"}
    )
    assert again.status_code == 200
    assert again.json()["user"]["must_change_password"] is False
    assert (await client.get("/api/thresholds")).status_code == 200


@pytest.mark.asyncio
async def test_migrations_contain_no_seed_account(db_pool):
    """FR-610 — 마이그레이션 SQL 에 계정/해시가 하드코딩되지 않는다.

    주석(Argon2id 방식 설명 등)은 허용한다 — 실제 시드(INSERT INTO users,
    해시 리터럴 $argon2...)만 금지한다.
    """
    from pathlib import Path

    migrations = Path(__file__).resolve().parents[2] / "migrations"
    for sql_file in migrations.glob("*.sql"):
        executable_lines = [
            line for line in sql_file.read_text(encoding="utf-8").splitlines()
            if not line.strip().startswith("--")
        ]
        executable = "\n".join(executable_lines).upper()
        assert "INSERT INTO USERS" not in executable, (
            f"{sql_file.name} 이 users 를 시드하고 있다 — 부트스트랩은 환경 변수로만"
        )
        assert "$ARGON2" not in executable, (
            f"{sql_file.name} 에 해시 리터럴이 하드코딩되어 있다"
        )
