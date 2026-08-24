"""sensor_data 에 source_mode 를 보존한다 (AI 이상탐지 학습 데이터 분리).

배경: 실측(live)과 주입(simulation)이 같은 node_id 로 같은 테이블에 섞여 들어온다
(04_DATA_CONTRACT 3.5 — 주입도 실제 node_id 를 그대로 쓴다). 지금까지는 envelope 의
source_mode 를 읽지도 저장하지도 않아 저장된 뒤에는 둘을 구분할 방법이 없었다.
AI 이상탐지는 "정상 실측만 학습" 이 전제라 이 구분이 없으면 학습셋 자체를 만들 수 없다.

설계 결정 — 누락/이상값은 'live' 가 아니라 NULL 이다.
  데이터 계약상 source_mode 는 필수지만 ingest 는 그것을 필수로 강제하지 않는다
  (강제하면 필드 하나 때문에 안전 필수 메시지를 통째로 drop 하게 된다).
  대신 확신할 수 없으면 NULL 로 남겨 학습셋에서 자동으로 빠지게 한다.
  '모르는 것을 live 로 가정' 하면 주입값이 정상 실측으로 둔갑한다.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from app.services import ingest


class _FakeTx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeConn:
    def __init__(self) -> None:
        self.executemany_calls: list[tuple[str, list]] = []

    async def fetchrow(self, sql: str, *args: object):
        # _mark_processed — 항상 신규 메시지로 취급
        return {"message_id": args[0]}

    async def executemany(self, sql: str, rows: list) -> None:
        self.executemany_calls.append((sql, rows))

    async def execute(self, sql: str, *args: object) -> str:
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


def _envelope(**overrides) -> bytes:
    env = {
        "schema_version": "1.1",
        "message_id": "01J6X3R8K7VQ2NTP5Z9MA4HWBC",
        "node_id": "sensor-01",
        "sampled_at": "2026-08-24T00:00:00.000Z",
        "data": {"co2_ppm": 612},
    }
    env.update(overrides)
    return json.dumps(env).encode()


@pytest.fixture
def conn(monkeypatch) -> FakeConn:
    c = FakeConn()
    monkeypatch.setattr(ingest, "get_pool", lambda: FakePool(c))
    monkeypatch.setattr(ingest, "_alert_callback", None)
    monkeypatch.setattr(ingest, "_reading_callback", None)
    monkeypatch.setattr(ingest, "_exposure_callback", None)
    monkeypatch.setattr(ingest, "_location_callback", None)
    return c


def _inserted_rows(conn: FakeConn) -> list:
    assert conn.executemany_calls, "sensor_data INSERT 가 실행되지 않았다"
    sql, rows = conn.executemany_calls[0]
    assert "sensor_data" in sql
    return rows


@pytest.mark.asyncio
async def test_live_source_mode_is_stored(conn):
    await ingest.ingest_telemetry(_envelope(source_mode="live"))
    rows = _inserted_rows(conn)
    assert rows[0][-1] == "live"


@pytest.mark.asyncio
async def test_simulation_source_mode_is_stored(conn):
    await ingest.ingest_telemetry(_envelope(source_mode="simulation"))
    rows = _inserted_rows(conn)
    assert rows[0][-1] == "simulation"


@pytest.mark.asyncio
async def test_missing_source_mode_stored_as_null_not_live(conn):
    """누락은 'live' 로 가정하지 않는다 — 주입값이 실측으로 둔갑하는 경로다."""
    await ingest.ingest_telemetry(_envelope())
    rows = _inserted_rows(conn)
    assert rows[0][-1] is None


@pytest.mark.asyncio
async def test_unknown_source_mode_stored_as_null(conn):
    await ingest.ingest_telemetry(_envelope(source_mode="staging"))
    rows = _inserted_rows(conn)
    assert rows[0][-1] is None


@pytest.mark.asyncio
async def test_non_string_source_mode_does_not_reject_message(conn):
    """타입이 이상해도 메시지 자체는 살린다 — 저장이 경보보다 우선일 수 없다."""
    await ingest.ingest_telemetry(_envelope(source_mode=123))
    rows = _inserted_rows(conn)
    assert rows[0][2] == "co2_ppm"
    assert rows[0][-1] is None
