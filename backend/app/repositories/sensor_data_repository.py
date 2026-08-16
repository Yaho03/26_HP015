"""sensor_data 시계열 조회 repository (이슈 #59)."""
from __future__ import annotations

from datetime import datetime
from typing import List

from app.db import get_pool


async def query(
    *, node_id: str, metric: str,
    start: datetime, end: datetime,
    interval: str | None = None,
    limit: int = 10_000,
) -> List[dict]:
    """interval=None: raw sensor_data. interval='1min': sensor_data_1min aggregate.

    limit 은 필수다. raw 는 노드·지표당 초당 1건이 쌓여 기간만 넓게 주면 수백만
    행이 올라온다 (이슈 #120). 상한을 SQL 에서 걸어 DB→앱 전송량부터 줄인다.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        if interval == "1min":
            rows = await conn.fetch(
                """
                SELECT bucket AS time, avg_value AS value
                FROM sensor_data_1min
                WHERE node_id = $1 AND metric = $2
                  AND bucket BETWEEN $3 AND $4
                ORDER BY bucket ASC
                LIMIT $5
                """,
                node_id, metric, start, end, limit,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT time, value
                FROM sensor_data
                WHERE node_id = $1 AND metric = $2
                  AND time BETWEEN $3 AND $4
                ORDER BY time ASC
                LIMIT $5
                """,
                node_id, metric, start, end, limit,
            )
        return [dict(r) for r in rows]
