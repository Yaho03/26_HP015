"""이슈 #59: REST 시계열 데이터 조회 + CSV 내보내기 — TDD 테스트."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest


class _FakeTx:
    async def __aenter__(self): return self
    async def __aexit__(self, *exc): return False


class FakeConn:
    def __init__(self):
        self.executed: list[tuple[str, tuple]] = []
        self._fetch_results: dict[str, list] = {}

    async def fetch(self, sql: str, *args):
        self.executed.append((sql, args))
        for k, v in self._fetch_results.items():
            if k in sql: return v
        return []

    def set_fetch(self, k, rows): self._fetch_results[k] = rows


class FakePool:
    def __init__(self, conn): self._conn = conn
    class _A:
        def __init__(self, conn): self._conn = conn
        async def __aenter__(self): return self._conn
        async def __aexit__(self, *e): return False
    def acquire(self): return FakePool._A(self._conn)


def test_sensor_data_module_importable():
    from app.repositories import sensor_data_repository
    assert hasattr(sensor_data_repository, "query")


@pytest.mark.asyncio
async def test_query_raw_returns_rows(monkeypatch):
    from app.repositories import sensor_data_repository as repo

    conn = FakeConn()
    conn.set_fetch("FROM sensor_data", [
        {"time": datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc), "value": 1100.0},
    ])
    pool = FakePool(conn)
    monkeypatch.setattr(repo, "get_pool", lambda: pool)

    rows = await repo.query(
        node_id="sensor-01", metric="co2_ppm",
        start=datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc),
        end=datetime(2026, 8, 10, 12, 5, 0, tzinfo=timezone.utc),
    )
    assert len(rows) == 1
    assert rows[0]["value"] == 1100.0


@pytest.mark.asyncio
async def test_query_uses_1min_aggregate_when_interval_specified(monkeypatch):
    """interval=1min 인 경우 sensor_data_1min 뷰에서 조회한다."""
    from app.repositories import sensor_data_repository as repo

    conn = FakeConn()
    conn.set_fetch("FROM sensor_data_1min", [
        {"bucket": datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc), "value": 1100.0},
    ])
    pool = FakePool(conn)
    monkeypatch.setattr(repo, "get_pool", lambda: pool)

    await repo.query(
        node_id="sensor-01", metric="co2_ppm",
        start=datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc),
        end=datetime(2026, 8, 10, 12, 5, 0, tzinfo=timezone.utc),
        interval="1min",
    )
    sql = conn.executed[0][0].lower()
    assert "sensor_data_1min" in sql


@pytest.mark.asyncio
async def test_query_filters_node_metric_time(monkeypatch):
    from app.repositories import sensor_data_repository as repo

    conn = FakeConn()
    conn.set_fetch("from sensor_data", [])
    pool = FakePool(conn)
    monkeypatch.setattr(repo, "get_pool", lambda: pool)

    await repo.query(
        node_id="sensor-01", metric="co2_ppm",
        start=datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc),
        end=datetime(2026, 8, 10, 12, 5, 0, tzinfo=timezone.utc),
    )
    args = conn.executed[0][1]
    assert "sensor-01" in args
    assert "co2_ppm" in args


@pytest.fixture
def fake_repo(monkeypatch):
    from app.repositories import sensor_data_repository as repo

    class FakeRepo:
        def __init__(self): self.calls = []
        async def query(self, **kw):
            self.calls.append(kw)
            return [{"time": datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc), "value": 1100.0}]
    fake = FakeRepo()
    monkeypatch.setattr(repo, "query", fake.query)
    return fake


@pytest.fixture
def client(fake_repo):
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


def test_get_sensor_data_returns_json(client):
    resp = client.get("/api/sensor-data", params={
        "node_id": "sensor-01", "metric": "co2_ppm",
        "start": "2026-08-10T12:00:00Z", "end": "2026-08-10T12:05:00Z",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["value"] == 1100.0


def test_get_sensor_data_csv_returns_csv(client):
    resp = client.get("/api/sensor-data/export", params={
        "node_id": "sensor-01", "metric": "co2_ppm",
        "start": "2026-08-10T12:00:00Z", "end": "2026-08-10T12:05:00Z",
    })
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]
    body = resp.text
    assert "time" in body
    assert "value" in body
    assert "1100" in body


def test_get_sensor_data_with_interval(client, fake_repo):
    resp = client.get("/api/sensor-data", params={
        "node_id": "sensor-01", "metric": "co2_ppm",
        "start": "2026-08-10T12:00:00Z", "end": "2026-08-10T12:05:00Z",
        "interval": "1min",
    })
    assert resp.status_code == 200
    assert fake_repo.calls[-1]["interval"] == "1min"


def test_get_sensor_data_invalid_interval_returns_422(client):
    resp = client.get("/api/sensor-data", params={
        "node_id": "sensor-01", "metric": "co2_ppm",
        "start": "2026-08-10T12:00:00Z", "end": "2026-08-10T12:05:00Z",
        "interval": "5sec",
    })
    assert resp.status_code == 422


def test_get_sensor_data_missing_required_returns_422(client):
    resp = client.get("/api/sensor-data", params={
        "node_id": "sensor-01",
    })
    assert resp.status_code == 422
