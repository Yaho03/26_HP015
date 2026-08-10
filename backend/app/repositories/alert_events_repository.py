"""alert_events 로그 조회 repository (이슈 #60)."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from app.db import get_pool


async def query(
    *,
    node_id: Optional[str] = None,
    alert_key: Optional[str] = None,
    status: Optional[str] = None,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    limit: int = 100,
) -> List[dict]:
    pool = get_pool()
    conditions = []
    args: list = []
    idx = 1

    if node_id:
        conditions.append(f"source_node_id = ${idx}")
        args.append(node_id)
        idx += 1
    if alert_key:
        conditions.append(f"alert_key = ${idx}")
        args.append(alert_key)
        idx += 1
    if status:
        conditions.append(f"status = ${idx}")
        args.append(status)
        idx += 1
    if start:
        conditions.append(f"activated_at >= ${idx}")
        args.append(start)
        idx += 1
    if end:
        conditions.append(f"activated_at <= ${idx}")
        args.append(end)
        idx += 1

    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    args.append(limit)

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT message_id, alert_id, source_node_id, alert_key, alert_type,
                   level, trigger_value, threshold, metric, message, status,
                   schema_version, activated_at, resolved_at, published_at
            FROM alert_events
            {where_clause}
            ORDER BY activated_at DESC
            LIMIT ${idx}
            """,
            *args,
        )
        return [dict(r) for r in rows]
