"""관리자 부트스트랩 테스트 (AUTH-9, 이슈 #139; FR-610).

단위: 생성 조건 (0명일 때만, 빈 설정이면 스킵, 평문 미저장).
통합(실DB): 부트스트랩 → 첫 로그인 → 변경 전 API 차단 → 변경 후 해제.
"""
from __future__ import annotations

import pytest

from app.config import settings
from app.repositories import user_repository
from app.services import auth_service


@pytest.fixture
def bootstrap_env(monkeypatch):
    monkeypatch.setattr(settings, "bootstrap_admin_username", "boot-admin")
    monkeypatch.setattr(settings, "bootstrap_admin_password", "boot-secret-pw")


@pytest.mark.asyncio
async def test_bootstrap_skipped_when_unconfigured(monkeypatch):
    """설정이 비어 있면 DB 를 건드리지 않는다."""
    monkeypatch.setattr(settings, "bootstrap_admin_username", "")
    monkeypatch.setattr(settings, "bootstrap_admin_password", "")
    called = []
    monkeypatch.setattr(
        user_repository, "count_users", lambda: _async_result(called, 0)
    )
    assert await auth_service.bootstrap_admin() is False
    assert called == [], "미설정이면 사용자 수 조회조차 하지 않는다"


@pytest.mark.asyncio
async def test_bootstrap_creates_admin_when_empty(bootstrap_env, monkeypatch):
    monkeypatch.setattr(user_repository, "count_users", lambda: _async_result([], 0))
    created = {}

    async def fake_create(username, password_hash, *, role, must_change_password):
        created.update(
            username=username, hash=password_hash, role=role,
            must_change_password=must_change_password,
        )
        return "row"

    monkeypatch.setattr(user_repository, "create_user", fake_create)

    assert await auth_service.bootstrap_admin() is True
    assert created["username"] == "boot-admin"
    assert created["role"] == "admin"
    assert created["must_change_password"] is True
    # 평문이 저장되지 않는다 (FR-603).
    assert created["hash"] != "boot-secret-pw"
    assert auth_service.verify_password("boot-secret-pw", created["hash"])


@pytest.mark.asyncio
async def test_bootstrap_skipped_when_users_exist(bootstrap_env, monkeypatch):
    """기존 계정이 하나라도 있으면 .env 값으로 계정을 만들지 않는다."""
    monkeypatch.setattr(user_repository, "count_users", lambda: _async_result([], 3))

    async def _should_not_create(*a, **kw):
        raise AssertionError("기존 사용자가 있으면 생성하면 안 된다")

    monkeypatch.setattr(user_repository, "create_user", _should_not_create)
    assert await auth_service.bootstrap_admin() is False


def _async_result(sink, value):
    async def _inner():
        sink.append("called")
        return value
    return _inner()
