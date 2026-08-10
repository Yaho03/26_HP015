"""thresholds 관리 API 라우터 (이슈 #53).

- GET /api/thresholds — 전체 임계값 조회
- GET /api/thresholds/{metric} — metric별 조회
- PUT /api/thresholds/{metric}/{level} — 임계값 수정

PRD FR-204: 임계값은 코드에 하드코딩하지 않는다. DB + 관리 API.
"""
from __future__ import annotations

import logging
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException

from app.models.threshold import Threshold, ThresholdLevel, ThresholdUpdate
from app.repositories import threshold_repository
from app.services import alert_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/thresholds", tags=["thresholds"])


async def get_threshold_repository() -> AsyncIterator[None]:
    yield


@router.get("", response_model=list[Threshold])
async def get_all_thresholds(_=Depends(get_threshold_repository)):
    return await threshold_repository.list_all()


@router.get("/{metric}", response_model=list[Threshold])
async def get_thresholds_by_metric(metric: str, _=Depends(get_threshold_repository)):
    return await threshold_repository.list_by_metric(metric)


@router.put("/{metric}/{level}", response_model=Threshold)
async def update_threshold(
    metric: str,
    level: ThresholdLevel,
    payload: ThresholdUpdate,
    _=Depends(get_threshold_repository),
):
    if not metric:
        raise HTTPException(status_code=400, detail="metric is required")
    threshold = Threshold(
        metric=metric,
        level=level,
        direction=payload.direction,
        enter_threshold=payload.enter_threshold,
        exit_threshold=payload.exit_threshold,
        enter_for_ms=payload.enter_for_ms,
        exit_for_ms=payload.exit_for_ms,
    )
    saved = await threshold_repository.upsert(threshold)
    try:
        await alert_service.reload()
    except Exception:
        logger.exception("alert evaluator reload failed after threshold update")
    return saved
