"""정상 센서 값 / 노드 상태 WebSocket 브로드캐스트 (이슈 #106).

경보가 없는 평상시에도 대시보드가 실시간 값을 받을 수 있도록,
ingest.py 의 reading/status 콜백을 통해 매 저장 후 브로드캐스트한다.
가스/환경 센서는 1Hz로 들어오므로 클라이언트 부담을 줄이기 위해
(node_id, metric)별로 1초에 한 번만 전송한다.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Dict, Tuple

from app.services import ingest
from app.services.ws_manager import manager

logger = logging.getLogger(__name__)

_THROTTLE_SECONDS = 1.0
_last_sent: Dict[Tuple[str, str], float] = {}
_callback_registered = False


def init() -> None:
    global _callback_registered
    if _callback_registered:
        return
    ingest.set_reading_callback(_on_reading_ingested)
    ingest.set_status_callback(_on_status_ingested)
    ingest.set_connection_callback(_on_connection_ingested)
    _callback_registered = True


def _throttled(node_id: str, metric: str) -> bool:
    key = (node_id, metric)
    now = time.monotonic()
    last = _last_sent.get(key)
    if last is not None and (now - last) < _THROTTLE_SECONDS:
        return True
    _last_sent[key] = now
    return False


async def _on_reading_ingested(
    node_id: str, metric: str, value: float, sampled_at: datetime
) -> None:
    if _throttled(node_id, metric):
        return
    await manager.broadcast({
        "type": "sensor_reading",
        "node_id": node_id,
        "metric": metric,
        "value": value,
        "timestamp": sampled_at.isoformat(),
    })


async def _on_status_ingested(node_id: str, data: dict, sampled_at: datetime) -> None:
    await manager.broadcast({
        "type": "node_status",
        "node_id": node_id,
        "battery_pct": data["battery_pct"],
        "wifi_rssi_dbm": data["wifi_rssi_dbm"],
        "sensors_online": data["sensors_online"],
        "sensors_error": data["sensors_error"],
        "timestamp": sampled_at.isoformat(),
    })


async def _on_connection_ingested(node_id: str, status: str, timestamp: datetime) -> None:
    await manager.broadcast({
        "type": "node_connection",
        "node_id": node_id,
        "connection_status": status,
        "timestamp": timestamp.isoformat(),
    })
