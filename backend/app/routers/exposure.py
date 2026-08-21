"""누적 노출량 API (FR-701~708, 11_EXPOSURE_DOSE_SPEC.md §6.2).

- GET  /api/exposure/current            — 활성 윈도우 전체 (대시보드 초기 로드)
- GET  /api/exposure/current/{node_id}  — 노드 1개
- GET  /api/exposure/history            — 확정된 과거 윈도우
- POST /api/exposure/reset              — 수동 리셋 (supervisor+, CSRF)
- GET  /api/exposure/limits             — 노출 기준값 조회
- PUT  /api/exposure/limits/{metric}    — 기준값 수정 (admin, CSRF)

전 경로는 enforce_authentication 게이트 아래에 있다 (AUTH-3). PUBLIC_PATHS 에
넣지 않는다 — 노출량은 개인의 건강 정보다.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.dependencies.auth import require_role, verify_csrf
from app.models.exposure import EXPOSURE_METRICS, ExposureLimit, ExposureShiftLogRow
from app.repositories import exposure_repository as repo
from app.services import exposure_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/exposure", tags=["exposure"])


class ExposureResetRequest(BaseModel):
    node_id: str
    #: 사유는 필수다 (§5.2 MUST). 노출량 경보의 **유일한 해제 경로**라, 왜 지웠는지가
    #: 남지 않으면 8시간 누적을 지운 근거를 나중에 아무도 대지 못한다.
    reason: str = Field(min_length=1)


class ExposureLimitUpdate(BaseModel):
    twa_limit_ppm: Optional[float] = None
    dose_limit_ppm_min: Optional[float] = None
    stel_limit_ppm: Optional[float] = None
    #: 출처. 고시명·조항·개정일이 들어가야 한다 (§3.3 MUST). 길이 하한은 DB CHECK 가
    #: 강제하므로 여기서 다시 검사하지 않는다 — 검증이 두 곳에 있으면 갈라진다.
    reference: str


@router.get("/current")
async def get_current_all():
    """활성 윈도우 전체. 대시보드가 초기 로드에서 부르고, 이후 갱신은 WebSocket 이 맡는다."""
    return exposure_service.snapshot_all()


@router.get("/current/{node_id}")
async def get_current(node_id: str):
    snapshot = exposure_service.snapshot(node_id)
    if snapshot is None:
        # 배정이 없거나 적산이 시작되지 않았다. 빈 객체 대신 404 로 구분한다 —
        # 빈 값을 200 으로 주면 화면이 "노출 없음"으로 그린다.
        raise HTTPException(status_code=404, detail="활성 노출 윈도우가 없습니다")
    return snapshot


@router.get("/history", response_model=list[ExposureShiftLogRow])
async def get_history(
    worker_id: Optional[int] = None,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    limit: int = Query(default=200, ge=1, le=1000),
):
    """확정된 과거 윈도우. 사고 조사와 교대 리포트가 쓴다."""
    return await repo.list_shift_log(worker_id=worker_id, start=start, end=end, limit=limit)


@router.get("/limits", response_model=list[ExposureLimit])
async def get_limits():
    """시드된 기준값만 나온다.

    비어 있는 것이 정상 상태다 (§3.2) — 고시 원문 대조(P0-A) 전까지 시드하지 않는다.
    화면은 그 metric 을 "0% 노출"이 아니라 "기준값 미검증"으로 그린다.
    """
    limits = await repo.load_limits()
    return [limits[m] for m in sorted(limits)]


@router.put("/limits/{metric}", response_model=ExposureLimit)
async def put_limit(
    metric: str,
    payload: ExposureLimitUpdate,
    # 노출 기준값은 작업자 안전 기준이다. thresholds 와 같은 등급으로 막는다.
    user=Depends(require_role("admin")),
    _csrf: None = Depends(verify_csrf),
):
    if metric not in EXPOSURE_METRICS:
        raise HTTPException(
            status_code=400,
            detail=f"노출량 대상 metric 이 아닙니다: {metric}",
        )
    saved = await repo.upsert_limit(ExposureLimit(metric=metric, **payload.model_dump()))
    # FR-605 감사 로그 테이블 적재는 그 인프라(#182)가 이 브랜치 계보에 아직 없다.
    # main 으로 rebase 한 뒤 연결한다. 그때까지는 애플리케이션 로그에 남긴다.
    logger.warning(
        "노출 기준값 변경 (metric=%s, actor=%s, reference=%r)",
        metric, _actor(user), saved.reference,
    )
    await exposure_service.reload_limits()
    return saved


@router.post("/reset")
async def reset_exposure(
    payload: ExposureResetRequest,
    # supervisor 이상 (§5.2 MUST). 노출량 경보는 자동 해제되지 않으므로 이것이
    # 유일한 해제 경로다 — viewer 가 누를 수 있으면 규칙이 무의미해진다.
    user=Depends(require_role("supervisor")),
    _csrf: None = Depends(verify_csrf),
):
    closed = await exposure_service.reset_windows(
        payload.node_id, payload.reason, _actor(user)
    )
    if closed == 0:
        raise HTTPException(status_code=404, detail="활성 노출 윈도우가 없습니다")
    return {"node_id": payload.node_id, "closed_windows": closed}


def _actor(user) -> str:
    """감사 기록용 행위자 표기. 모델이 바뀌어도 리셋이 실패하지는 않게 한다."""
    return getattr(user, "username", None) or getattr(user, "id", None) or "unknown"
