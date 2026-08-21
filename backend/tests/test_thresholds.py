"""이슈 #53: 임계값 DB 테이블 + 관리 API — TDD 테스트.

검증 범위:
1. 마이그레이션 005: thresholds 테이블 + 18행 기본값 시드
2. ThresholdRepository: list_all, list_by_metric, upsert (FakePool 기반)
3. FastAPI router: GET /api/thresholds, GET /api/thresholds/{metric}, PUT /api/thresholds/{metric}/{level}
4. PRD FR-201 / 06_ALERT_RULES 임계값 데이터 정합성
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


# ============================================================
# 1. 마이그레이션 005 검증
# ============================================================

def test_migration_005_exists():
    expected = MIGRATIONS_DIR / "005_thresholds.sql"
    assert expected.exists(), "005_thresholds.sql 이 없다"


def test_migration_005_creates_thresholds_table():
    sql = (MIGRATIONS_DIR / "005_thresholds.sql").read_text()
    pattern = re.compile(
        r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+thresholds",
        re.IGNORECASE,
    )
    assert pattern.search(sql), "thresholds 테이블 생성 구문이 없다"


def test_migration_005_has_required_columns():
    sql = (MIGRATIONS_DIR / "005_thresholds.sql").read_text().upper()
    for col in (
        "METRIC", "LEVEL", "DIRECTION",
        "ENTER_THRESHOLD", "EXIT_THRESHOLD",
        "ENTER_FOR_MS", "EXIT_FOR_MS",
        "UPDATED_AT",
    ):
        assert col in sql, f"thresholds 테이블에 {col} 컬럼이 없다"


def test_migration_005_has_primary_key_on_metric_level():
    sql = (MIGRATIONS_DIR / "005_thresholds.sql").read_text().upper()
    assert "PRIMARY KEY" in sql
    assert "METRIC" in sql and "LEVEL" in sql


def test_migration_005_seeds_default_thresholds():
    """PRD FR-201 + 06_ALERT_RULES 기본 임계값 18행이 시드되어야 한다.
    6 metrics (co2_ppm, co_ppm, h2s_ppm, temperature_c, o2_low, o2_high) × 3 levels."""
    sql = (MIGRATIONS_DIR / "005_thresholds.sql").read_text()
    insert_count = len(re.findall(r"INSERT\s+INTO\s+thresholds", sql, re.IGNORECASE))
    assert insert_count >= 1, "INSERT 구문이 없다"

    for metric in ("co2_ppm", "co_ppm", "h2s_ppm", "temperature_c", "o2_low", "o2_high"):
        assert metric in sql, f"기본 임계값에 {metric} 이 없다"

    for level in ("level1_caution", "level2_warning", "level3_critical"):
        assert level in sql, f"기본 임계값에 {level} 이 없다"


def test_migration_005_is_idempotent_or_uses_on_conflict():
    """시드 INSERT 는 재실행에 안전해야 한다 (ON CONFLICT DO NOTHING 또는 INSERT 단회)."""
    sql = (MIGRATIONS_DIR / "005_thresholds.sql").read_text().upper()
    if "INSERT INTO THRESHOLDS" in sql:
        assert "ON CONFLICT" in sql, (
            "INSERT 시드에 ON CONFLICT 가 없으면 재실행 시 중복 에러 (#98 위배)"
        )


# ============================================================
# 2. Pydantic 모델 검증
# ============================================================

def test_threshold_model_importable():
    from app.models.threshold import Threshold, ThresholdLevel, ThresholdDirection
    assert Threshold is not None
    assert ThresholdLevel is not None
    assert ThresholdDirection is not None


def test_threshold_model_validates_level_enum():
    from app.models.threshold import ThresholdLevel
    assert ThresholdLevel.LEVEL1 == "level1_caution"
    assert ThresholdLevel.LEVEL2 == "level2_warning"
    assert ThresholdLevel.LEVEL3 == "level3_critical"


def test_threshold_model_validates_direction_enum():
    from app.models.threshold import ThresholdDirection
    assert ThresholdDirection.ABOVE.value == "above"
    assert ThresholdDirection.BELOW.value == "below"


def test_threshold_model_rejects_negative_duration():
    """enter_for_ms/exit_for_ms 음수는 거부해야 한다."""
    from app.models.threshold import Threshold
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Threshold(
            metric="co2_ppm",
            level="level1_caution",
            direction="above",
            enter_threshold=1000,
            exit_threshold=900,
            enter_for_ms=-1,
            exit_for_ms=5000,
        )


# ============================================================
# 3. Repository 단위 테스트 (FakePool 기반)
# ============================================================

class _FakeTx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeConn:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple]] = []
        self._fetch_results: dict[str, list[dict]] = {}
        self._fetchrow_results: dict[str, dict | None] = {}

    async def execute(self, sql: str, *args: object) -> str:
        self.executed.append((sql, args))
        return "INSERT 0 1"

    async def fetch(self, sql: str, *args: object):
        self.executed.append((sql, args))
        for key, rows in self._fetch_results.items():
            if key in sql:
                return rows
        return []

    async def fetchrow(self, sql: str, *args: object):
        self.executed.append((sql, args))
        for key, row in self._fetchrow_results.items():
            if key in sql:
                return row
        return None

    def transaction(self):
        return _FakeTx()

    def set_fetch(self, sql_substr: str, rows: list[dict]) -> None:
        self._fetch_results[sql_substr] = rows

    def set_fetchrow(self, sql_substr: str, row: dict | None) -> None:
        self._fetchrow_results[sql_substr] = row


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
async def test_repository_list_all_returns_all_thresholds(monkeypatch):
    """list_all 은 모든 thresholds 행을 반환한다."""
    from app.repositories import threshold_repository
    from app.models.threshold import Threshold

    sample_rows = [
        {
            "metric": "co2_ppm", "level": "level1_caution", "direction": "above",
            "enter_threshold": 1000.0, "exit_threshold": 900.0,
            "enter_for_ms": 3000, "exit_for_ms": 5000, "updated_at": None,
        },
    ]
    conn = FakeConn()
    conn.set_fetch("FROM thresholds", sample_rows)
    pool = FakePool(conn)
    monkeypatch.setattr(threshold_repository, "get_pool", lambda: pool)

    result = await threshold_repository.list_all()
    assert len(result) == 1
    assert isinstance(result[0], Threshold)
    assert result[0].metric == "co2_ppm"


@pytest.mark.asyncio
async def test_repository_list_by_metric_filters(monkeypatch):
    """list_by_metric 은 해당 metric 의 임계값만 반환한다."""
    from app.repositories import threshold_repository

    conn = FakeConn()
    conn.set_fetch("FROM thresholds", [])
    pool = FakePool(conn)
    monkeypatch.setattr(threshold_repository, "get_pool", lambda: pool)

    await threshold_repository.list_by_metric("co2_ppm")

    sql = conn.executed[-1][0].upper()
    assert "WHERE" in sql
    assert "METRIC" in sql


@pytest.mark.asyncio
async def test_repository_upsert_inserts_or_updates(monkeypatch):
    """upsert 는 INSERT ... ON CONFLICT (metric, level) DO UPDATE 를 사용한다."""
    from app.repositories import threshold_repository
    from app.models.threshold import Threshold

    th = Threshold(
        metric="co2_ppm", level="level1_caution", direction="above",
        enter_threshold=1100.0, exit_threshold=950.0,
        enter_for_ms=3000, exit_for_ms=5000,
    )
    conn = FakeConn()
    pool = FakePool(conn)
    monkeypatch.setattr(threshold_repository, "get_pool", lambda: pool)

    await threshold_repository.upsert(th)

    assert len(conn.executed) == 1
    sql = conn.executed[0][0].upper()
    assert "INSERT INTO THRESHOLDS" in sql
    assert "ON CONFLICT" in sql
    assert "DO UPDATE" in sql


# ============================================================
# 4. FastAPI router 테스트 (TestClient + dependency override)
# ============================================================

@pytest.fixture
def fake_thresholds_repo(monkeypatch):
    """테스트용 thresholds repository stub.
    threshold_repository 모듈 함수들을 직접 monkeypatch."""
    from app.models.threshold import Threshold
    from app.repositories import threshold_repository

    class FakeRepo:
        def __init__(self):
            self.store: dict[tuple[str, str], Threshold] = {}
            self.calls: list[tuple] = []

        async def list_all(self):
            self.calls.append(("list_all",))
            return list(self.store.values())

        async def list_by_metric(self, metric: str):
            self.calls.append(("list_by_metric", metric))
            return [t for t in self.store.values() if t.metric == metric]

        async def upsert(self, threshold):
            self.calls.append(("upsert", threshold))
            self.store[(threshold.metric, threshold.level)] = threshold
            return threshold

        async def find(self, metric: str, level: str):
            self.calls.append(("find", metric, level))
            return self.store.get((metric, level))

    fake = FakeRepo()
    monkeypatch.setattr(threshold_repository, "list_all", fake.list_all)
    monkeypatch.setattr(threshold_repository, "list_by_metric", fake.list_by_metric)
    monkeypatch.setattr(threshold_repository, "upsert", fake.upsert)
    monkeypatch.setattr(threshold_repository, "find", fake.find)
    return fake


@pytest.fixture
def client(fake_thresholds_repo):
    """TestClient with fake repository dependency override.
    with-context를 사용하지 않아 lifespan(DB 연결)이 실행되지 않는다."""
    from fastapi.testclient import TestClient
    from app.main import app

    return TestClient(app)


def test_get_all_thresholds_returns_list(client, fake_thresholds_repo):
    """GET /api/thresholds → 200 + 모든 thresholds 리스트."""
    from app.models.threshold import Threshold
    fake_thresholds_repo.store[("co2_ppm", "level1_caution")] = Threshold(
        metric="co2_ppm", level="level1_caution", direction="above",
        enter_threshold=1000.0, exit_threshold=900.0,
        enter_for_ms=3000, exit_for_ms=5000,
    )

    resp = client.get("/api/thresholds")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["metric"] == "co2_ppm"
    assert data[0]["level"] == "level1_caution"


def test_get_thresholds_by_metric(client, fake_thresholds_repo):
    """GET /api/thresholds/{metric} → 200 + 해당 metric 임계값 리스트."""
    from app.models.threshold import Threshold
    fake_thresholds_repo.store[("co2_ppm", "level1_caution")] = Threshold(
        metric="co2_ppm", level="level1_caution", direction="above",
        enter_threshold=1000.0, exit_threshold=900.0,
        enter_for_ms=3000, exit_for_ms=5000,
    )
    fake_thresholds_repo.store[("temperature_c", "level1_caution")] = Threshold(
        metric="temperature_c", level="level1_caution", direction="above",
        enter_threshold=35.0, exit_threshold=34.0,
        enter_for_ms=5000, exit_for_ms=10000,
    )

    resp = client.get("/api/thresholds/co2_ppm")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["metric"] == "co2_ppm"


def test_get_thresholds_unknown_metric_returns_empty(client):
    """GET /api/thresholds/{unknown} → 200 + 빈 리스트 (에러 아님)."""
    resp = client.get("/api/thresholds/unknown_metric")
    assert resp.status_code == 200
    assert resp.json() == []


def test_put_threshold_updates_value(client, fake_thresholds_repo):
    """PUT /api/thresholds/{metric}/{level} → 200 + 반영된 값."""
    payload = {
        "direction": "above",
        "enter_threshold": 1200.0,
        "exit_threshold": 1000.0,
        "enter_for_ms": 3000,
        "exit_for_ms": 5000,
    }
    resp = client.put(
        "/api/thresholds/co2_ppm/level1_caution",
        json=payload,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["enter_threshold"] == 1200.0
    assert data["exit_threshold"] == 1000.0
    # repository 에 upsert 호출되었는지 확인
    upsert_calls = [c for c in fake_thresholds_repo.calls if c[0] == "upsert"]
    assert len(upsert_calls) == 1


def test_put_threshold_rejects_negative_duration(client):
    """PUT 음수 enter_for_ms → 422."""
    payload = {
        "direction": "above",
        "enter_threshold": 1200.0,
        "exit_threshold": 1000.0,
        "enter_for_ms": -1,
        "exit_for_ms": 5000,
    }
    resp = client.put("/api/thresholds/co2_ppm/level1_caution", json=payload)
    assert resp.status_code == 422


def test_put_threshold_rejects_invalid_level(client):
    """PUT 잘못된 level 값 → 422."""
    payload = {
        "direction": "above",
        "enter_threshold": 1200.0,
        "exit_threshold": 1000.0,
        "enter_for_ms": 3000,
        "exit_for_ms": 5000,
    }
    resp = client.put("/api/thresholds/co2_ppm/invalid_level", json=payload)
    assert resp.status_code == 422


def test_put_threshold_rejects_invalid_direction(client):
    """PUT 잘못된 direction → 422."""
    payload = {
        "direction": "sideways",
        "enter_threshold": 1200.0,
        "exit_threshold": 1000.0,
        "enter_for_ms": 3000,
        "exit_for_ms": 5000,
    }
    resp = client.put("/api/thresholds/co2_ppm/level1_caution", json=payload)
    assert resp.status_code == 422
