"""alert-events 로그 API (이슈 #60)."""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Query

from app.repositories import alert_events_repository

router = APIRouter(prefix="/api/alert-events", tags=["alert-events"])


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _serialize(row: dict) -> dict:
    out = dict(row)
    for k in ("activated_at", "resolved_at", "published_at"):
        v = out.get(k)
        if isinstance(v, datetime):
            out[k] = v.isoformat()
    return out


@router.get("")
async def get_alert_events(
    node_id: Optional[str] = Query(None),
    alert_key: Optional[str] = Query(None),
    status: Optional[Literal["active", "resolved"]] = Query(None),
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
):
    rows = await alert_events_repository.query(
        node_id=node_id, alert_key=alert_key, status=status,
        start=_parse_dt(start), end=_parse_dt(end),
        limit=limit,
    )
    return [_serialize(r) for r in rows]
