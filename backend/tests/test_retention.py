"""이슈 #97: processed_messages retention 정책 — TDD 테스트.

검증 범위:
1. 마이그레이션 004 파일 존재 + received_at 인덱스 생성
2. cleanup 함수가 30일 이상된 행만 삭제하는 SQL 실행
3. background task가 주기적으로 실행되도록 예약되는지
4. RETENTION_DAYS 상수가 30 (raw sensor_data retention과 동일)

DB 없이 단위 테스트로 검증. Testcontainers 통합 테스트는 #84에서.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


# ============================================================
# 1. 마이그레이션 파일 검증
# ============================================================

def test_migration_004_exists():
    """migrations/004_processed_messages_retention.sql 파일이 존재해야 한다."""
    expected = MIGRATIONS_DIR / "004_processed_messages_retention.sql"
    assert expected.exists(), "004_processed_messages_retention.sql 이 없다"


def test_migration_004_creates_received_at_index():
    """004 마이그레이션은 processed_messages.received_at 에 인덱스를 생성해야 한다."""
    sql = (MIGRATIONS_DIR / "004_processed_messages_retention.sql").read_text(
        encoding="utf-8"
    )
    # CREATE INDEX IF NOT EXISTS ... ON processed_messages (received_at)
    pattern = re.compile(
        r"CREATE\s+INDEX\s+IF\s+NOT\s+EXISTS\s+\w+\s+ON\s+processed_messages\s*\(\s*received_at\s*\)",
        re.IGNORECASE,
    )
    assert pattern.search(sql), (
        "004 마이그레이션에 processed_messages(received_at) 인덱스가 없다"
    )


def test_migration_004_is_idempotent():
    """모든 DDL이 IF NOT EXISTS 가드를 가져야 한다 (#98 원칙)."""
    sql = (MIGRATIONS_DIR / "004_processed_messages_retention.sql").read_text(
        encoding="utf-8"
    )
    # 주석 제거
    lines = [l.split("--", 1)[0] for l in sql.splitlines() if not l.strip().startswith("--")]
    cleaned = "\n".join(lines)
    if re.search(r"CREATE\s+INDEX", cleaned, re.IGNORECASE):
        assert re.search(
            r"CREATE\s+INDEX\s+IF\s+NOT\s+EXISTS", cleaned, re.IGNORECASE
        ), "CREATE INDEX 가 IF NOT EXISTS 없이 사용되었다"


# ============================================================
# 2. retention 모듈 검증
# ============================================================

def test_retention_module_importable():
    from app.services import retention
    assert hasattr(retention, "cleanup_processed_messages")
    assert hasattr(retention, "start")
    assert hasattr(retention, "stop")
    assert hasattr(retention, "RETENTION_DAYS")
    assert hasattr(retention, "CLEANUP_INTERVAL_SECONDS")


def test_retention_days_matches_raw():
    """RETENTION_DAYS 는 raw sensor_data retention(30일)과 동일해야 한다.
    (FR-101 SHOULD: 노드 버퍼링 최대 100건 — 30일보다 오래된 메시지는 없으므로
    dedup 정확성을 잃지 않는다.)"""
    from app.services.retention import RETENTION_DAYS
    assert RETENTION_DAYS == 30


def test_cleanup_interval_is_reasonable():
    """cleanup 주기는 1시간 이하여야 한다 (운영 환경에서 디스크 절약)."""
    from app.services.retention import CLEANUP_INTERVAL_SECONDS
    assert 60 <= CLEANUP_INTERVAL_SECONDS <= 3600


# ============================================================
# 3. cleanup 함수 동작 검증 (FakeConn 사용)
# ============================================================

class _FakeTx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeConn:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple]] = []

    async def execute(self, sql: str, *args: object) -> str:
        self.executed.append((sql, args))
        return "DELETE 0"

    def transaction(self):
        return _FakeTx()


class FakePool:
    def __init__(self, conn: FakeConn) -> None:
        self._conn = conn

    class _Acquired:
        def __init__(self, conn: FakeConn) -> None:
            self._conn = conn

        async def __aenter__(self):
            return self._conn

        async def __aexit__(self, *exc):
            return False

    def acquire(self):
        return self._Acquired(self._conn)


@pytest.mark.asyncio
async def test_cleanup_deletes_old_rows(monkeypatch):
    """cleanup 은 30일 이상된 processed_messages 행을 삭제하는 DELETE 를 실행한다."""
    from app.services import retention

    conn = FakeConn()
    pool = FakePool(conn)
    monkeypatch.setattr(retention, "get_pool", lambda: pool)

    deleted = await retention.cleanup_processed_messages()

    assert len(conn.executed) == 1
    sql = conn.executed[0][0].upper()
    assert "DELETE FROM PROCESSED_MESSAGES" in sql
    assert "RECEIVED_AT" in sql
    assert "INTERVAL" in sql or "$1" in sql
    assert deleted >= 0


@pytest.mark.asyncio
async def test_cleanup_uses_retention_days_threshold(monkeypatch):
    """cleanup SQL 은 RETENTION_DAYS(30) 일 임계값을 사용한다."""
    from app.services import retention

    conn = FakeConn()
    pool = FakePool(conn)
    monkeypatch.setattr(retention, "get_pool", lambda: pool)

    await retention.cleanup_processed_messages()

    sql = conn.executed[0][0]
    args = conn.executed[0][1]
    # INTERVAL '30 days' 패턴 또는 $1 인자로 30이 전달되어야 함
    interval_match = re.search(r"INTERVAL\s+'(\d+)\s+days?", sql, re.IGNORECASE)
    if interval_match:
        assert int(interval_match.group(1)) == retention.RETENTION_DAYS
    else:
        assert 30 in args, "30일 임계값이 SQL 에 명시되지 않았다"


@pytest.mark.asyncio
async def test_cleanup_returns_deleted_count(monkeypatch):
    """cleanup 은 삭제된 행 수를 반환한다."""
    from app.services import retention

    conn = FakeConn()
    conn.execute = lambda sql, *args: _return_delete_status("DELETE 42")  # type: ignore
    pool = FakePool(conn)
    monkeypatch.setattr(retention, "get_pool", lambda: pool)

    async def _async_execute(sql, *args):
        conn.executed.append((sql, args))
        return "DELETE 42"

    conn.execute = _async_execute  # type: ignore
    deleted = await retention.cleanup_processed_messages()
    assert deleted == 42


async def _return_delete_status(status: str):
    return status


# ============================================================
# 4. background task start/stop 검증
# ============================================================

@pytest.mark.asyncio
async def test_start_schedules_background_task(monkeypatch):
    """start() 는 asyncio.create_task 로 주기적 cleanup task 를 예약한다."""
    from app.services import retention

    created_tasks = []
    real_create_task = retention.asyncio.create_task

    def fake_create_task(coro, **kwargs):
        t = real_create_task(coro, **kwargs)
        created_tasks.append(t)
        return t

    monkeypatch.setattr(retention.asyncio, "create_task", fake_create_task)

    try:
        await retention.start()
        assert len(created_tasks) == 1, "start() 가 cleanup task 를 예약하지 않았다"
    finally:
        await retention.stop()
        for t in created_tasks:
            if not t.done():
                t.cancel()


@pytest.mark.asyncio
async def test_stop_cancels_background_task():
    """stop() 은 예약된 task 를 취소한다."""
    from app.services import retention

    await retention.start()
    assert retention._task is not None
    await retention.stop()
    assert retention._task is None
