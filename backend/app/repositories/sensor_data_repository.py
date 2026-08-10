"""sensor_data 시계열 조회 repository (이슈 #59)."""
from __future__ import annotations

from datetime import datetime
from typing import List

from app.db import get_pool


async def query(
    *, node_id: str, metric: str,
    start: datetime, end: datetime,
    interval: str | None = None,
) -> List[dict]:
    """interval=None: raw sensor_data. interval='1min': sensor_data_1min aggregate."""
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
                """,
                node_id, metric, start, end,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT time, value
                FROM sensor_data
                WHERE node_id = $1 AND metric = $2
                  AND time BETWEEN $3 AND $4
                ORDER BY time ASC
                """,
                node_id, metric, start, end,
            )
        return [dict(r) for r in rows]
