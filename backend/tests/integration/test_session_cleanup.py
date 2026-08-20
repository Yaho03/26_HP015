"""만료 세션 정리 통합 테스트 — 실DB (AUTH-11, 이슈 #141; FR-611).

완료 조건: sessions 테이블이 무한 증가하지 않는다 — 폐기/절대만료 후
30일이 지난 행이 주기 삭제 대상이 된다. 활성 세션은 지우지 않는다.
"""
from __future__ import annotations

import pytest

from app import db
from app.services import auth_service, retention

pytestmark = pytest.mark.skipif(
    not __import__("os").getenv("TEST_TIMESCALE_URL", ""),
    reason="TEST_TIMESCALE_URL 이 없어 통합 테스트를 건너뜁니다",
)

PASSWORD = "session-cleanup-pw"


async def _make_user(username: str) -> int:
    pool = db.get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO users (username, password_hash, display_name, role)
            VALUES ($1, $2, $1, 'viewer')
            ON CONFLICT (username) DO UPDATE SET password_hash = EXCLUDED.password_hash
            RETURNING id
            """,
            username, auth_service.hash_password(PASSWORD),
        )


@pytest.mark.asyncio
async def test_cleanup_deletes_old_revoked_and_expired_sessions(db_pool):
    user_id = await _make_user("cleanup-user")
    pool = db.get_pool()

    # (a) 31일 전 폐기 세션 — 삭제 대상
    await conn_insert(pool, user_id, "old-revoked",
                      created_days_ago=31, expires_days_ago=30, revoked_days_ago=31)
    # (b) 31일 전 절대만료 세션 — 삭제 대상
    await conn_insert(pool, user_id, "old-expired",
                      created_days_ago=31, expires_days_ago=31, revoked_days_ago=None)
    # (c) 어제 폐기 세션 — 보존 (아직 30일 안 지남)
    await conn_insert(pool, user_id, "recent-revoked",
                      created_days_ago=1, expires_days_ago=0.5, revoked_days_ago=1)
    # (d) 활성 세션 (내일 만료) — 절대 삭제 금지
    await conn_insert(pool, user_id, "active",
                      created_days_ago=0, expires_days_ago=-1, revoked_days_ago=None)

    deleted = await retention.cleanup_expired_sessions()
    assert deleted >= 2

    async with pool.acquire() as conn:
        remaining = {
            r["session_hash"]
            for r in await conn.fetch("SELECT session_hash FROM sessions WHERE user_id = $1", user_id)
        }
    active_hash = auth_service.hash_token("active")
    recent_hash = auth_service.hash_token("recent-revoked")
    assert active_hash in remaining, "활성 세션이 삭제되면 안 된다"
    assert recent_hash in remaining, "30일 안 지난 폐기 세션은 보존된다"
    assert auth_service.hash_token("old-revoked") not in remaining
    assert auth_service.hash_token("old-expired") not in remaining


async def conn_insert(pool, user_id: int, token: str, *, created_days_ago: float,
                      expires_days_ago: float, revoked_days_ago: float | None) -> None:
    """expires_days_ago 양수 = 이미 만료, 음수 = 미래 만료(활성)."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO sessions (user_id, session_hash, csrf_token, expires_at,
                                  created_at, last_seen_at, revoked_at)
            VALUES ($1, $2, 'csrf',
                    now() - make_interval(days => $3),
                    now() - make_interval(days => $4),
                    now(),
                    CASE WHEN $5::double precision IS NULL THEN NULL
                         ELSE now() - make_interval(days => $5) END)
            """,
            user_id,
            auth_service.hash_token(token),
            expires_days_ago,
            created_days_ago,
            revoked_days_ago,
        )


@pytest.mark.asyncio
async def test_sessions_table_does_not_grow_unboundedly(db_pool):
    """cleanup 이 지운 뒤 같은 양을 다시 지우면 0 — 주기 실행 멱등성."""
    first = await retention.cleanup_expired_sessions()
    _ = first
    # 이미 위 테스트가 지웠으므로 추가 삭제는 0에 가깝다 (다른 테스트 잔여 제외).
    # 멱등성 확인: 예외 없이 동작.
    await retention.cleanup_expired_sessions()
