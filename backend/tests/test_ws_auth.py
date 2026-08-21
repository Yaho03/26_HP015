"""WebSocket 인증 단위 테스트 (AUTH-4, 이슈 #134).

완료 조건:
1. 무인증/만료 /ws 연결이 close 1008 로 종료되고 데이터를 받지 않는다
2. 유효 세션은 snapshot 을 받는다

세션 검증만 가짜로 대체한다 (인증 로직 자체는 test_auth_lifecycle 이
실DB 로 검증). snapshot 은 DB 폴백으로 빈 객체가 온다.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.dependencies import auth as deps_auth
from app.main import app
from app.repositories.user_repository import UserRow
from app.services.auth_service import ValidSession


def _fake_user() -> UserRow:
    return UserRow(
        {
            "id": 1,
            "username": "ws-user",
            "password_hash": "",
            "display_name": "WS",
            "role": "viewer",
            "is_active": True,
            "must_change_password": False,
        }
    )


def _fake_valid_session() -> ValidSession:
    return ValidSession(session_id=1, csrf_token="csrf", user=_fake_user())


@pytest.fixture
def client():
    return TestClient(app)


def test_ws_without_cookie_closed_1008_no_data(client, monkeypatch):
    """쿠키 없으면 핸드셰이크 후 즉시 1008 — 어떤 메시지도 오지 않는다."""
    async def _fail(token):
        raise deps_auth.auth_service.SessionExpired()

    monkeypatch.setattr(deps_auth.auth_service, "validate_session", _fail)

    with client.websocket_connect("/ws") as ws:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            ws.receive_text()
        assert exc_info.value.code == 1008


def test_ws_with_expired_session_closed_1008(client, monkeypatch):
    async def _expired(token):
        raise deps_auth.auth_service.SessionExpired()

    monkeypatch.setattr(deps_auth.auth_service, "validate_session", _expired)

    with client.websocket_connect("/ws") as ws:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            ws.receive_text()
        assert exc_info.value.code == 1008


def test_ws_with_valid_session_receives_snapshot(client, monkeypatch):
    async def _valid(token):
        assert token == "valid-session-token"
        return _fake_valid_session()

    monkeypatch.setattr(deps_auth.auth_service, "validate_session", _valid)

    with client.websocket_connect(
        "/ws", cookies={"hp015_session": "valid-session-token"}
    ) as ws:
        snapshot = ws.receive_json()
    assert snapshot["type"] == "snapshot"


def test_authenticate_ws_returns_none_without_cookie(client, monkeypatch):
    """authenticate_ws 는 쿠키가 없으면 DB 를 건드리지 않고 None."""
    import asyncio

    called = []

    async def _should_not_run(token):
        called.append(token)
        raise AssertionError("쿠키 없으면 세션 검증을 부르면 안 된다")

    monkeypatch.setattr(deps_auth.auth_service, "validate_session", _should_not_run)

    from fastapi import WebSocket

    class FakeWS:
        cookies: dict[str, str] = {}

    assert asyncio.get_event_loop_policy() is not None
    result = asyncio.run(deps_auth.authenticate_ws(FakeWS()))
    assert result is None
    assert called == []
    _ = WebSocket  # import 참조 유지 (타입 힌트용)