"""sensor-data 시계열 API (이슈 #59).

- GET /api/sensor-data — 시계열 JSON 조회
- GET /api/sensor-data/export — CSV 내보내기
"""
from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Query
from fastapi.responses import PlainTextResponse

from app.repositories import sensor_data_repository

router = APIRouter(prefix="/api/sensor-data", tags=["sensor-data"])


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@router.get("")
async def get_sensor_data(
    node_id: str = Query(...),
    metric: str = Query(...),
    start: str = Query(...),
    end: str = Query(...),
    interval: Literal["1min"] | None = Query(None),
):
    rows = await sensor_data_repository.query(
        node_id=node_id, metric=metric,
        start=_parse_dt(start), end=_parse_dt(end),
        interval=interval,
    )
    return [
        {"time": r["time"].isoformat() if hasattr(r["time"], "isoformat") else r["time"],
         "value": r["value"]}
        for r in rows
    ]


@router.get("/export", response_class=PlainTextResponse)
async def export_sensor_data(
    node_id: str = Query(...),
    metric: str = Query(...),
    start: str = Query(...),
    end: str = Query(...),
    interval: Literal["1min"] | None = Query(None),
):
    rows = await sensor_data_repository.query(
        node_id=node_id, metric=metric,
        start=_parse_dt(start), end=_parse_dt(end),
        interval=interval,
    )
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["time", "value"])
    for r in rows:
        t = r["time"]
        t_str = t.isoformat() if hasattr(t, "isoformat") else str(t)
        writer.writerow([t_str, r["value"]])
    return PlainTextResponse(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="sensor_data_{node_id}_{metric}.csv"'},
    )
