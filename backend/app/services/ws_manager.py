"""WebSocket connection manager (이슈 #58).

연결된 대시보드 클라이언트들에게 alert 이벤트/노드 상태 변화를 브로드캐스트한다.
연결 시 현재 활성 alert + 노드 상태 snapshot 을 먼저 전송한다.
"""
from __future__ import annotations

import logging
from typing import Set

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        self._clients: Set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.add(ws)
        await self._send_snapshot(ws)
        logger.info("ws client connected (total=%d)", len(self._clients))

    def disconnect(self, ws: WebSocket) -> None:
        self._clients.discard(ws)
        logger.info("ws client disconnected (total=%d)", len(self._clients))

    async def _send_snapshot(self, ws: WebSocket) -> None:
        await ws.send_json({"type": "snapshot", "nodes": {}, "alerts": {}})

    async def broadcast(self, message: dict) -> None:
        dead: list[WebSocket] = []
        for ws in list(self._clients):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._clients.discard(ws)


manager = ConnectionManager()
