"""thresholds DB 액세스 계층 (이슈 #53).

repository 패턴으로 분리해 비즈니스 로직을 HTTP 라우터와 DB 에서 분리.
FakePool 주입이 가능해 단위 테스트가 DB 없이 동작한다.
"""
from __future__ import annotations

from typing import List

from app.db import get_pool
from app.models.threshold import Threshold


async def list_all() -> List[Threshold]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT metric, level, direction, enter_threshold, exit_threshold,
                   enter_for_ms, exit_for_ms, updated_at
            FROM thresholds
            ORDER BY metric, level
            """
        )
        return [Threshold(**dict(r)) for r in rows]


async def list_by_metric(metric: str) -> List[Threshold]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT metric, level, direction, enter_threshold, exit_threshold,
                   enter_for_ms, exit_for_ms, updated_at
            FROM thresholds
            WHERE metric = $1
            ORDER BY level
            """,
            metric,
        )
        return [Threshold(**dict(r)) for r in rows]


async def upsert(threshold: Threshold) -> Threshold:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO thresholds (metric, level, direction, enter_threshold,
                                     exit_threshold, enter_for_ms, exit_for_ms, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, now())
            ON CONFLICT (metric, level) DO UPDATE SET
                direction       = EXCLUDED.direction,
                enter_threshold = EXCLUDED.enter_threshold,
                exit_threshold  = EXCLUDED.exit_threshold,
                enter_for_ms    = EXCLUDED.enter_for_ms,
                exit_for_ms     = EXCLUDED.exit_for_ms,
                updated_at      = now()
            """,
            threshold.metric,
            threshold.level.value,
            threshold.direction.value,
            threshold.enter_threshold,
            threshold.exit_threshold,
            threshold.enter_for_ms,
            threshold.exit_for_ms,
        )
        return threshold
