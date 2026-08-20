"""사용자·세션 DB 액세스 (AUTH-2, 이슈 #132).

user_repository 는 저장/조회만 담당한다. 해싱·만료 판정·폐기 정책은
auth_service 이 가진다 (비밀번호 검증은 DB 와 무관한 순수 계산이라
서비스 계층에서 먼저 한다 — 계정 열거 방지 타이밍 마스킹 참조).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from app.db import get_pool
from app.models.user import UserOut

_USER_COLUMNS = "id, username, display_name, role, is_active, must_change_password"


class UserRow:
    """DB 행 전체(password_hash 포함). 서비스 계층 내부에서만 쓴다."""

    def __init__(self, record: dict) -> None:
        self.id: int = record["id"]
        self.username: str = record["username"]
        self.password_hash: str = record["password_hash"]
        self.display_name: str = record["display_name"]
        self.role: str = record["role"]
        self.is_active: bool = record["is_active"]
        self.must_change_password: bool = record["must_change_password"]

    def to_out(self) -> UserOut:
        """응답 모델로 변환 — 여기서 해시가 영원히 떨어져 나간다."""
        return UserOut(
            id=self.id,
            username=self.username,
            display_name=self.display_name,
            role=self.role,
            is_active=self.is_active,
            must_change_password=self.must_change_password,
        )


async def get_by_username(username: str) -> Optional[UserRow]:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"""
            SELECT id, username, password_hash, display_name, role, is_active,
                   must_change_password
            FROM users WHERE username = $1
            """,
            username,
        )
        return UserRow(dict(row)) if row else None


async def count_users() -> int:
    pool = get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval("SELECT count(*) FROM users")


async def create_user(
    username: str,
    password_hash: str,
    *,
    role: str = "viewer",
    must_change_password: bool = False,
) -> UserRow:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO users (username, password_hash, display_name, role,
                               must_change_password)
            VALUES ($1, $2, $1, $3, $4)
            RETURNING id, username, password_hash, display_name, role, is_active,
                      must_change_password
            """,
            username, password_hash, role, must_change_password,
        )
        return UserRow(dict(row))


async def update_password(user_id: int, password_hash: str, *, must_change: bool = False) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE users
            SET password_hash = $2,
                must_change_password = $3,
                updated_at = now()
            WHERE id = $1
            """,
            user_id, password_hash, must_change,
        )


async def create_session(
    user_id: int,
    session_hash: str,
    csrf_token: str,
    expires_at: datetime,
) -> int:
    pool = get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO sessions (user_id, session_hash, csrf_token, expires_at)
            VALUES ($1, $2, $3, $4)
            RETURNING id
            """,
            user_id, session_hash, csrf_token, expires_at,
        )


async def find_active_session(session_hash: str) -> Optional[dict]:
    """유효(만료·폐기 아님)한 세션을 사용자 정보와 조인해 반환한다."""
    pool = get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """
            SELECT s.id AS session_id, s.csrf_token, s.expires_at, s.created_at,
                   s.last_seen_at,
                   u.id AS user_id, u.username, u.password_hash, u.display_name,
                   u.role, u.is_active, u.must_change_password
            FROM sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.session_hash = $1
              AND s.revoked_at IS NULL
              AND s.expires_at > $2
            """,
            session_hash, datetime.now(timezone.utc),
        )


async def touch_session(session_id: int, last_seen_at: datetime) -> None:
    """유휴 만료 기준(last_seen_at)을 갱신한다."""
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE sessions SET last_seen_at = $2 WHERE id = $1",
            session_id, last_seen_at,
        )


async def revoke_session(session_hash: str) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE sessions SET revoked_at = now() WHERE session_hash = $1 AND revoked_at IS NULL",
            session_hash,
        )


async def revoke_all_for_user(user_id: int) -> None:
    """비밀번호 변경 등으로 기존 세션을 전부 무효화한다."""
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE sessions SET revoked_at = now() WHERE user_id = $1 AND revoked_at IS NULL",
            user_id,
        )
