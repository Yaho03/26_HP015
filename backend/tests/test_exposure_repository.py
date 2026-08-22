"""노출량 DB 액세스 검증 (FR-701, §6.3).

DB 없이 검증한다 — `test_migrations.py` 가 쓰는 Fake 커넥션 패턴과 같다. 실제
Timescale 왕복은 TEST_TIMESCALE_URL 이 있을 때 도는 통합 테스트 소관이고, 여기서는
**SQL 의 모양과 트랜잭션 경계**를 본다. 그 두 가지가 이 계층에서 틀리면 조용히
데이터가 어긋난다.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models.exposure import ExposureShiftLogRow, ExposureStateRow
from app.repositories import exposure_repository as repo

T0 = datetime(2026, 8, 21, 1, 0, 0, tzinfo=timezone.utc)


class _FakeTx:
    def __init__(self, conn: "FakeConn") -> None:
        self._conn = conn

    async def __aenter__(self):
        self._conn.tx_depth += 1
        self._conn.tx_started += 1
        return self

    async def __aexit__(self, *exc):
        self._conn.tx_depth -= 1
        return False


class FakeConn:
    """asyncpg.Connection 흉내. 실행된 SQL 과 트랜잭션 깊이를 기록한다."""

    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple, int]] = []
        self.tx_depth = 0
        self.tx_started = 0
        self.fetch_rows: list[dict] = []
        self.fetchrow_row: dict | None = None

    async def execute(self, sql: str, *args):
        self.executed.append((sql, args, self.tx_depth))
        return "UPDATE 1"

    async def fetch(self, sql: str, *args):
        self.executed.append((sql, args, self.tx_depth))
        return self.fetch_rows

    async def fetchrow(self, sql: str, *args):
        self.executed.append((sql, args, self.tx_depth))
        return self.fetchrow_row

    def transaction(self):
        return _FakeTx(self)


class FakePool:
    def __init__(self, conn: FakeConn) -> None:
        self._conn = conn

    class _Acquired:
        def __init__(self, conn): self._conn = conn
        async def __aenter__(self): return self._conn
        async def __aexit__(self, *exc): return False

    def acquire(self):
        return self._Acquired(self._conn)


@pytest.fixture
def conn(monkeypatch) -> FakeConn:
    c = FakeConn()
    monkeypatch.setattr(repo, "get_pool", lambda: FakePool(c))
    return c


def _state(**over) -> ExposureStateRow:
    base = dict(
        exposure_id="01J000000000000000000000AA",
        worker_id=7,
        node_id="wearable-01",
        metric="co2_ppm",
        window_start=T0,
        window_source="assignment",
    )
    base.update(over)
    return ExposureStateRow(**base)


# ============================================================
# ULID
# ============================================================

def test_exposure_id_is_a_sortable_ulid():
    """python-ulid 를 쓴다 — 직접 구현하지 않는다 (이미 requirements 에 있다)."""
    a = repo.new_exposure_id()
    b = repo.new_exposure_id()
    assert len(a) == 26 and len(b) == 26
    # 같은 밀리초여도 충돌하지 않고, 시간이 지나면 사전순이 곧 발생순이다.
    assert a != b
    assert sorted([b, a]) == [a, b] or a[:10] == b[:10]


# ============================================================
# §3.2 — 시드되지 않은 기준값은 dict 에 없다
# ============================================================

@pytest.mark.asyncio
async def test_load_limits_omits_unseeded_metrics(conn):
    """0 이나 기본값으로 채우지 않는다.

    채우면 호출부가 기준 대비 0퍼센트를 계산하게 되고, 그게 §6.4 가 금지하는
    표시다. 행이 없는 것과 값이 0 인 것은 다른 상태다.
    """
    conn.fetch_rows = [
        {
            "metric": "co2_ppm", "twa_limit_ppm": 5000.0,
            "dose_limit_ppm_min": 2_400_000.0, "stel_limit_ppm": 30000.0,
            "reference": "고용노동부 고시 제2020-48호 별표1", "updated_at": T0,
        }
    ]
    limits = await repo.load_limits()
    assert set(limits) == {"co2_ppm"}
    assert "co_ppm" not in limits and "h2s_ppm" not in limits


# ============================================================
# 윈도우 열기 — 경합은 DB 가 거절하게 둔다
# ============================================================

@pytest.mark.asyncio
async def test_open_window_returns_none_when_already_active(conn):
    """ON CONFLICT DO NOTHING 이라 RETURNING 이 비면 None 이다.

    미리 SELECT 로 검사하지 않는 이유는 배정 이벤트와 기동 복구가 동시에 열려고 하면
    검사와 INSERT 사이가 벌어져 둘 다 통과하기 때문이다.
    """
    conn.fetchrow_row = None
    got = await repo.open_window("X", 7, "wearable-01", "co2_ppm", T0, "assignment")
    assert got is None
    sql = conn.executed[0][0]
    assert "ON CONFLICT DO NOTHING" in sql
    assert "INSERT INTO exposure_state" in sql


# ============================================================
# flush — 부분 반영 금지
# ============================================================

@pytest.mark.asyncio
async def test_flush_states_is_one_transaction(conn):
    """절반만 저장된 채로 죽으면 지표마다 기준 시각이 달라져, 복구 후 어떤 지표는
    이중 적산되고 어떤 지표는 빠진다."""
    rows = [_state(metric="co2_ppm"), _state(metric="co_ppm", exposure_id="B")]
    n = await repo.flush_states(rows)
    assert n == 2
    assert conn.tx_started == 1, "flush 가 트랜잭션으로 묶이지 않았다"
    updates = [e for e in conn.executed if "UPDATE exposure_state" in e[0]]
    assert len(updates) == 2
    assert all(depth > 0 for _, _, depth in updates), "UPDATE 가 트랜잭션 밖에서 실행됐다"


@pytest.mark.asyncio
async def test_flush_states_skips_empty(conn):
    assert await repo.flush_states([]) == 0
    assert conn.executed == []


@pytest.mark.asyncio
async def test_flush_only_touches_open_windows(conn):
    """이미 닫힌 윈도우를 되살리면 안 된다."""
    await repo.flush_states([_state()])
    sql = [e[0] for e in conn.executed if "UPDATE exposure_state" in e[0]][0]
    assert "closed_at IS NULL" in sql


# ============================================================
# 윈도우 종료 — 로그와 상태가 갈라지면 안 된다
# ============================================================

def _final() -> ExposureShiftLogRow:
    return ExposureShiftLogRow(
        exposure_id="01J000000000000000000000AA",
        worker_id=7, worker_name="홍길동", node_id="wearable-01", metric="co2_ppm",
        window_start=T0, window_end=T0 + timedelta(hours=2),
        dose_ppm_min=1000.0, dose_fraction=0.4, twa_8h_ppm=500.0, peak_ppm=1300.0,
        o2_deficient_s=None, data_gap_s=20,
        trust_level="high", max_alert_level="normal",
    )


@pytest.mark.asyncio
async def test_close_window_writes_log_and_closes_state_in_one_transaction(conn):
    """갈라지면 두 가지 고장이 난다 — 로그만 남으면 uq_exposure_state_active 가 다음
    배정을 막고, 상태만 닫히면 그 교대의 노출 기록이 통째로 사라진다."""
    await repo.close_window(_state(), _final())
    assert conn.tx_started == 1, "종료가 트랜잭션으로 묶이지 않았다"

    inserts = [e for e in conn.executed if "INSERT INTO exposure_shift_log" in e[0]]
    closes = [e for e in conn.executed if "SET closed_at" in e[0]]
    assert len(inserts) == 1 and len(closes) == 1
    assert inserts[0][2] > 0 and closes[0][2] > 0, "일부가 트랜잭션 밖이다"


@pytest.mark.asyncio
async def test_close_window_log_is_idempotent(conn):
    """재시도로 같은 윈도우를 두 번 확정해도 감사 기록이 중복되지 않아야 한다."""
    await repo.close_window(_state(), _final())
    sql = [e[0] for e in conn.executed if "INSERT INTO exposure_shift_log" in e[0]][0]
    assert "ON CONFLICT (exposure_id) DO NOTHING" in sql


# ============================================================
# 이력 조회
# ============================================================

@pytest.mark.asyncio
async def test_list_shift_log_without_filters_has_no_where(conn):
    conn.fetch_rows = []
    await repo.list_shift_log()
    sql, args, _ = conn.executed[0]
    assert "WHERE" not in sql
    assert args == (200,), "limit 이 마지막 인자여야 한다"


@pytest.mark.asyncio
async def test_list_shift_log_filters_are_positional_in_order(conn):
    """플레이스홀더 번호가 인자 순서와 어긋나면 조용히 엉뚱한 행이 나온다."""
    conn.fetch_rows = []
    start = T0
    end = T0 + timedelta(days=1)
    await repo.list_shift_log(worker_id=7, start=start, end=end, limit=50)
    sql, args, _ = conn.executed[0]
    assert args == (7, start, end, 50)
    assert "worker_id = $1" in sql
    assert "window_end >= $2" in sql
    assert "window_start <= $3" in sql
    assert "LIMIT $4" in sql
