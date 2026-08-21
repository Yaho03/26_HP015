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
from app.repositories import audit_repository
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
    before = (await repo.load_limits()).get(metric)
    saved = await repo.upsert_limit(ExposureLimit(metric=metric, **payload.model_dump()))
    actor_id, actor_name = _actor(user)
    # FR-605. 노출 기준값은 안전 기준이라 "누가 언제 무엇을 무엇으로 바꿨는가"가
    # 남아야 한다. before 를 함께 남기는 이유는 사후에 "원래 값이 뭐였나"를 다른
    # 곳에서 복원할 수 없기 때문이다 — upsert 가 이전 행을 덮어쓴다.
    await audit_repository.record(
        actor_id, actor_name, "exposure_limit_update", metric,
        {
            "before": before.model_dump(mode="json") if before else None,
            "after": saved.model_dump(mode="json"),
        },
    )
    logger.warning(
        "노출 기준값 변경 (metric=%s, actor=%s, reference=%r)",
        metric, actor_name, saved.reference,
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
    actor_id, actor_name = _actor(user)
    # 리셋 **전** 상태를 감사 로그에 남긴다. 리셋하고 나면 누적값이 확정 로그로
    # 넘어가 버려서, 무엇을 지웠는지가 이 기록에만 남는다.
    before = exposure_service.snapshot(payload.node_id)
    closed = await exposure_service.reset_windows(
        payload.node_id, payload.reason, actor_name
    )
    if closed == 0:
        raise HTTPException(status_code=404, detail="활성 노출 윈도우가 없습니다")

    # FR-605 MUST (§5.2). 노출량 경보의 유일한 해제 경로라, 사유 없이 지운 흔적이
    # 남지 않으면 8시간 누적을 지운 근거를 나중에 아무도 대지 못한다.
    await audit_repository.record(
        actor_id, actor_name, "exposure_reset", payload.node_id,
        {"reason": payload.reason, "closed_windows": closed, "before": before},
    )
    return {"node_id": payload.node_id, "closed_windows": closed}


def _actor(user) -> tuple[Optional[int], str]:
    """감사 기록용 행위자. 모델이 바뀌어도 리셋 자체가 실패하지는 않게 방어한다.

    감사 쓰기가 본 기능을 막으면 감사가 오히려 안전 운영을 막는 역설이 된다
    (audit_repository.record 의 같은 판단).
    """
    actor_id = getattr(user, "id", None)
    name = getattr(user, "username", None) or (str(actor_id) if actor_id else "unknown")
    return (actor_id if isinstance(actor_id, int) else None), name
