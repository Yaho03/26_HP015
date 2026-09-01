"""ai_anomaly_results 저장/조회.

alert_events 를 건드리지 않는다 — 이 파일에 그 테이블 이름이 나오지 않는 것이
§9.4 안전 분리의 최소 조건이다.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import List, Optional

from app.db import get_pool

# 이 시간 안에 데이터를 보낸 노드만 평가 대상으로 본다.
_ACTIVE_NODE_WINDOW = "15 minutes"


async def insert(result: dict) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO ai_anomaly_results
                (time, node_id, status, score, threshold,
                 consecutive_exceedances, top_contributors, model_version, source_mode)
            VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, $9)
            """,
            datetime.fromisoformat(result["evaluated_at"]),
            result["node_id"],
            result["status"],
            result.get("score"),
            result.get("threshold"),
            int(result.get("consecutive_exceedances") or 0),
            json.dumps(result.get("top_contributors") or [], ensure_ascii=False),
            result.get("model_version") or "unknown",
            result.get("source_mode"),
        )


async def recent_window(
    *, node_id: str, features: List[str], start: datetime, end: datetime
) -> List[dict]:
    """추론 입력. 학습 때 쓴 feature 만, 그리고 그 순서와 무관하게 long 으로 가져온다."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT time, metric, value, source_mode
            FROM sensor_data
            WHERE node_id = $1 AND metric = ANY($2::text[])
              AND time BETWEEN $3 AND $4
            ORDER BY time ASC
            """,
            node_id, features, start, end,
        )
        return [dict(r) for r in rows]


async def recent_node_ids() -> List[str]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT DISTINCT node_id
            FROM sensor_data
            WHERE time > now() - INTERVAL '{_ACTIVE_NODE_WINDOW}'
              AND node_id LIKE 'sensor-%'
            ORDER BY node_id
            """
        )
        return [r["node_id"] for r in rows]


async def latest_by_node() -> List[dict]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT ON (node_id) *
            FROM ai_anomaly_results
            ORDER BY node_id, time DESC
            """
        )
        return [_row_to_dict(r) for r in rows]


async def history(
    *, node_id: str, start: datetime, end: datetime, limit: int = 5000
) -> List[dict]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM ai_anomaly_results
            WHERE node_id = $1 AND time BETWEEN $2 AND $3
            ORDER BY time ASC
            LIMIT $4
            """,
            node_id, start, end, limit,
        )
        return [_row_to_dict(r) for r in rows]


def _row_to_dict(row) -> dict:
    contributors = row["top_contributors"]
    if isinstance(contributors, str):
        contributors = json.loads(contributors)
    return {
        "node_id": row["node_id"],
        "evaluated_at": row["time"].isoformat(),
        "status": row["status"],
        "score": row["score"],
        "threshold": row["threshold"],
        "consecutive_exceedances": row["consecutive_exceedances"],
        "top_contributors": contributors or [],
        "model_version": row["model_version"],
        "source_mode": row["source_mode"],
        "is_research_only": True,
    }
