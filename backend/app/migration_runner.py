"""마이그레이션 러너 — 이슈 #98 (idempotency 보강).

각 .sql 파일을 번호(파일명) 순서대로 적용하되, schema_migrations 추적 테이블에
이미 기록된 파일은 스킵한다. 각 파일의 SHA-256 checksum 으로 내용 변조를 감지한다.

설계 원칙:
- 외부 프레임워크(alembic/yoyo) 없이 asyncpg + 50줄 러너로 구현
- 모든 DDL은 SQL 자체에 IF NOT EXISTS / CREATE OR REPLACE 가드가 있어야 한다 (정적 검사로 검증)
- 러너 자체도 idempotent: schema_migrations 테이블을 IF NOT EXISTS 로 생성하고
  적용된 파일은 INSERT ... ON CONFLICT DO NOTHING 으로 무시
- 각 마이그레이션 파일은 하나의 트랜잭션으로 적용 (atomicity)
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Optional

from app.db import get_pool

logger = logging.getLogger(__name__)

# schema_migrations 추적 테이블 DDL.
# 러너가 가장 먼저 실행한다. 일반 마이그레이션 파일 루프에서는 스킵된다
# (파일명으로 중복 처리 방지).
SCHEMA_MIGRATIONS_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename    TEXT PRIMARY KEY,
    checksum    TEXT NOT NULL,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

# 000_schema_migrations.sql 파일명 (이 파일은 러너가 직접 처리)
_SCHEMA_MIGRATIONS_FILENAME = "000_schema_migrations.sql"


def _migrations_dir() -> Path:
    """마이그레이션 디렉토리 경로. backend/migrations/."""
    # backend/app/migration_runner.py → backend/migrations/
    return Path(__file__).resolve().parent.parent / "migrations"


def _checksum(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _list_migration_files(migrations_dir: Path) -> list[Path]:
    """migrations/ 디렉토리의 .sql 파일을 번호(파일명)순으로 정렬해 반환.
    000_schema_migrations.sql 은 제외 (러너가 직접 처리)."""
    files = sorted(p for p in migrations_dir.glob("*.sql") if p.name != _SCHEMA_MIGRATIONS_FILENAME)
    return files


async def apply_all() -> None:
    """모든 미적용 마이그레이션을 순서대로 적용한다.

    1. schema_migrations 추적 테이블 생성 (IF NOT EXISTS, idempotent)
    2. migrations/ 내 .sql 파일을 파일명 순으로 정렬
    3. 각 파일에 대해:
       a. 이미 schema_migrations 에 기록되어 있으면 → checksum 비교 후 스킵 (불일치 시 에러)
       b. 미적용 파일이면 → 트랜잭션으로 실행 후 schema_migrations 에 INSERT
    """
    pool = get_pool()
    migrations_dir = _migrations_dir()

    async with pool.acquire() as conn:
        # 1. 추적 테이블 생성 (러너가 직접 처리)
        await conn.execute(SCHEMA_MIGRATIONS_SQL)

        # 2. 파일 목록
        files = _list_migration_files(migrations_dir)
        if not files:
            logger.info("no migration files to apply")
            return

        # 3. 각 파일 처리
        for path in files:
            await _apply_one(conn, path)


async def _apply_one(conn, path: Path) -> None:
    """단일 마이그레이션 파일 적용. 이미 적용되었으면 스킵, checksum 불일치 시 에러."""
    content = path.read_text(encoding="utf-8")
    checksum = _checksum(content)

    # schema_migrations 조회
    row = await conn.fetchrow(
        "SELECT filename, checksum FROM schema_migrations WHERE filename = $1",
        path.name,
    )
    if row is not None:
        # 이미 적용됨 — checksum 검증
        if row["checksum"] != checksum:
            raise RuntimeError(
                f"checksum mismatch for {path.name}: "
                f"applied={row['checksum']}, current={checksum}. "
                f"마이그레이션 파일이 적용 후 수정되었습니다. "
                f"새 파일을 추가하거나 schema_migrations 에서 수동 처리하세요."
            )
        logger.debug("migration %s already applied, skipping", path.name)
        return

    # 미적용 — 트랜잭션으로 실행 후 추적 테이블에 기록
    logger.info("applying migration %s", path.name)
    async with conn.transaction():
        await conn.execute(content)
        await conn.execute(
            "INSERT INTO schema_migrations (filename, checksum) VALUES ($1, $2)",
            path.name,
            checksum,
        )
