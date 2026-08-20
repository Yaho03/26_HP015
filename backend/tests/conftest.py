"""단위 테스트 공용 픽스처.

AUTH-3(#133)부터 앱 전체에 인증 게이트가 붙었다. 단위 테스트는 라우터 로직
자체를 검증하는 계층이므로 게이트를 통과한 admin 으로 가짜 인증한다 —
인증/인가 동작 자체는 tests/integration/test_authz_matrix.py 가 실DB 로
검증한다. 통합 디렉터리는 이 오버라이드를 쓰지 않는다 (진짜 게이트 대상).
"""
from __future__ import annotations

import pytest

from app.dependencies import auth as deps_auth
from app.repositories.user_repository import UserRow


def _fake_user(role: str = "admin") -> UserRow:
    return UserRow(
        {
            "id": 1,
            "username": "unit-admin",
            "password_hash": "",
            "display_name": "단위테스트",
            "role": role,
            "is_active": True,
            "must_change_password": False,
        }
    )


def install_admin_auth(app) -> None:
    """테스트용 로컬 FastAPI 앱(라우터 일부만 마운트)에도 같은 가짜 인증을 단다.

    app.dependency_overrides 는 앱 인스턴스별로 있어서, main.app 이 아닌
    앱을 만드는 테스트(test_demo_control 등)는 이 헬퍼를 직접 호출해야 한다.
    """
    async def _noop_gate():
        return None

    app.dependency_overrides[deps_auth.enforce_authentication] = _noop_gate
    app.dependency_overrides[deps_auth._bearer_user] = lambda: _fake_user("admin")
    app.dependency_overrides[deps_auth.verify_csrf] = lambda: None


@pytest.fixture(autouse=True)
def _auth_override(request):
    """tests/integration 밖의 단위 테스트만 게이트를 통과시킨다."""
    if "integration" in str(request.fspath):
        yield
        return

    from app.main import app

    install_admin_auth(app)
    try:
        yield
    finally:
        app.dependency_overrides.pop(deps_auth.enforce_authentication, None)
        app.dependency_overrides.pop(deps_auth._bearer_user, None)
        app.dependency_overrides.pop(deps_auth.verify_csrf, None)
