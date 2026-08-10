"""이슈 #58: WebSocket 서버 — TDD 테스트."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient


def test_websocket_endpoint_exists():
    from app.main import app
    routes = [r.path for r in app.routes]
    assert "/ws" in routes


def test_websocket_connect_and_receive_snapshot():
    from app.main import app
    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        data = ws.receive_json()
    assert data["type"] == "snapshot"
    assert "nodes" in data
    assert "alerts" in data


def test_websocket_manager_module_importable():
    from app.services import ws_manager
    assert hasattr(ws_manager, "ConnectionManager")
    assert hasattr(ws_manager, "manager")


def test_websocket_manager_broadcast_to_all_clients():
    from app.services.ws_manager import ConnectionManager

    mng = ConnectionManager()
    received = []

    class FakeWS:
        async def send_json(self, msg):
            received.append(msg)

    mng._clients.add(FakeWS())
    mng._clients.add(FakeWS())

    import asyncio
    asyncio.run(mng.broadcast({"type": "alert", "data": 1}))
    assert len(received) == 2


def test_websocket_manager_broadcast_skips_disconnected_clients():
    from app.services.ws_manager import ConnectionManager

    mng = ConnectionManager()

    class GoodWS:
        received = []
        async def send_json(self, msg):
            self.received.append(msg)

    class BadWS:
        async def send_json(self, msg):
            raise RuntimeError("disconnected")

    good = GoodWS()
    mng._clients.add(good)
    mng._clients.add(BadWS())

    import asyncio
    asyncio.run(mng.broadcast({"type": "alert"}))

    assert len(mng._clients) == 1
    assert good in mng._clients


def test_alert_publisher_triggers_ws_broadcast(monkeypatch):
    """alert_publisher 가 ws_manager.broadcast 를 호출하는지 검증."""
    from app.services import ws_manager

    broadcasted: list = []

    async def _fake_broadcast(msg):
        broadcasted.append(msg)
    monkeypatch.setattr(ws_manager.manager, "broadcast", _fake_broadcast)

    from app.services import alert_service
    from app.models.alert import AlertLevel, AlertTransition
    from datetime import datetime, timezone

    class _FakePublisher:
        async def publish_transition(self, t):
            pass
    monkeypatch.setattr(alert_service, "_publisher", _FakePublisher())

    transition = AlertTransition(
        node_id="sensor-01", metric="co2_ppm",
        from_level=AlertLevel.NORMAL, to_level=AlertLevel.LEVEL1,
        value=1100.0, threshold=1000.0,
        timestamp=datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc),
    )
    import asyncio
    asyncio.run(alert_service._handle_transition(transition))

    assert len(broadcasted) == 1
    assert broadcasted[0]["type"] == "alert"
