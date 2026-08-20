"""WebSocket 엔드포인트 (이슈 #58, #122)."""
from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.ws_manager import manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await manager.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        # WebSocketDisconnect 만 잡으면 그 외 예외(끊어진 소켓의 RuntimeError 등)
        # 에서 연결 해제가 실행되지 않아 목록에 영원히 남는다. 그러면 이후 모든
        # 브로드캐스트가 그 소켓에 대해 실패한다 (이슈 #122).
        logger.exception("ws connection ended with an unexpected error")
    finally:
        manager.disconnect(ws)
