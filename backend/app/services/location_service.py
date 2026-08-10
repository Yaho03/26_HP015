"""위치 필터링 서비스 진입점 (이슈 #70).

ingest_telemetry 가 location metric(x_m, y_m, z_m) 을 만나면 본 서비스의
callback 을 통해 LocationFilter 로 이상치 제거 + EMA smoothing 을 적용하고,
필터링된 위치를 WebSocket 으로 대시보드에 브로드캐스트한다.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from app.services import ingest
from app.services.location_filter import FilteredPosition, LocationFilter
from app.services.ws_manager import manager

logger = logging.getLogger(__name__)

_filter = LocationFilter(alpha=0.3, max_jump_m=1.0)
_callback_registered = False


def init() -> None:
    global _callback_registered
    if _callback_registered:
        return
    ingest.set_location_callback(_on_location_ingested)
    _callback_registered = True


async def _on_location_ingested(
    node_id: str,
    x: float,
    y: float,
    z: float,
    sampled_at: datetime,
) -> None:
    filtered = _filter.update(node_id, x, y, z, sampled_at)
    if filtered is None:
        return
    await _broadcast(filtered)


async def _broadcast(pos: FilteredPosition) -> None:
    try:
        import asyncio
        await manager.broadcast({
            "type": "location",
            "node_id": pos.node_id,
            "x": pos.x,
            "y": pos.y,
            "z": pos.z,
            "timestamp": pos.timestamp.isoformat(),
        })
    except Exception:
        logger.exception("ws broadcast failed for location (node=%s)", pos.node_id)


def get_filter() -> LocationFilter:
    return _filter
