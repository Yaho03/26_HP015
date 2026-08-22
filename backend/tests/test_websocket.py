"""이슈 #58: WebSocket 서버 — TDD 테스트."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient


def test_websocket_endpoint_exists():
    from app.main import app
    routes = [r.path for r in app.routes]
    assert "/ws" in routes


def test_websocket_connect_and_receive_snapshot(monkeypatch):
    from app.main import app
    from app.dependencies import auth as deps_auth
    from app.repositories.user_repository import UserRow
    from app.services.auth_service import ValidSession

    # AUTH-4(#134) 부터 /ws 는 세션 쿠키가 필요하다 — 기존 계약(snapshot 수신)
    # 은 유효 세션에서 검증한다.
    async def _valid(token):
        return ValidSession(
            session_id=1,
            csrf_token="csrf",
            user=UserRow(
                {
                    "id": 1,
                    "username": "ws-user",
                    "password_hash": "",
                    "display_name": "WS",
                    "role": "viewer",
                    "is_active": True,
                    "must_change_password": False,
                }
            ),
        )

    monkeypatch.setattr(deps_auth.auth_service, "validate_session", _valid)
    client = TestClient(app)
    with client.websocket_connect("/ws", cookies={"hp015_session": "t"}) as ws:
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

    recomputed: list[str] = []

    async def _fake_recompute(reason: str):
        recomputed.append(reason)

    from app.services import evacuation_service
    monkeypatch.setattr(evacuation_service, "recompute_all", _fake_recompute)

    from app.services import alert_service
    from app.models.alert import AlertLevel, AlertTransition
    from datetime import datetime, timezone

    from app.services import alert_publisher

    class _FakePublisher:
        async def publish_transition(self, t):
            pass
    monkeypatch.setattr(alert_publisher, "_publisher", _FakePublisher())

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
    assert recomputed == ["hazard_changed"]


# ============================================================
# 이슈 #106 — snapshot이 실제 node_status/alert_events를 반영
# ============================================================

def test_snapshot_reflects_node_status_and_active_alerts(monkeypatch):
    """_send_snapshot()이 DB row를 nodes/alerts dict로 정확히 변환하는지 확인.
    수정 전에는 항상 빈 {} 라 새로고침하면 화면이 초기화됐다 (이슈 #106)."""
    from datetime import datetime, timezone
    from app.services import ws_manager

    node_row = {
        "node_id": "sensor-01",
        "battery_pct": 78,
        "wifi_rssi_dbm": -52,
        "connection_status": "online",
        "updated_at": datetime(2026, 8, 13, 12, 0, 0, tzinfo=timezone.utc),
    }
    reading_row = {
        "node_id": "sensor-02",
        "metric": "co2_ppm",
        "value": 650.0,
        "time": datetime(2026, 8, 13, 12, 0, 0, tzinfo=timezone.utc),
    }
    alert_row = {
        "source_node_id": "sensor-01",
        "alert_key": "co2_ppm",
        "level": "level1_caution",
        "trigger_value": 1100.0,
        "threshold": 1000.0,
        "activated_at": datetime(2026, 8, 13, 12, 0, 0, tzinfo=timezone.utc),
        "status": "active",
    }

    class FakeConn:
        async def fetch(self, sql, *args):
            if "FROM node_status" in sql:
                return [node_row]
            if "FROM sensor_data" in sql:
                return [reading_row]
            return [alert_row]

    class FakePool:
        class _Acquired:
            async def __aenter__(self):
                return FakeConn()

            async def __aexit__(self, *exc):
                return False

        def acquire(self):
            return self._Acquired()

    monkeypatch.setattr("app.db.get_pool", lambda: FakePool())

    sent: list[dict] = []

    class FakeWS:
        async def send_json(self, msg):
            sent.append(msg)

    import asyncio
    asyncio.run(ws_manager.manager._send_snapshot(FakeWS()))

    assert len(sent) == 1
    snapshot = sent[0]
    assert snapshot["nodes"]["sensor-01"]["battery_pct"] == 78
    assert snapshot["nodes"]["sensor-02"]["readings"]["co2_ppm"]["value"] == 650.0, (
        "node_status가 없는(gas 리딩만 온) 노드도 sensor_data 최신값으로 snapshot에 포함돼야 함"
    )
    assert snapshot["alerts"]["sensor-01:co2_ppm"]["node_id"] == "sensor-01"
    assert snapshot["alerts"]["sensor-01:co2_ppm"]["level"] == "level1_caution"


def test_snapshot_keeps_same_alert_key_active_for_two_different_nodes(monkeypatch):
    """코드리뷰 반영: sensor-01/sensor-02가 둘 다 co2_ppm active alert이면
    alert_key만으로 키를 잡던 이전 구현은 하나가 다른 하나를 덮어썼다.
    node_id:alert_key 복합 키로 두 노드가 동시에 유지되는지 확인한다."""
    from datetime import datetime, timezone
    from app.services import ws_manager

    alert_rows = [
        {
            "source_node_id": "sensor-01",
            "alert_key": "co2_ppm",
            "level": "level2_warning",
            "trigger_value": 2100.0,
            "threshold": 2000.0,
            "activated_at": datetime(2026, 8, 13, 12, 0, 0, tzinfo=timezone.utc),
            "status": "active",
        },
        {
            "source_node_id": "sensor-02",
            "alert_key": "co2_ppm",
            "level": "level1_caution",
            "trigger_value": 1100.0,
            "threshold": 1000.0,
            "activated_at": datetime(2026, 8, 13, 12, 0, 1, tzinfo=timezone.utc),
            "status": "active",
        },
    ]

    class FakeConn:
        async def fetch(self, sql, *args):
            if "FROM node_status" in sql or "FROM sensor_data" in sql:
                return []
            return alert_rows

    class FakePool:
        class _Acquired:
            async def __aenter__(self):
                return FakeConn()

            async def __aexit__(self, *exc):
                return False

        def acquire(self):
            return self._Acquired()

    monkeypatch.setattr("app.db.get_pool", lambda: FakePool())

    sent: list[dict] = []

    class FakeWS:
        async def send_json(self, msg):
            sent.append(msg)

    import asyncio
    asyncio.run(ws_manager.manager._send_snapshot(FakeWS()))

    alerts = sent[0]["alerts"]
    assert len(alerts) == 2, "두 노드의 같은 alert_key가 서로 덮어쓰지 않고 둘 다 유지돼야 함"
    assert alerts["sensor-01:co2_ppm"]["level"] == "level2_warning"
    assert alerts["sensor-02:co2_ppm"]["level"] == "level1_caution"


def test_snapshot_falls_back_to_empty_on_db_error(monkeypatch):
    """DB 조회 실패 시 연결을 끊지 않고 빈 snapshot으로 폴백."""
    from app.services import ws_manager

    def _raise():
        raise RuntimeError("DB pool is not initialized")
    monkeypatch.setattr("app.db.get_pool", _raise)

    sent: list[dict] = []

    class FakeWS:
        async def send_json(self, msg):
            sent.append(msg)

    import asyncio
    asyncio.run(ws_manager.manager._send_snapshot(FakeWS()))

    assert sent == [{"type": "snapshot", "nodes": {}, "alerts": {}}]
