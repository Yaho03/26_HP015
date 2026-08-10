"""processed_messages retention (이슈 #97).

raw sensor_data 의 TimescaleDB retention(30일)와 동일 기간으로 processed_messages
dedup 테이블을 정리한다. FR-101 SHOULD 노드 버퍼링(최대 100건, 짧은 시간 내 재전송)
전제하에 30일보다 오래된 메시지는 올 일이 없으므로 dedup 정확성을 잃지 않는다.

raw sensor_data 가 이미 30일 후 삭제되므로, 30일 이상된 message_id 로 들어온 메시지는
raw 데이터도 없어 어차피 의미 있는 처리가 불가능 → 안전하게 삭제.

정리 방식: hypertable retention policy 대신 1시간 간격 백그라운드 DELETE.
이유: processed_messages.PK(message_id) 가 partition key(time)를 포함하지 않아
hypertable 로 전환하려면 PK 재정의가 필요 (마이그레이션 복잡도 ↑).
단순 테이블 + 인덱스 스캔 DELETE 가 더 가볍다.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from app.db import get_pool

logger = logging.getLogger(__name__)

RETENTION_DAYS = 30
CLEANUP_INTERVAL_SECONDS = 3600  # 1시간

_task: Optional[asyncio.Task] = None


async def cleanup_processed_messages() -> int:
    """30일 이상된 processed_messages 행을 삭제하고 삭제된 행 수를 반환한다."""
    pool = get_pool()
    async with pool.acquire() as conn:
        status = await conn.execute(
            """
            DELETE FROM processed_messages
            WHERE received_at < now() - make_interval(days => $1)
            """,
            RETENTION_DAYS,
        )
        # asyncpg status 형식: "DELETE N"
        try:
            deleted = int(status.split()[1])
        except (IndexError, ValueError):
            deleted = 0
        if deleted > 0:
            logger.info(
                "processed_messages retention cleanup: deleted %d rows older than %d days",
                deleted, RETENTION_DAYS,
            )
        return deleted


async def _loop() -> None:
    """CLEANUP_INTERVAL_SECONDS 마다 cleanup 실행. 시작 시 즉시 1회 실행."""
    while True:
        try:
            await cleanup_processed_messages()
        except Exception:
            logger.exception("processed_messages cleanup failed (will retry next tick)")
        await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)


async def start() -> None:
    """백그라운드 cleanup task 예약. 중복 시작 방지."""
    global _task
    if _task is not None and not _task.done():
        return
    _task = asyncio.create_task(_loop())
    logger.info(
        "processed_messages retention task started (interval=%ds, retention=%ddays)",
        CLEANUP_INTERVAL_SECONDS, RETENTION_DAYS,
    )


async def stop() -> None:
    """백그라운드 task 취소."""
    global _task
    if _task is not None:
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
        _task = None
