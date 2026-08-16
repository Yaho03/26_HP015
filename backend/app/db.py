from typing import Optional

import asyncpg

from app.config import settings

_pool: Optional[asyncpg.Pool] = None


async def connect() -> None:
    global _pool
    _pool = await asyncpg.create_pool(settings.timescale_url, min_size=1, max_size=5)


async def disconnect() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("DB pool is not initialized. Call db.connect() first.")
    return _pool


def is_initialized() -> bool:
    return _pool is not None


async def ping() -> bool:
    """DB 가 실제로 응답하는지 확인한다 (이슈 #119).

    is_initialized() 는 풀 객체의 존재만 본다. 풀은 살아 있는데 DB 가 죽었거나
    네트워크가 끊긴 경우를 잡지 못한다. /health 가 이 왕복을 거쳐야 거짓 ok 를
    내보내지 않는다.
    """
    if _pool is None:
        return False
    try:
        async with _pool.acquire() as conn:
            await conn.execute("SELECT 1")
        return True
    except Exception:
        return False
