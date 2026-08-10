"""이슈 #52: 노드 연결 상태 관리 (30초 timeout 감지) — TDD 테스트.

검증 범위:
1. connection_monitor 모듈 정의
2. 30초 이상 backend_received_at 과거 노드를 offline 으로 표시
3. timeout 감지 시 connection_lost 경보 발생
4. 재접속(online 메시지) 시 정상 복귀 (ingest_connection 에서 처리됨, 여기서는 간접 검증)
5. background task 주기적 실행
6. timeout 임계값 30초
"""
from __future__ import annotations

import pytest


async def _async_noop(*args, **kwargs):
    pass


def test_connection_monitor_module_importable():
    from app.services import connection_monitor
    assert hasattr(connection_monitor, "TIMEOUT_SECONDS")
    assert hasattr(connection_monitor, "check_timeouts")
    assert hasattr(connection_monitor, "start")
    assert hasattr(connection_monitor, "stop")


def test_timeout_is_30_seconds():
    from app.services.connection_monitor import TIMEOUT_SECONDS
    assert TIMEOUT_SECONDS == 30


class _FakeTx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeConn:
    def __init__(self):
        self.executed: list[tuple[str, tuple]] = []
        self._fetch_results: dict[str, list[dict]] = {}

    async def fetch(self, sql: str, *args):
        self.executed.append((sql, args))
        for key, rows in self._fetch_results.items():
            if key in sql:
                return rows
        return []

    async def execute(self, sql: str, *args):
        self.executed.append((sql, args))
        return "UPDATE 0"

    def transaction(self):
        return _FakeTx()

    def set_fetch(self, sql_substr: str, rows: list[dict]) -> None:
        self._fetch_results[sql_substr] = rows


class FakePool:
    def __init__(self, conn):
        self._conn = conn

    class _Acquired:
        def __init__(self, conn):
            self._conn = conn

        async def __aenter__(self):
            return self._conn

        async def __aexit__(self, *exc):
            return False

    def acquire(self):
        return self._Acquired(self._conn)


@pytest.mark.asyncio
async def test_check_timeouts_finds_stale_nodes(monkeypatch):
    """30초 이상된 노드를 찾는 SELECT 쿼리를 실행한다."""
    from app.services import connection_monitor

    conn = FakeConn()
    conn.set_fetch("FROM node_status", [
        {"node_id": "sensor-01", "connection_status": "online"},
    ])
    pool = FakePool(conn)
    monkeypatch.setattr(connection_monitor, "get_pool", lambda: pool)
    monkeypatch.setattr(connection_monitor, "_emit_connection_lost", _async_noop)

    stale_count = await connection_monitor.check_timeouts()

    select_calls = [s for s, _ in conn.executed if "SELECT" in s.upper()]
    assert len(select_calls) >= 1
    assert stale_count == 1


@pytest.mark.asyncio
async def test_check_timeouts_updates_stale_nodes_to_offline(monkeypatch):
    """stale 노드를 connection_status='offline', reason='timeout' 으로 UPDATE."""
    from app.services import connection_monitor

    conn = FakeConn()
    conn.set_fetch("FROM node_status", [
        {"node_id": "sensor-01", "connection_status": "online"},
    ])
    pool = FakePool(conn)
    monkeypatch.setattr(connection_monitor, "get_pool", lambda: pool)
    monkeypatch.setattr(connection_monitor, "_emit_connection_lost", _async_noop)

    await connection_monitor.check_timeouts()

    update_calls = [s for s, _ in conn.executed if "UPDATE NODE_STATUS" in s.upper()]
    assert len(update_calls) >= 1
    first = update_calls[0].upper()
    assert "OFFLINE" in first
    assert "TIMEOUT" in first


@pytest.mark.asyncio
async def test_check_timeouts_emits_connection_lost_alert(monkeypatch):
    """timeout 감지 시 connection_lost 경보를 발생시킨다."""
    from app.services import connection_monitor

    conn = FakeConn()
    conn.set_fetch("FROM node_status", [
        {"node_id": "sensor-01", "connection_status": "online"},
    ])
    pool = FakePool(conn)
    monkeypatch.setattr(connection_monitor, "get_pool", lambda: pool)

    emitted: list = []
    async def _fake_emit(node_id):
        emitted.append(node_id)
    monkeypatch.setattr(connection_monitor, "_emit_connection_lost", _fake_emit)

    await connection_monitor.check_timeouts()

    assert emitted == ["sensor-01"]


@pytest.mark.asyncio
async def test_check_timeouts_no_stale_nodes(monkeypatch):
    """stale 노드가 없으면 아무 일도 일어나지 않는다."""
    from app.services import connection_monitor

    conn = FakeConn()
    conn.set_fetch("FROM node_status", [])
    pool = FakePool(conn)
    monkeypatch.setattr(connection_monitor, "get_pool", lambda: pool)

    emitted: list = []
    async def _fake_emit(node_id):
        emitted.append(node_id)
    monkeypatch.setattr(connection_monitor, "_emit_connection_lost", _fake_emit)

    stale = await connection_monitor.check_timeouts()
    assert stale == 0
    update_calls = [s for s, _ in conn.executed if "UPDATE" in s.upper()]
    assert len(update_calls) == 0
    assert emitted == []


@pytest.mark.asyncio
async def test_check_timeouts_skips_already_offline_nodes(monkeypatch):
    """이미 offline 상태인 노드는 SELECT 결과에서 제외된다 (쿼리가 connection_status='online' 필터).
    실제 SQL filter 는 DB 에서 일어나므로, 테스트는 online 행만 반환하는 fixture 로 검증."""
    from app.services import connection_monitor

    conn = FakeConn()
    conn.set_fetch("FROM node_status", [
        {"node_id": "sensor-01", "connection_status": "online"},
    ])
    pool = FakePool(conn)
    monkeypatch.setattr(connection_monitor, "get_pool", lambda: pool)

    emitted: list = []
    async def _fake_emit(node_id):
        emitted.append(node_id)
    monkeypatch.setattr(connection_monitor, "_emit_connection_lost", _fake_emit)

    stale = await connection_monitor.check_timeouts()
    assert stale == 1

    select_sql = next((s for s, _ in conn.executed if "SELECT" in s.upper()), "")
    assert "connection_status = 'online'" in select_sql or "connection_status='online'" in select_sql, (
        "SELECT 가 connection_status='online' 필터를 포함해야 함 (이미 offline 노드 제외)"
    )


@pytest.mark.asyncio
async def test_start_schedules_periodic_task(monkeypatch):
    from app.services import connection_monitor
    import asyncio

    await connection_monitor.start()
    try:
        assert connection_monitor._task is not None
    finally:
        await connection_monitor.stop()


@pytest.mark.asyncio
async def test_stop_cancels_task():
    from app.services import connection_monitor

    await connection_monitor.start()
    assert connection_monitor._task is not None
    await connection_monitor.stop()
    assert connection_monitor._task is None
