from typing import Optional

import asyncpg

from app.config import settings

_pool: Optional[asyncpg.Pool] = None


async def connect() -> None:
    """커넥션 풀을 만든다.

    TIMESCALE_URL 이 비어 있으면 여기서 실패한다 (이슈 #128). 빈 값으로 두면
    asyncpg 가 기본값으로 접속을 시도해 엉뚱한 DB 에 붙거나, 애매한 오류를 낸다.
    설정 클래스의 필수 필드로 올리지 않은 이유는 import 시점에 터져 테스트까지
    막히기 때문이다. 기동 시점에 확인하는 편이 안전하다.
    """
    global _pool
    if not settings.timescale_url:
        raise RuntimeError(
            "TIMESCALE_URL 이 설정되지 않았습니다. backend/.env 를 확인하세요 "
            "(.env.example 참고)."
        )
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
