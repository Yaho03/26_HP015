"""messages_processed 가 실제 메시지 수를 세는지 (이슈 #117).

증가 호출이 metric 루프 안에 있어, 지표 4개를 담은 가스 메시지 1건이 4건으로
집계됐다. 처리량 지표가 부풀려지면 실제 부하와 유실을 판단할 수 없다.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from app.observability import metrics
from app.services import ingest


class _FakeTx:
    async def __aenter__(self): return self
    async def __aexit__(self, *exc): return False


class FakeConn:
    """중복 판정만 흉내낸다. is_new=False 면 이미 처리한 메시지다."""

    def __init__(self, is_new: bool = True):
        self._is_new = is_new
        self.inserted: list = []

    def transaction(self): return _FakeTx()

    async def fetchrow(self, sql, *args):
        return {"message_id": args[0]} if self._is_new else None

    async def executemany(self, sql, rows):
        self.inserted.extend(rows)


class FakePool:
    def __init__(self, conn): self._conn = conn

    class _A:
        def __init__(self, conn): self._conn = conn
        async def __aenter__(self): return self._conn
        async def __aexit__(self, *e): return False

    def acquire(self): return FakePool._A(self._conn)


def gas_payload(message_id: str = "01J6X3R8K7VQ2NTP5Z9MA4HWBC") -> bytes:
    """지표 4개를 담은 가스 메시지 1건."""
    return json.dumps({
        "schema_version": "1.1",
        "message_id": message_id,
        "node_id": "sensor-01",
        "sampled_at": datetime(2026, 8, 16, tzinfo=timezone.utc).isoformat(),
        "data": {
            "co2_ppm": 600,
            "co_ppm": 2.5,
            "h2s_ppm": 0.1,
            "gas_resistance_ohm": 80000,
        },
    }).encode()


@pytest.fixture
def counters(monkeypatch):
    """카운터를 0 으로 두고 DB 를 가짜로 바꾼다."""
    for name in metrics.snapshot():
        setattr(metrics, name, 0)
    monkeypatch.setattr(ingest, "_alert_callback", None)
    monkeypatch.setattr(ingest, "_reading_callback", None)
    monkeypatch.setattr(ingest, "_location_callback", None)
    return metrics


@pytest.mark.asyncio
async def test_one_message_counts_once(counters, monkeypatch):
    """★ 지표 4개짜리 메시지 1건은 1 이어야 한다. 예전에는 4 였다."""
    monkeypatch.setattr(ingest, "get_pool", lambda: FakePool(FakeConn()))
    await ingest.ingest_telemetry(gas_payload())
    assert counters.snapshot()["messages_processed"] == 1


@pytest.mark.asyncio
async def test_metrics_written_counts_each_metric(counters, monkeypatch):
    """지표 단위 집계는 별도 카운터로 남긴다 — 둘 다 알아야 유용하다."""
    monkeypatch.setattr(ingest, "get_pool", lambda: FakePool(FakeConn()))
    await ingest.ingest_telemetry(gas_payload())
    assert counters.snapshot()["metrics_written"] == 4


@pytest.mark.asyncio
async def test_two_messages_count_twice(counters, monkeypatch):
    monkeypatch.setattr(ingest, "get_pool", lambda: FakePool(FakeConn()))
    await ingest.ingest_telemetry(gas_payload("01J6X3R8K7VQ2NTP5Z9MA4HWB1"))
    await ingest.ingest_telemetry(gas_payload("01J6X3R8K7VQ2NTP5Z9MA4HWB2"))
    snap = counters.snapshot()
    assert snap["messages_processed"] == 2
    assert snap["metrics_written"] == 8


@pytest.mark.asyncio
async def test_duplicate_is_not_counted_as_processed(counters, monkeypatch):
    """중복은 처리한 것이 아니다. 별도 카운터가 이미 있다."""
    monkeypatch.setattr(ingest, "get_pool", lambda: FakePool(FakeConn(is_new=False)))
    with pytest.raises(ingest.DuplicateMessage):
        await ingest.ingest_telemetry(gas_payload())
    snap = counters.snapshot()
    assert snap["messages_processed"] == 0
    assert snap["metrics_written"] == 0


@pytest.mark.asyncio
async def test_message_without_numeric_metrics_still_counts(counters, monkeypatch):
    """숫자 지표가 하나도 없어도 메시지는 처리한 것이다.

    _extract_metrics 는 숫자 필드만 뽑으므로 문자열만 담긴 메시지는 지표가 0 이다.
    예전 구현은 증가가 루프 안에 있어 이런 메시지를 아예 세지 않았다.
    """
    monkeypatch.setattr(ingest, "get_pool", lambda: FakePool(FakeConn()))
    payload = json.dumps({
        "schema_version": "1.1",
        "message_id": "01J6X3R8K7VQ2NTP5Z9MA4HWB3",
        "node_id": "sensor-01",
        "sampled_at": datetime(2026, 8, 16, tzinfo=timezone.utc).isoformat(),
        "data": {"co_calibration_status": "uncalibrated"},
    }).encode()
    await ingest.ingest_telemetry(payload)
    snap = counters.snapshot()
    assert snap["messages_processed"] == 1
    assert snap["metrics_written"] == 0


def test_metrics_written_is_exposed():
    assert "metrics_written" in metrics.snapshot()
