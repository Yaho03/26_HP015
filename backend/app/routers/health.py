"""health & metrics API (이슈 #88)."""
from __future__ import annotations

from fastapi import APIRouter

from app import db
from app.services import mqtt_subscriber

router = APIRouter()


@router.get("/health")
def health():
    return {
        "status": "ok",
        "mqtt": {"connected": mqtt_subscriber.get_client() is not None},
        "db": {"pool_initialized": db.is_initialized()},
    }


@router.get("/api/metrics")
def get_metrics():
    from app.observability import metrics
    return metrics.snapshot()
