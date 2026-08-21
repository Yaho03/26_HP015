"""누적 노출량 모델 (FR-701~708, 11_EXPOSURE_DOSE_SPEC.md §2).

필드명은 사양서 §2 변수명 표를 그대로 쓴다. 여기서 새로 짓지 않는다 — 백엔드
필드명·DB 컬럼명·WebSocket 페이로드 키·프론트 타입명이 전부 같은 표를 따라야
계약이 성립한다.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel

WindowSource = Literal["assignment", "manual_reset", "shift_rollover"]
TrustLevel = Literal["high", "medium", "low"]
AlertLevel = Literal["normal", "level1_caution", "level2_warning", "level3_critical"]

#: 노출량이 다루는 지표. sensor_data.metric 과 같은 문자열이어야 한다 (§2.3).
EXPOSURE_METRICS: tuple[str, ...] = ("co2_ppm", "co_ppm", "h2s_ppm", "o2_pct")


class ExposureLimit(BaseModel):
    """노출 기준값 한 줄.

    **시드되지 않은 metric 은 이 테이블에 행 자체가 없다** (§3.2). 그 경우 API 는
    status "unavailable", reason "limit_unverified" 로 내려보낸다. 행이 없는 것과
    값이 0 인 것은 다른 상태다.
    """

    metric: str
    twa_limit_ppm: Optional[float] = None
    dose_limit_ppm_min: Optional[float] = None
    stel_limit_ppm: Optional[float] = None
    reference: str
    updated_at: Optional[datetime] = None


class ExposureStateRow(BaseModel):
    """활성/종료된 노출 윈도우 한 줄 (exposure_state).

    적산 중 상태의 영속 표현이다. 메모리에만 두면 백엔드 재시작에 8시간 누적이
    사라진다 (§4.5 MUST).
    """

    exposure_id: str
    worker_id: int
    node_id: str
    metric: str
    window_start: datetime
    window_source: WindowSource

    dose_ppm_min: float = 0.0
    dose_worst_case_ppm_min: float = 0.0

    o2_deficient_s: int = 0
    o2_severe_s: int = 0
    o2_enriched_s: int = 0

    peak_ppm: Optional[float] = None
    peak_at: Optional[datetime] = None
    o2_min_pct: Optional[float] = None

    last_value: Optional[float] = None
    last_sample_at: Optional[datetime] = None

    data_gap_s: int = 0
    closed_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ExposureShiftLogRow(BaseModel):
    """확정된 과거 윈도우 (exposure_shift_log).

    worker_name 이 비정규화된 것은 의도다 — 작업자 레코드가 지워져도 "누가 얼마나
    노출됐는가"는 남아야 한다. 사고 조사와 분쟁의 근거라서다.
    """

    exposure_id: str
    worker_id: int
    worker_name: str
    node_id: str
    metric: str
    window_start: datetime
    window_end: datetime
    dose_ppm_min: Optional[float] = None
    dose_fraction: Optional[float] = None
    twa_8h_ppm: Optional[float] = None
    peak_ppm: Optional[float] = None
    o2_deficient_s: Optional[int] = None
    data_gap_s: int = 0
    trust_level: TrustLevel
    max_alert_level: AlertLevel
