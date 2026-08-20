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
    def __init__(self, previous_status: str | None = None) -> None:
        self.executed: list[tuple[str, tuple]] = []
        self.previous_status = previous_status

    async def fetchval(self, sql: str, *args: object):
        return self.previous_status

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
async def test_recovery_callback_fires_on_offline_to_online_transition(monkeypatch):
    """이슈 #111: 이전 상태가 offline이었던 노드가 online 메시지를 보내면
    복귀 콜백이 호출돼야 한다 (connection_lost 경보 해제 트리거)."""
    conn = FakeConn(previous_status="offline")
    pool = FakePool(conn)
    monkeypatch.setattr(ingest, "get_pool", lambda: pool)

    recovered: list[str] = []

    async def _on_recovery(node_id: str) -> None:
        recovered.append(node_id)
    monkeypatch.setattr(ingest, "_connection_recovery_callback", _on_recovery)

    await ingest.ingest_connection(_connection_payload(status="online", reason="connect"))

    assert recovered == ["sensor-01"]


@pytest.mark.asyncio
async def test_recovery_callback_not_fired_when_already_online(monkeypatch):
    """이전 상태가 이미 online이면 (중복 online 메시지) 복귀 콜백을 또 쏘면 안 됨."""
    conn = FakeConn(previous_status="online")
    pool = FakePool(conn)
    monkeypatch.setattr(ingest, "get_pool", lambda: pool)

    recovered: list[str] = []

    async def _on_recovery(node_id: str) -> None:
        recovered.append(node_id)
    monkeypatch.setattr(ingest, "_connection_recovery_callback", _on_recovery)

    await ingest.ingest_connection(_connection_payload(status="online", reason="connect"))

    assert recovered == []


@pytest.mark.asyncio
async def test_recovery_callback_not_fired_for_offline_message(monkeypatch):
    """offline 메시지 자체는 복귀가 아니므로 콜백이 호출되면 안 됨."""
    conn = FakeConn(previous_status="online")
    pool = FakePool(conn)
    monkeypatch.setattr(ingest, "get_pool", lambda: pool)

    recovered: list[str] = []

    async def _on_recovery(node_id: str) -> None:
        recovered.append(node_id)
    monkeypatch.setattr(ingest, "_connection_recovery_callback", _on_recovery)

    await ingest.ingest_connection(_connection_payload(status="offline", reason="lwt"))

    assert recovered == []


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
async def test_offline_status_bypasses_timestamp_ordering_guard(monkeypatch):
    """이슈 #107 리뷰 3번: offline은 timestamp 순서 가드 없이 항상 반영돼야 한다.

    LWT payload는 CONNECT 시점에 고정되어 나중에 실제 오프라인 시각을 반영하지
    못하므로(항상 "연결했던 시각"), timestamp가 기존 connection_updated_at보다
    과거여도 offline 전환만은 무조건 통과해야 한다. 실제 DB에서의 재현/검증은
    커밋 메시지 참조 — 여기서는 실행되는 SQL이 offline을 무조건 통과시키는
    분기를 포함하는지 확인한다."""
    conn = FakeConn()
    pool = FakePool(conn)
    monkeypatch.setattr(ingest, "get_pool", lambda: pool)

    await ingest.ingest_connection(_connection_payload(status="offline"))

    sql = conn.executed[0][0]
    assert "connection_status = 'offline'" in sql, (
        "WHERE 절에 offline 무조건 통과 분기가 없으면 LWT가 항상 stale timestamp로 "
        "드롭될 수 있음"
    )


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
