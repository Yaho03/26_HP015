"""WebSocket 엔드포인트 (이슈 #58)."""
from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.ws_manager import manager

router = APIRouter(tags=["websocket"])


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await manager.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(ws)
