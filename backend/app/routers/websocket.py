"""WebSocket 엔드포인트 (이슈 #58, #122, #134)."""
from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.dependencies.auth import authenticate_ws
from app.services.ws_manager import manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])

# Policy Violation — 세션 없음/만료. 프론트는 이 코드를 보고 재연결하지 않고
# 로그인 상태 갱신으로 전환한다 (AUTH-4). 1008이 아닌 close(네트워크 끊김 등)만
# 지수 백오프로 재연결한다.
WS_CLOSE_POLICY_VIOLATION = 1008


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    # accept() 이전에 인증한다. 실패해도 accept 후 즉시 close(1008) 하는 이유:
    # 핸드셰이크를 거부(403)하면 브라우저는 close code 를 못 보고, 프론트가
    # '세션 만료'와 '서버 장애'를 구분할 수 없다. 1008 을 전달해야 재연결
    # 폭주를 막는다. 어떤 경로든 데이터는 1바이트도 나가지 않는다.
    user = await authenticate_ws(ws)
    if user is None:
        await ws.accept()
        await ws.close(code=WS_CLOSE_POLICY_VIOLATION)
        return
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
