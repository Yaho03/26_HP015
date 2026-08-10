"""이슈 #96: ingest_connection reason 필드 옵셔널화 — TDD 테스트.

문제: LWT offline 메시지는 reason 이 없을 수 있음 → InvalidMessage 로 drop
      → safety-critical disconnect 이벤트 유실 위험.

검증 범위:
1. reason 없는 connection 메시지도 정상 처리
2. reason 있는 메시지는 기존대로 처리
3. reason 누락 시 "unknown" 으로 정규화해 저장
4. node_id/status/timestamp 는 여전히 필수
5. reason 빈 문자열도 "unknown" 으로 정규화
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import pytest

from app.services import ingest


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
        return "INSERT 0 1"

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


def _connection_payload(**overrides: Any) -> bytes:
    payload = {
        "schema_version": "1.1",
        "node_id": "sensor-01",
        "status": "offline",
        "reason": "lwt",
        "boot_id": "01J6X3R8K7VQ2NTP5Z9MA4HWBD",
        "timestamp": "2026-08-09T12:00:00.000Z",
    }
    payload.update(overrides)
    return json.dumps(payload).encode("utf-8")


@pytest.mark.asyncio
async def test_connection_message_without_reason_is_accepted(monkeypatch):
    """reason 필드가 없는 connection 메시지는 InvalidMessage 없이 처리되어야 한다."""
    conn = FakeConn()
    pool = FakePool(conn)
    monkeypatch.setattr(ingest, "get_pool", lambda: pool)

    payload = _connection_payload()
    payload_obj = json.loads(payload)
    del payload_obj["reason"]
    payload = json.dumps(payload_obj).encode("utf-8")

    await ingest.ingest_connection(payload)  # should not raise

    assert len(conn.executed) == 1
    sql = conn.executed[0][0].upper()
    assert "INSERT INTO NODE_STATUS" in sql


@pytest.mark.asyncio
async def test_connection_message_without_reason_uses_unknown(monkeypatch):
    """reason 이 누락된 경우 "unknown" 으로 정규화해 저장해야 한다."""
    conn = FakeConn()
    pool = FakePool(conn)
    monkeypatch.setattr(ingest, "get_pool", lambda: pool)

    payload_obj = json.loads(_connection_payload())
    del payload_obj["reason"]
    payload = json.dumps(payload_obj).encode("utf-8")

    await ingest.ingest_connection(payload)

    args = conn.executed[0][1]
    status, reason, ts = args[1], args[2], args[3]
    assert status == "offline"
    assert reason == "unknown"


@pytest.mark.asyncio
async def test_connection_message_with_reason_uses_provided_value(monkeypatch):
    """reason 이 명시된 경우 해당 값을 그대로 사용한다 (regression 방지)."""
    conn = FakeConn()
    pool = FakePool(conn)
    monkeypatch.setattr(ingest, "get_pool", lambda: pool)

    await ingest.ingest_connection(_connection_payload(reason="lwt"))

    args = conn.executed[0][1]
    assert args[2] == "lwt"


@pytest.mark.asyncio
async def test_connection_message_empty_reason_normalized_to_unknown(monkeypatch):
    """빈 문자열 reason 도 "unknown" 으로 정규화한다."""
    conn = FakeConn()
    pool = FakePool(conn)
    monkeypatch.setattr(ingest, "get_pool", lambda: pool)

    await ingest.ingest_connection(_connection_payload(reason=""))

    args = conn.executed[0][1]
    assert args[2] == "unknown"


@pytest.mark.asyncio
async def test_connection_message_missing_node_id_still_rejected(monkeypatch):
    """node_id 가 없으면 여전히 InvalidMessage."""
    conn = FakeConn()
    pool = FakePool(conn)
    monkeypatch.setattr(ingest, "get_pool", lambda: pool)

    payload_obj = json.loads(_connection_payload())
    del payload_obj["node_id"]
    payload = json.dumps(payload_obj).encode("utf-8")

    with pytest.raises(ingest.InvalidMessage) as exc_info:
        await ingest.ingest_connection(payload)
    assert "node_id" in str(exc_info.value)


@pytest.mark.asyncio
async def test_connection_message_missing_status_still_rejected(monkeypatch):
    """status 가 없으면 여전히 InvalidMessage."""
    conn = FakeConn()
    pool = FakePool(conn)
    monkeypatch.setattr(ingest, "get_pool", lambda: pool)

    payload_obj = json.loads(_connection_payload())
    del payload_obj["status"]
    payload = json.dumps(payload_obj).encode("utf-8")

    with pytest.raises(ingest.InvalidMessage):
        await ingest.ingest_connection(payload)


@pytest.mark.asyncio
async def test_connection_message_missing_timestamp_still_rejected(monkeypatch):
    """timestamp 가 없으면 여전히 InvalidMessage."""
    conn = FakeConn()
    pool = FakePool(conn)
    monkeypatch.setattr(ingest, "get_pool", lambda: pool)

    payload_obj = json.loads(_connection_payload())
    del payload_obj["timestamp"]
    payload = json.dumps(payload_obj).encode("utf-8")

    with pytest.raises(ingest.InvalidMessage):
        await ingest.ingest_connection(payload)
