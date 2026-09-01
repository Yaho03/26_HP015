"""이슈 #106: 정상 센서 값 / 노드 상태 WebSocket 브로드캐스트 — TDD 테스트."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest


def test_module_importable():
    from app.services import sensor_broadcast
    assert hasattr(sensor_broadcast, "init")


@pytest.mark.asyncio
async def test_reading_ingested_broadcasts_sensor_reading(monkeypatch):
    from app.services import sensor_broadcast

    sent: list[dict] = []

    async def _fake_broadcast(msg):
        sent.append(msg)
    monkeypatch.setattr(sensor_broadcast.manager, "broadcast", _fake_broadcast)
    sensor_broadcast._last_sent.clear()

    ts = datetime(2026, 8, 13, 12, 0, 0, tzinfo=timezone.utc)
    await sensor_broadcast._on_reading_ingested("sensor-01", "co2_ppm", 612.0, ts)

    assert len(sent) == 1
    assert sent[0] == {
        "type": "sensor_reading",
        "node_id": "sensor-01",
        "metric": "co2_ppm",
        "value": 612.0,
        "timestamp": ts.isoformat(),
    }


@pytest.mark.asyncio
async def test_reading_throttled_within_one_second(monkeypatch):
    """같은 (node_id, metric)은 1초 내 재전송하지 않는다 (가스 1Hz 대비 클라이언트 부담 완화)."""
    from app.services import sensor_broadcast

    sent: list[dict] = []

    async def _fake_broadcast(msg):
        sent.append(msg)
    monkeypatch.setattr(sensor_broadcast.manager, "broadcast", _fake_broadcast)
    sensor_broadcast._last_sent.clear()

    ts = datetime.now(timezone.utc)
    await sensor_broadcast._on_reading_ingested("sensor-01", "co2_ppm", 600.0, ts)
    await sensor_broadcast._on_reading_ingested("sensor-01", "co2_ppm", 601.0, ts)
    await sensor_broadcast._on_reading_ingested("sensor-01", "temperature_c", 24.5, ts)

    assert len(sent) == 2, "같은 metric 연속 호출은 1건만, 다른 metric은 별도로 통과"
    metrics_sent = {m["metric"] for m in sent}
    assert metrics_sent == {"co2_ppm", "temperature_c"}


@pytest.mark.asyncio
async def test_status_ingested_broadcasts_node_status(monkeypatch):
    from app.services import sensor_broadcast

    sent: list[dict] = []

    async def _fake_broadcast(msg):
        sent.append(msg)
    monkeypatch.setattr(sensor_broadcast.manager, "broadcast", _fake_broadcast)

    ts = datetime(2026, 8, 13, 12, 0, 0, tzinfo=timezone.utc)
    await sensor_broadcast._on_status_ingested(
        "sensor-01",
        {
            "battery_pct": 78,
            "wifi_rssi_dbm": -52,
            "sensors_online": ["mh-z19b"],
            "sensors_error": [],
        },
        ts,
    )

    assert len(sent) == 1
    assert sent[0]["type"] == "node_status"
    assert sent[0]["node_id"] == "sensor-01"
    assert sent[0]["battery_pct"] == 78


@pytest.mark.asyncio
async def test_connection_ingested_broadcasts_live_connection_state(monkeypatch):
    from app.services import sensor_broadcast

    sent: list[dict] = []

    async def _fake_broadcast(msg):
        sent.append(msg)
    monkeypatch.setattr(sensor_broadcast.manager, "broadcast", _fake_broadcast)

    ts = datetime(2026, 8, 13, 12, 0, 0, tzinfo=timezone.utc)
    await sensor_broadcast._on_connection_ingested("sensor-01", "online", ts)

    assert sent == [{
        "type": "node_connection",
        "node_id": "sensor-01",
        "connection_status": "online",
        "timestamp": ts.isoformat(),
    }]


def test_init_registers_callbacks_with_ingest(monkeypatch):
    from app.services import sensor_broadcast, ingest

    monkeypatch.setattr(sensor_broadcast, "_callback_registered", False)
    monkeypatch.setattr(ingest, "_reading_callback", None)
    monkeypatch.setattr(ingest, "_status_callback", None)
    monkeypatch.setattr(ingest, "_connection_callback", None)

    sensor_broadcast.init()

    assert ingest._reading_callback is sensor_broadcast._on_reading_ingested
    assert ingest._status_callback is sensor_broadcast._on_status_ingested
    assert ingest._connection_callback is sensor_broadcast._on_connection_ingested


def test_init_is_idempotent(monkeypatch):
    from app.services import sensor_broadcast, ingest

    monkeypatch.setattr(sensor_broadcast, "_callback_registered", False)
    calls = []
    monkeypatch.setattr(ingest, "set_reading_callback", lambda cb: calls.append(cb))
    monkeypatch.setattr(ingest, "set_status_callback", lambda cb: calls.append(cb))
    monkeypatch.setattr(ingest, "set_connection_callback", lambda cb: calls.append(cb))

    sensor_broadcast.init()
    sensor_broadcast.init()

    assert len(calls) == 3, "두 번째 init()은 콜백을 재등록하지 않음"
