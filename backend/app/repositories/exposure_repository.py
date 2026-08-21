"""누적 노출량 DB 액세스 (FR-701~708, 11_EXPOSURE_DOSE_SPEC.md §6.3).

`worker_repository.py` 와 같은 방식이다 — 얇은 함수, pydantic 모델 반환, 경쟁
조건은 미리 SELECT 해서 막지 않고 DB 제약이 거절하게 둔다.

이 계층이 지켜야 할 것 두 가지.

1. **기준값이 없는 것과 0 인 것을 구분한다.** `load_limits()` 는 시드되지 않은
   metric 을 dict 에서 아예 빼고 돌려준다. 0 이나 기본값으로 채우면 호출부가
   "기준 대비 0%"를 계산하게 되고, 그게 §6.4 가 금지하는 표시다.
2. **윈도우 종료는 원자적이다.** 확정 로그를 남기고 상태를 닫는 두 동작이 갈라지면
   사고 기록이 없는 채로 윈도우만 사라지거나, 닫히지 않은 윈도우가 남아
   `uq_exposure_state_active` 가 다음 배정을 막는다.
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, Iterable, List, Optional

from ulid import ULID

from app.db import get_pool
from app.models.exposure import ExposureLimit, ExposureShiftLogRow, ExposureStateRow


def new_exposure_id() -> str:
    """노출 윈도우 ID (§2.3 ULID).

    UUID4 가 아니라 ULID 인 이유는 **시간순 정렬**이다. 앞 48비트가 밀리초
    타임스탬프라 문자열 정렬이 곧 발생 순서가 되고, 사고 조사에서 시간축으로 훑을 때
    정렬 인덱스 없이도 눈으로 따라갈 수 있다.

    직접 구현하지 않는다 — `python-ulid` 가 이미 requirements.txt 에 있다.
    """
    return str(ULID())


__all__ = [
    "new_exposure_id",
    "load_limits",
    "load_active_states",
    "open_window",
    "flush_states",
    "close_window",
    "list_shift_log",
]

_STATE_COLUMNS = """
    exposure_id, worker_id, node_id, metric, window_start, window_source,
    dose_ppm_min, dose_worst_case_ppm_min,
    o2_deficient_s, o2_severe_s, o2_enriched_s,
    peak_ppm, peak_at, o2_min_pct,
    last_value, last_sample_at, data_gap_s, closed_at, updated_at
"""

# ── 기준값 ──────────────────────────────────────────────────────────────

async def load_limits() -> Dict[str, ExposureLimit]:
    """시드된 기준값만 돌려준다.

    시드되지 않은 metric 은 dict 에 **없다**. 기본값으로 채우지 않는 이유는 §3.2 —
    고시 원문 대조가 끝나지 않은 숫자를 안전 기준으로 쓰지 않기 위해서다. 호출부는
    `metric not in limits` 를 보고 reason "limit_unverified" 로 내려보낸다.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT metric, twa_limit_ppm, dose_limit_ppm_min, stel_limit_ppm,
                   reference, updated_at
            FROM exposure_limits
            """
        )
        return {r["metric"]: ExposureLimit(**dict(r)) for r in rows}


# ── 활성 윈도우 ─────────────────────────────────────────────────────────

async def load_active_states() -> List[ExposureStateRow]:
    """열려 있는 윈도우 전체. 기동 시 복구 경로가 쓴다 (§4.5).

    다운타임 구간을 data_gap_s 로 기록하는 책임은 호출부(서비스)에 있다. 여기서는
    마지막으로 flush 된 상태를 그대로 돌려준다.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"SELECT {_STATE_COLUMNS} FROM exposure_state WHERE closed_at IS NULL"
        )
        return [ExposureStateRow(**dict(r)) for r in rows]


async def open_window(
    exposure_id: str,
    worker_id: int,
    node_id: str,
    metric: str,
    window_start: datetime,
    window_source: str,
) -> Optional[ExposureStateRow]:
    """윈도우를 연다. 이미 활성 윈도우가 있으면 None.

    미리 SELECT 해서 검사하지 않는다 — 배정 이벤트와 기동 복구가 동시에 열려고 하면
    검사와 INSERT 사이가 벌어져 둘 다 통과한다. `uq_exposure_state_active` 가
    거절하게 두고 여기서 번역한다 (worker_repository.assign 과 같은 이유).
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"""
            INSERT INTO exposure_state
                (exposure_id, worker_id, node_id, metric, window_start, window_source)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT DO NOTHING
            RETURNING {_STATE_COLUMNS}
            """,
            exposure_id, worker_id, node_id, metric, window_start, window_source,
        )
        return ExposureStateRow(**dict(row)) if row else None


async def flush_states(states: Iterable[ExposureStateRow]) -> int:
    """적산 상태를 일괄 저장한다 (§4.5).

    한 트랜잭션으로 묶는 이유는 부분 반영을 막기 위해서다. 절반만 저장된 채로 죽으면
    노드마다 기준 시각이 달라져, 복구 후 어떤 지표는 이중 적산되고 어떤 지표는
    빠진다. 전부 반영되거나 전부 아니거나여야 다음 기동이 일관된 지점에서 출발한다.
    """
    rows = list(states)
    if not rows:
        return 0
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            for s in rows:
                await conn.execute(
                    """
                    UPDATE exposure_state SET
                        dose_ppm_min            = $2,
                        dose_worst_case_ppm_min = $3,
                        o2_deficient_s          = $4,
                        o2_severe_s             = $5,
                        o2_enriched_s           = $6,
                        peak_ppm                = $7,
                        peak_at                 = $8,
                        o2_min_pct              = $9,
                        last_value              = $10,
                        last_sample_at          = $11,
                        data_gap_s              = $12,
                        updated_at              = now()
                    WHERE exposure_id = $1 AND closed_at IS NULL
                    """,
                    s.exposure_id,
                    s.dose_ppm_min, s.dose_worst_case_ppm_min,
                    s.o2_deficient_s, s.o2_severe_s, s.o2_enriched_s,
                    s.peak_ppm, s.peak_at, s.o2_min_pct,
                    s.last_value, s.last_sample_at, s.data_gap_s,
                )
    return len(rows)


# ── 윈도우 종료 ─────────────────────────────────────────────────────────

async def close_window(state: ExposureStateRow, final: ExposureShiftLogRow) -> None:
    """확정 로그를 남기고 윈도우를 닫는다. **한 트랜잭션이다.**

    둘이 갈라지면 두 가지 고장이 난다.

      * 로그만 남고 상태가 안 닫히면 `uq_exposure_state_active` 가 다음 배정을 막는다
      * 상태만 닫히고 로그가 없으면 그 교대의 노출 기록이 통째로 사라진다

    로그는 ON CONFLICT DO NOTHING 이다 — 재시도로 같은 윈도우를 두 번 확정해도
    기록이 중복되지 않는다.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO exposure_shift_log (
                    exposure_id, worker_id, worker_name, node_id, metric,
                    window_start, window_end, dose_ppm_min, dose_fraction,
                    twa_8h_ppm, peak_ppm, o2_deficient_s, data_gap_s,
                    trust_level, max_alert_level
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
                ON CONFLICT (exposure_id) DO NOTHING
                """,
                final.exposure_id, final.worker_id, final.worker_name,
                final.node_id, final.metric, final.window_start, final.window_end,
                final.dose_ppm_min, final.dose_fraction, final.twa_8h_ppm,
                final.peak_ppm, final.o2_deficient_s, final.data_gap_s,
                final.trust_level, final.max_alert_level,
            )
            await conn.execute(
                "UPDATE exposure_state SET closed_at = $2, updated_at = now() "
                "WHERE exposure_id = $1 AND closed_at IS NULL",
                state.exposure_id, final.window_end,
            )


async def list_shift_log(
    worker_id: Optional[int] = None,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    limit: int = 200,
) -> List[ExposureShiftLogRow]:
    """확정된 과거 윈도우 조회 (§6.2 GET /api/exposure/history)."""
    clauses = []
    args: list = []
    if worker_id is not None:
        args.append(worker_id)
        clauses.append(f"worker_id = ${len(args)}")
    if start is not None:
        args.append(start)
        clauses.append(f"window_end >= ${len(args)}")
    if end is not None:
        args.append(end)
        clauses.append(f"window_start <= ${len(args)}")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    args.append(limit)

    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT exposure_id, worker_id, worker_name, node_id, metric,
                   window_start, window_end, dose_ppm_min, dose_fraction,
                   twa_8h_ppm, peak_ppm, o2_deficient_s, data_gap_s,
                   trust_level, max_alert_level
            FROM exposure_shift_log
            {where}
            ORDER BY window_start DESC
            LIMIT ${len(args)}
            """,
            *args,
        )
        return [ExposureShiftLogRow(**dict(r)) for r in rows]
