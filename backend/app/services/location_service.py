"""위치 필터링 서비스 진입점 (이슈 #70).

ingest_telemetry 가 location metric(x_m, y_m, z_m) 을 만나면 본 서비스의
callback 을 통해 LocationFilter 로 이상치 제거 + EMA smoothing 을 적용하고,
필터링된 위치를 WebSocket 으로 대시보드에 브로드캐스트한다.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from app.config import settings
from app.services import ingest
from app.services.location_filter import FilteredPosition, LocationFilter
from app.services.ws_manager import manager

logger = logging.getLogger(__name__)

_filter = LocationFilter(
    alpha=settings.location_filter_alpha,
    max_speed_mps=settings.location_filter_max_speed_mps,
    reject_limit=settings.location_filter_reject_limit,
)
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
    """필터링된 위치를 브로드캐스트한다.

    실측 좌표(position_raw)와 그 좌표계만 보낸다. 화면 표시 좌표는 보내지 않는다 —
    뷰마다 매핑 프리셋이 다르므로(모니터링=FILL, 트윈 상세=TRUE SCALE) 백엔드가
    어느 하나를 고를 수 없다. 변환은 프론트 utils/coordinates 가 담당한다.

    x/y/z 는 구버전 클라이언트 호환용으로 유지한다.
    """
    try:
        import asyncio
        await manager.broadcast({
            "type": "location",
            "node_id": pos.node_id,
            "x": pos.x,
            "y": pos.y,
            "z": pos.z,
            "position_raw": {"x_m": pos.x, "y_m": pos.y, "z_m": pos.z},
            "source_coordinate_system": settings.location_source_coordinate_system,
            "timestamp": pos.timestamp.isoformat(),
        })
    except Exception:
        logger.exception("ws broadcast failed for location (node=%s)", pos.node_id)


def get_filter() -> LocationFilter:
    return _filter
