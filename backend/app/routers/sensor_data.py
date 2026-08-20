"""sensor-data 시계열 API (이슈 #59, #120).

- GET /api/sensor-data — 시계열 JSON 조회
- GET /api/sensor-data/export — CSV 내보내기
"""
from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta
from typing import Iterator, Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.repositories import sensor_data_repository

router = APIRouter(prefix="/api/sensor-data", tags=["sensor-data"])

# raw sensor_data 는 노드·지표당 초당 1건이 쌓인다. 상한이 없으면 기간만 넓게 줘도
# 수백만 행이 메모리로 올라온다 (이슈 #120).
DEFAULT_LIMIT = 10_000
MAX_LIMIT = 100_000

# TimescaleDB raw 보존이 30일이라 그보다 넓게 조회할 이유가 없다. 하루를 얹어
# 경계에서 자르지 않는다.
MAX_RANGE_DAYS = 31


def _parse_dt(value: str, field: str) -> datetime:
    """ISO8601 파싱. 형식 오류는 사용자 입력 문제이므로 422 로 알린다.

    예전에는 ValueError 가 그대로 올라가 500 이 됐다. 서버 오류로 보고하면
    호출자가 자기 요청을 고칠 수 있다는 걸 알 수 없다.
    """
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=422,
            detail=f"{field} 는 ISO8601 형식이어야 합니다 (예: 2026-08-16T00:00:00Z). 받은 값: {value!r}",
        )


def _validated_range(start: str, end: str) -> tuple[datetime, datetime]:
    start_dt = _parse_dt(start, "start")
    end_dt = _parse_dt(end, "end")
    if end_dt < start_dt:
        raise HTTPException(status_code=422, detail="end 는 start 보다 빠를 수 없습니다.")
    if end_dt - start_dt > timedelta(days=MAX_RANGE_DAYS):
        raise HTTPException(
            status_code=422,
            detail=f"조회 기간은 최대 {MAX_RANGE_DAYS}일입니다 (raw 보존 기간 30일).",
        )
    return start_dt, end_dt


def _iso(value) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


@router.get("")
async def get_sensor_data(
    node_id: str = Query(...),
    metric: str = Query(...),
    start: str = Query(...),
    end: str = Query(...),
    interval: Literal["1min"] | None = Query(None),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
):
    start_dt, end_dt = _validated_range(start, end)
    rows = await sensor_data_repository.query(
        node_id=node_id, metric=metric,
        start=start_dt, end=end_dt,
        interval=interval, limit=limit,
    )
    return [{"time": _iso(r["time"]), "value": r["value"]} for r in rows]


@router.get("/export")
async def export_sensor_data(
    node_id: str = Query(...),
    metric: str = Query(...),
    start: str = Query(...),
    end: str = Query(...),
    interval: Literal["1min"] | None = Query(None),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
):
    start_dt, end_dt = _validated_range(start, end)
    rows = await sensor_data_repository.query(
        node_id=node_id, metric=metric,
        start=start_dt, end=end_dt,
        interval=interval, limit=limit,
    )

    def lines() -> Iterator[str]:
        """행을 흘려보낸다. 예전에는 CSV 전체를 StringIO 에 만든 뒤 다시 문자열로
        복사해 같은 데이터를 두 벌 들고 있었다."""
        buf = io.StringIO()
        writer = csv.writer(buf)

        def flush() -> str:
            chunk = buf.getvalue()
            buf.seek(0)
            buf.truncate(0)
            return chunk

        writer.writerow(["time", "value"])
        yield flush()
        for r in rows:
            writer.writerow([_iso(r["time"]), r["value"]])
            yield flush()

    return StreamingResponse(
        lines(),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="sensor_data_{node_id}_{metric}.csv"'
        },
    )
