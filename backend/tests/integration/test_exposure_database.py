"""실제 TimescaleDB에서 노출량 스키마의 안전 불변식을 검증한다."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import asyncpg
import pytest

from app.models.exposure import ExposureShiftLogRow, ExposureStateRow
from app.repositories import exposure_repository as repo


T0 = datetime(2026, 8, 21, 1, 0, tzinfo=timezone.utc)
MIGRATION = Path(__file__).resolve().parents[2] / "migrations" / "009_exposure.sql"


async def _worker(conn: asyncpg.Connection, suffix: str) -> int:
    return await conn.fetchval(
        "INSERT INTO workers (employee_no, name) VALUES ($1, $2) RETURNING id",
        f"EXP-DB-{suffix}",
        "노출량 통합 테스트",
    )


def _state(worker_id: int, exposure_id: str = "01J000000000000000000000AA") -> ExposureStateRow:
    return ExposureStateRow(
        exposure_id=exposure_id,
        worker_id=worker_id,
        node_id="wearable-test",
        metric="co2_ppm",
        window_start=T0,
        window_source="assignment",
    )


def _final(worker_id: int, exposure_id: str = "01J000000000000000000000AA") -> ExposureShiftLogRow:
    return ExposureShiftLogRow(
        exposure_id=exposure_id,
        worker_id=worker_id,
        worker_name="노출량 통합 테스트",
        node_id="wearable-test",
        metric="co2_ppm",
        window_start=T0,
        window_end=T0 + timedelta(hours=1),
        dose_ppm_min=60_000,
        dose_fraction=None,
        twa_8h_ppm=125,
        peak_ppm=1_000,
        o2_deficient_s=None,
        data_gap_s=0,
        trust_level="high",
        max_alert_level="normal",
    )


class _SameConnectionPool:
    """repository가 fixture 트랜잭션과 같은 연결을 쓰게 하는 최소 어댑터."""

    def __init__(self, connection: asyncpg.Connection) -> None:
        self.connection = connection

    class _Acquire:
        def __init__(self, connection: asyncpg.Connection) -> None:
            self.connection = connection

        async def __aenter__(self) -> asyncpg.Connection:
            return self.connection

        async def __aexit__(self, *exc) -> bool:
            return False

    def acquire(self) -> "_SameConnectionPool._Acquire":
        return self._Acquire(self.connection)


@pytest.mark.asyncio
async def test_exposure_migration_is_idempotent_on_timescale(conn):
    """009 전체를 두 번 실행해도 실제 PostgreSQL에서 실패하지 않는다."""
    sql = MIGRATION.read_text(encoding="utf-8")
    await conn.execute(sql)
    await conn.execute(sql)


@pytest.mark.asyncio
async def test_verified_exposure_limits_are_seeded_exactly(conn):
    rows = await conn.fetch(
        """SELECT metric, twa_limit_ppm, dose_limit_ppm_min, stel_limit_ppm,
                  reference
           FROM exposure_limits
           ORDER BY metric"""
    )
    by_metric = {row["metric"]: row for row in rows}

    assert set(by_metric) == {"co2_ppm", "co_ppm", "h2s_ppm"}
    expected = {
        "co2_ppm": (5000, 2_400_000, 30_000, "124-38-9"),
        "co_ppm": (30, 14_400, 200, "630-08-0"),
        "h2s_ppm": (10, 4_800, 15, "7783-06-4"),
    }
    for metric, (twa, dose, stel, cas) in expected.items():
        row = by_metric[metric]
        assert row["twa_limit_ppm"] == twa
        assert row["dose_limit_ppm_min"] == dose == twa * 480
        assert row["stel_limit_ppm"] == stel
        assert "제2020-48호" in row["reference"]
        assert cas in row["reference"]


@pytest.mark.asyncio
async def test_o2_is_not_seeded_as_accumulated_ppm_limit(conn):
    assert await conn.fetchval(
        "SELECT count(*) FROM exposure_limits WHERE metric = 'o2_pct'"
    ) == 0


@pytest.mark.asyncio
async def test_active_window_unique_index_rejects_duplicate(conn):
    worker_id = await _worker(conn, "UNIQUE")
    args = (worker_id, "wearable-test", "co2_ppm", T0, "assignment")
    await conn.execute(
        """INSERT INTO exposure_state
           (exposure_id, worker_id, node_id, metric, window_start, window_source)
           VALUES ('01J000000000000000000000AB', $1, $2, $3, $4, $5)""",
        *args,
    )
    with pytest.raises(asyncpg.UniqueViolationError):
        await conn.execute(
            """INSERT INTO exposure_state
               (exposure_id, worker_id, node_id, metric, window_start, window_source)
               VALUES ('01J000000000000000000000AC', $1, $2, $3, $4, $5)""",
            *args,
        )


@pytest.mark.asyncio
async def test_close_window_rolls_back_log_when_state_update_fails(conn, monkeypatch):
    """두 번째 쓰기가 실패하면 앞선 확정 로그도 남지 않아야 한다."""
    worker_id = await _worker(conn, "ATOMIC")
    state = _state(worker_id)
    final = _final(worker_id)
    await conn.execute(
        """INSERT INTO exposure_state
           (exposure_id, worker_id, node_id, metric, window_start, window_source)
           VALUES ($1, $2, $3, $4, $5, $6)""",
        state.exposure_id,
        state.worker_id,
        state.node_id,
        state.metric,
        state.window_start,
        state.window_source,
    )
    await conn.execute(
        """CREATE FUNCTION pg_temp.reject_exposure_close() RETURNS trigger AS $$
           BEGIN RAISE EXCEPTION 'forced close failure'; END;
           $$ LANGUAGE plpgsql"""
    )
    await conn.execute(
        """CREATE TRIGGER reject_exposure_close
           BEFORE UPDATE ON exposure_state
           FOR EACH ROW EXECUTE FUNCTION pg_temp.reject_exposure_close()"""
    )
    monkeypatch.setattr(repo, "get_pool", lambda: _SameConnectionPool(conn))

    with pytest.raises(asyncpg.RaiseError, match="forced close failure"):
        await repo.close_window(state, final)

    assert await conn.fetchval(
        "SELECT count(*) FROM exposure_shift_log WHERE exposure_id = $1",
        state.exposure_id,
    ) == 0
    assert await conn.fetchval(
        "SELECT closed_at IS NULL FROM exposure_state WHERE exposure_id = $1",
        state.exposure_id,
    ) is True


@pytest.mark.asyncio
@pytest.mark.parametrize("reference", ["", "ACGIH"])
async def test_exposure_limit_rejects_non_substantive_reference(conn, reference):
    with pytest.raises(asyncpg.CheckViolationError):
        await conn.execute(
            """INSERT INTO exposure_limits
               (metric, twa_limit_ppm, dose_limit_ppm_min, stel_limit_ppm, reference)
               VALUES ('o2_pct', 19.5, 9360, NULL, $1)""",
            reference,
        )
