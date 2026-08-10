"""이슈 #60: REST 이벤트 로그 조회 + 필터 — TDD 테스트."""
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


def test_module_importable():
    from app.repositories import alert_events_repository as repo
    assert hasattr(repo, "query")


@pytest.mark.asyncio
async def test_query_returns_rows(monkeypatch):
    from app.repositories import alert_events_repository as repo

    conn = FakeConn()
    conn.set_fetch("FROM alert_events", [
        {"message_id": "mid1", "alert_id": "aid1", "source_node_id": "sensor-01",
         "alert_key": "co2_ppm", "alert_type": "gas_threshold", "level": "level1_caution",
         "trigger_value": 1100.0, "threshold": 1000.0, "metric": "co2_ppm",
         "message": "...", "status": "active", "schema_version": "1.1",
         "activated_at": datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc),
         "resolved_at": None, "published_at": datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)},
    ])
    pool = FakePool(conn)
    monkeypatch.setattr(repo, "get_pool", lambda: pool)

    rows = await repo.query()
    assert len(rows) == 1
    assert rows[0]["source_node_id"] == "sensor-01"


@pytest.mark.asyncio
async def test_query_filters_by_node_id(monkeypatch):
    from app.repositories import alert_events_repository as repo

    conn = FakeConn()
    conn.set_fetch("FROM alert_events", [])
    pool = FakePool(conn)
    monkeypatch.setattr(repo, "get_pool", lambda: pool)

    await repo.query(node_id="sensor-01")
    args = conn.executed[0][1]
    assert "sensor-01" in args


@pytest.mark.asyncio
async def test_query_filters_by_status(monkeypatch):
    from app.repositories import alert_events_repository as repo

    conn = FakeConn()
    conn.set_fetch("FROM alert_events", [])
    pool = FakePool(conn)
    monkeypatch.setattr(repo, "get_pool", lambda: pool)

    await repo.query(status="active")
    sql = conn.executed[0][0].lower()
    assert "status" in sql


@pytest.mark.asyncio
async def test_query_filters_by_alert_key(monkeypatch):
    from app.repositories import alert_events_repository as repo

    conn = FakeConn()
    conn.set_fetch("FROM alert_events", [])
    pool = FakePool(conn)
    monkeypatch.setattr(repo, "get_pool", lambda: pool)

    await repo.query(alert_key="co2_ppm")
    args = conn.executed[0][1]
    assert "co2_ppm" in args


@pytest.mark.asyncio
async def test_query_filters_by_time_range(monkeypatch):
    from app.repositories import alert_events_repository as repo

    conn = FakeConn()
    conn.set_fetch("FROM alert_events", [])
    pool = FakePool(conn)
    monkeypatch.setattr(repo, "get_pool", lambda: pool)

    start = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 8, 10, 13, 0, 0, tzinfo=timezone.utc)
    await repo.query(start=start, end=end)
    sql = conn.executed[0][0].lower()
    assert "activated_at" in sql


@pytest.mark.asyncio
async def test_query_applies_limit(monkeypatch):
    from app.repositories import alert_events_repository as repo

    conn = FakeConn()
    conn.set_fetch("FROM alert_events", [])
    pool = FakePool(conn)
    monkeypatch.setattr(repo, "get_pool", lambda: pool)

    await repo.query(limit=50)
    sql = conn.executed[0][0].upper()
    assert "LIMIT" in sql


@pytest.fixture
def fake_repo(monkeypatch):
    from app.repositories import alert_events_repository as repo

    class FR:
        async def query(self, **kw):
            return [{
                "message_id": "mid1", "alert_id": "aid1",
                "source_node_id": kw.get("node_id", "sensor-01"),
                "alert_key": kw.get("alert_key", "co2_ppm"),
                "alert_type": "gas_threshold",
                "level": "level1_caution",
                "trigger_value": 1100.0, "threshold": 1000.0,
                "metric": "co2_ppm",
                "message": "msg",
                "status": kw.get("status", "active"),
                "schema_version": "1.1",
                "activated_at": datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc),
                "resolved_at": None,
                "published_at": datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc),
            }]
    fake = FR()
    monkeypatch.setattr(repo, "query", fake.query)
    return fake


@pytest.fixture
def client(fake_repo):
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


def test_get_events_returns_list(client):
    resp = client.get("/api/alert-events")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1


def test_get_events_filter_by_node_id(client):
    resp = client.get("/api/alert-events", params={"node_id": "sensor-02"})
    assert resp.status_code == 200
    assert resp.json()[0]["source_node_id"] == "sensor-02"


def test_get_events_filter_by_status(client):
    resp = client.get("/api/alert-events", params={"status": "resolved"})
    assert resp.status_code == 200
    assert resp.json()[0]["status"] == "resolved"


def test_get_events_invalid_status_returns_422(client):
    resp = client.get("/api/alert-events", params={"status": "unknown"})
    assert resp.status_code == 422


def test_get_events_applies_limit(client, fake_repo):
    resp = client.get("/api/alert-events", params={"limit": 50})
    assert resp.status_code == 200
