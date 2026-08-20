"""sensor-data 쿼리 통합 테스트 — 실제 DB (이슈 #124).

SQL 문법과 파라미터 순서는 mock 으로 검증되지 않는다. #120 에서 LIMIT $5 를
추가했는데, 파라미터 번호가 하나만 어긋나도 단위 테스트는 통과하고 런타임에
터진다.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.repositories import sensor_data_repository

NODE = "sensor-integration-query"
METRIC = "co2_ppm"


@pytest.fixture
async def seeded(db_pool):
    """1초 간격 표본 50건을 넣는다."""
    base = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)
    async with db_pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM sensor_data WHERE node_id = $1", NODE
        )
        await conn.executemany(
            """
            INSERT INTO sensor_data (time, node_id, metric, value, message_id)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT DO NOTHING
            """,
            [
                (base + timedelta(seconds=i), NODE, METRIC, 500.0 + i, f"itest-{i:04d}")
                for i in range(50)
            ],
        )
    yield base
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM sensor_data WHERE node_id = $1", NODE)


@pytest.mark.asyncio
async def test_query_returns_rows_in_time_order(seeded):
    rows = await sensor_data_repository.query(
        node_id=NODE, metric=METRIC,
        start=seeded, end=seeded + timedelta(hours=1),
        limit=100,
    )
    assert len(rows) == 50
    times = [r["time"] for r in rows]
    assert times == sorted(times), "시간 순서가 아니다"


@pytest.mark.asyncio
async def test_limit_is_actually_applied_in_sql(seeded):
    """★ LIMIT 이 SQL 에 실제로 걸리는지. 파라미터 번호가 어긋나면 여기서 터진다."""
    rows = await sensor_data_repository.query(
        node_id=NODE, metric=METRIC,
        start=seeded, end=seeded + timedelta(hours=1),
        limit=10,
    )
    assert len(rows) == 10


@pytest.mark.asyncio
async def test_range_filter_excludes_outside_rows(seeded):
    rows = await sensor_data_repository.query(
        node_id=NODE, metric=METRIC,
        start=seeded, end=seeded + timedelta(seconds=9),
        limit=100,
    )
    assert len(rows) == 10


@pytest.mark.asyncio
async def test_other_node_is_not_returned(seeded):
    rows = await sensor_data_repository.query(
        node_id="sensor-does-not-exist", metric=METRIC,
        start=seeded, end=seeded + timedelta(hours=1),
        limit=100,
    )
    assert rows == []


@pytest.mark.asyncio
async def test_aggregate_path_runs(seeded):
    """1min 집계 경로도 SQL 이 유효한지 확인한다. 연속 집계가 아직 채워지지
    않았을 수 있으므로 행 수가 아니라 '터지지 않는 것' 을 본다."""
    rows = await sensor_data_repository.query(
        node_id=NODE, metric=METRIC,
        start=seeded, end=seeded + timedelta(hours=1),
        interval="1min", limit=100,
    )
    assert isinstance(rows, list)
