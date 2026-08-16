"""실제 DB 를 쓰는 통합 테스트 기반 (이슈 #124).

단위 테스트는 DB 를 전부 mock 한다. 그래서 SQL 문법 오류, 타입 바인딩 불일치,
제약 조건 위반처럼 **경계면에서만 드러나는 결함**을 하나도 걸러내지 못한다.
P0 6건 중 5건이 이 사각지대에서 나왔다. #102(TIMESTAMPTZ 에 str 바인딩)가
대표적이다 — 단위 테스트는 전부 통과했는데 경보 저장이 통째로 실패했다.

여기서는 mock 을 쓰지 않는다. 진짜 DB 에 붙어 마이그레이션을 적용하고 쿼리한다.

실행:
    TEST_TIMESCALE_URL=postgresql://hp015:hp015_dev_pw@localhost:5432/hp015_test \\
      pytest tests/integration -v

TEST_TIMESCALE_URL 이 없으면 통째로 skip 한다 — DB 없이도 단위 테스트는 돌아야 한다.
"""
from __future__ import annotations

import os

import asyncpg
import pytest
import pytest_asyncio

TEST_DB_URL = os.getenv("TEST_TIMESCALE_URL", "")

pytestmark = pytest.mark.skipif(
    not TEST_DB_URL,
    reason="TEST_TIMESCALE_URL 이 없어 통합 테스트를 건너뜁니다",
)


def pytest_collection_modifyitems(items):
    """DB 가 없으면 이 디렉터리 전체를 skip 한다."""
    if TEST_DB_URL:
        return
    skip = pytest.mark.skip(reason="TEST_TIMESCALE_URL 미설정")
    for item in items:
        item.add_marker(skip)


@pytest_asyncio.fixture
async def db_pool():
    """테스트마다 풀을 열고 마이그레이션을 적용한다.

    세션 스코프로 두면 pytest-asyncio 의 함수 스코프 이벤트 루프와 충돌한다.
    마이그레이션은 멱등이라 반복 적용해도 비용이 크지 않다.

    마이그레이션 적용 자체가 검증이다 — SQL 문법 오류나 순서 문제가 여기서 터진다.
    """
    if not TEST_DB_URL:
        pytest.skip("TEST_TIMESCALE_URL 미설정")

    from app import db
    from app.config import settings

    settings.timescale_url = TEST_DB_URL
    await db.connect()
    try:
        from app import migration_runner

        await migration_runner.apply_all()
        yield db.get_pool()
    finally:
        await db.disconnect()


@pytest_asyncio.fixture
async def conn(db_pool):
    """테스트마다 트랜잭션을 열고 끝나면 되돌린다.

    테스트끼리 데이터가 새지 않게 한다. 커밋하지 않으므로 뒷정리가 필요 없다.
    """
    async with db_pool.acquire() as connection:
        tx = connection.transaction()
        await tx.start()
        try:
            yield connection
        finally:
            await tx.rollback()


@pytest.fixture
def node_id() -> str:
    return "sensor-01"
