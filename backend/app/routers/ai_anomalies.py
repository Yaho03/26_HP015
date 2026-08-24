"""AI 이상징후 조회 API (연구용).

경로에 alert 라는 낱말을 쓰지 않는다. `/api/alert-events` 와 이름이 닮으면
호출하는 쪽에서 언젠가 둘을 같은 것으로 다루게 된다.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Query

from app.repositories import ai_anomaly_repository
from app.services import ai_anomaly_service

router = APIRouter(prefix="/api/ai-anomalies", tags=["ai-anomalies"])


@router.get("/model")
async def model_info() -> dict:
    """모델 준비 상태와 한계. 화면이 '연구용' 배지를 그리는 근거다."""
    artifact = ai_anomaly_service.artifact()
    if artifact is None:
        return {
            "ready": False,
            "status": ai_anomaly_service.STATUS_MODEL_NOT_READY,
            "is_research_only": True,
        }
    return {
        "ready": True,
        "model_version": artifact.model_version,
        "features": artifact.features,
        "n_features": artifact.n_features,
        "sequence_length": artifact.sequence_length,
        "resample_interval_s": artifact.resample_interval_s,
        "threshold": artifact.threshold,
        "known_nodes": sorted(artifact.scaler_per_node),
        "is_research_only": True,
        # 학습 데이터의 한계. null 이 아니면 화면이 경고 문구를 함께 그린다.
        "data_limitation": artifact.data_limitation,
    }


@router.get("/latest")
async def latest() -> List[dict]:
    return await ai_anomaly_repository.latest_by_node()


@router.get("/history")
async def history(
    node_id: str,
    start: Optional[datetime] = Query(None),
    end: Optional[datetime] = Query(None),
    limit: int = Query(5000, ge=1, le=20000),
) -> List[dict]:
    now = datetime.now(timezone.utc)
    return await ai_anomaly_repository.history(
        node_id=node_id,
        start=start or (now - timedelta(hours=1)),
        end=end or now,
        limit=limit,
    )
