"""location WebSocket 페이로드 계약 검증.

05_DIGITAL_TWIN_SPEC 3.1 — 실측 좌표와 화면 표시 좌표를 같은 이름으로 보내지 않는다.
백엔드는 실측값(position_raw)과 그 좌표계만 보내고, 비율 매핑은 프론트가 뷰별로 한다.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.services import location_service
from app.services.location_filter import FilteredPosition


def _capture(monkeypatch) -> list:
    sent: list = []

    async def fake_broadcast(message):
        sent.append(message)

    monkeypatch.setattr(location_service.manager, "broadcast", fake_broadcast)
    return sent


def _position() -> FilteredPosition:
    return FilteredPosition(
        node_id="wearable-01",
        x=1.2,
        y=0.8,
        z=0.0,
        timestamp=datetime(2026, 8, 16, 3, 0, 0, tzinfo=timezone.utc),
    )


@pytest.mark.asyncio
async def test_broadcast_includes_position_raw(monkeypatch):
    sent = _capture(monkeypatch)
    await location_service._broadcast(_position())
    assert sent[0]["position_raw"] == {"x_m": 1.2, "y_m": 0.8, "z_m": 0.0}


@pytest.mark.asyncio
async def test_broadcast_declares_source_coordinate_system(monkeypatch):
    sent = _capture(monkeypatch)
    await location_service._broadcast(_position())
    assert sent[0]["source_coordinate_system"] == "demo-local"


@pytest.mark.asyncio
async def test_broadcast_keeps_legacy_xyz_for_compatibility(monkeypatch):
    sent = _capture(monkeypatch)
    await location_service._broadcast(_position())
    msg = sent[0]
    assert (msg["x"], msg["y"], msg["z"]) == (1.2, 0.8, 0.0)


@pytest.mark.asyncio
async def test_broadcast_does_not_send_display_coordinates(monkeypatch):
    """표시 좌표를 백엔드가 정하면 뷰마다 다른 매핑을 쓸 수 없다."""
    sent = _capture(monkeypatch)
    await location_service._broadcast(_position())
    assert "position" not in sent[0]
    assert "position_display" not in sent[0]


@pytest.mark.asyncio
async def test_source_coordinate_system_is_configurable(monkeypatch):
    """실제 선박 좌표를 직접 수신하면 ship-visual 로 선언해 중복 변환을 막는다."""
    monkeypatch.setattr(
        location_service.settings, "location_source_coordinate_system", "ship-visual"
    )
    sent = _capture(monkeypatch)
    await location_service._broadcast(_position())
    assert sent[0]["source_coordinate_system"] == "ship-visual"
