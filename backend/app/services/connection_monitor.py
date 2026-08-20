"""노드 연결 상태 관리 — 30초 timeout 감지 (이슈 #52).

04_DATA_CONTRACT.md 섹션 5.2 (오프라인 판정):
1. LWT 메시지 수신 (status: offline, reason: lwt) — ingest_connection 에서 처리
2. 30초 이상 데이터 수신 없음 → 백엔드가 reason: timeout 으로 offline 판정 — 본 모듈

동작:
- 1초마다 node_status 를 스캔해 backend_received_at > 30초 경과한 online 노드를 offline 으로 전환
- timeout 발생 시 connection_lost alert_key 로 alert_service.transition 호출
  (status: online → offline 을 AlertLevel.NORMAL→LEVEL3 로 매핑 — safety-critical)
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from app.db import get_pool

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 30
CHECK_INTERVAL_SECONDS = 1

_task: Optional[asyncio.Task] = None
_callback_registered = False


def init() -> None:
    """ingest.set_connection_recovery_callback 등록 (이슈 #111) — 노드가
    offline→online으로 복귀하면 connection_lost 경보를 해제한다."""
    global _callback_registered
    if _callback_registered:
        return
    from app.services import ingest
    ingest.set_connection_recovery_callback(_emit_connection_recovered)
    _callback_registered = True


async def check_timeouts() -> int:
    """30초 이상 backend_received_at 과거인 online 노드를 offline 으로 표시하고
    connection_lost 경보를 발생시킨다. 처리된 노드 수 반환."""
    pool = get_pool()
    stale_count = 0
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT node_id, connection_status FROM node_status
            WHERE connection_status = 'online'
              AND backend_received_at IS NOT NULL
              AND backend_received_at < now() - make_interval(secs => $1)
            """,
            TIMEOUT_SECONDS,
        )
        if not rows:
            return 0
        for row in rows:
            node_id = row["node_id"]
            async with conn.transaction():
                await conn.execute(
                    """
                    UPDATE node_status
                    SET connection_status     = 'offline',
                        connection_reason      = 'timeout',
                        connection_updated_at  = now(),
                        backend_received_at    = now()
                    WHERE node_id = $1 AND connection_status = 'online'
                    """,
                    node_id,
                )
            await _emit_connection_lost(node_id)
            stale_count += 1
    return stale_count


async def _emit_connection_lost(node_id: str) -> None:
    """connection_lost alert 발생. alert_service 를 통해 publisher 로 연결."""
    try:
        from datetime import datetime, timezone
        from app.models.alert import AlertLevel, AlertTransition
        from app.services import alert_service
        transition = AlertTransition(
            node_id=node_id,
            metric="connection_lost",
            from_level=AlertLevel.NORMAL,
            to_level=AlertLevel.LEVEL3,
            value=0.0,
            threshold=0.0,
            timestamp=datetime.now(timezone.utc),
        )
        await alert_service.handle_transition(transition)
    except Exception:
        logger.exception("failed to emit connection_lost alert for %s", node_id)


async def _emit_connection_recovered(node_id: str) -> None:
    """connection_lost 경보 해제 (이슈 #111). 노드가 offline→online으로 복귀하면
    ingest.py의 콜백을 통해 호출된다. _emit_connection_lost의 반대 방향 —
    이게 없으면 노드가 복귀해도 경보가 active_alert_ids에 영구 잔류하고
    alerts/state/{node}/connection_lost retain 메시지가 고착된다."""
    try:
        from datetime import datetime, timezone
        from app.models.alert import AlertLevel, AlertTransition
        from app.services import alert_service
        transition = AlertTransition(
            node_id=node_id,
            metric="connection_lost",
            from_level=AlertLevel.LEVEL3,
            to_level=AlertLevel.NORMAL,
            value=0.0,
            threshold=0.0,
            timestamp=datetime.now(timezone.utc),
        )
        await alert_service.handle_transition(transition)
    except Exception:
        logger.exception("failed to emit connection_recovered for %s", node_id)


async def _loop() -> None:
    while True:
        try:
            await check_timeouts()
        except Exception:
            logger.exception("connection timeout check failed")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


async def start() -> None:
    global _task
    if _task is not None and not _task.done():
        return
    _task = asyncio.create_task(_loop())
    logger.info("connection monitor started (timeout=%ds)", TIMEOUT_SECONDS)


async def stop() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
        _task = None
