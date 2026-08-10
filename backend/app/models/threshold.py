"""thresholds 데이터 모델 (이슈 #53).

PRD FR-201 + 06_ALERT_RULES 4.x 의 임계값 정의를 pydantic 모델로 표현.
- metric: co2_ppm, co_ppm, h2s_ppm, temperature_c, o2_low, o2_high
- level: level1_caution, level2_warning, level3_critical
- direction: above (측정값 >= enter_threshold 진입), below (측정값 < enter_threshold 진입, O2 저농도)
- enter_threshold / exit_threshold: Hysteresis 쌍
- enter_for_ms / exit_for_ms: 시간 기반 판정 지속 (06_ALERT_RULES 섹션 3)
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class ThresholdLevel(str, Enum):
    LEVEL1 = "level1_caution"
    LEVEL2 = "level2_warning"
    LEVEL3 = "level3_critical"

    @property
    def numeric(self) -> int:
        return {self.LEVEL1: 1, self.LEVEL2: 2, self.LEVEL3: 3}[self]


class ThresholdDirection(str, Enum):
    ABOVE = "above"
    BELOW = "below"


class Threshold(BaseModel):
    """thresholds 테이블 한 행과 1:1 대응."""

    model_config = ConfigDict(from_attributes=True)

    metric: str = Field(..., min_length=1)
    level: ThresholdLevel
    direction: ThresholdDirection = ThresholdDirection.ABOVE
    enter_threshold: float
    exit_threshold: float
    enter_for_ms: int = Field(..., ge=0)
    exit_for_ms: int = Field(..., ge=0)
    updated_at: datetime | None = None


class ThresholdUpdate(BaseModel):
    """PUT /api/thresholds/{metric}/{level} 요청 바디.
    metric/level 은 path parameter 에서 오므로 본문에서 제외."""

    direction: ThresholdDirection = ThresholdDirection.ABOVE
    enter_threshold: float
    exit_threshold: float
    enter_for_ms: int = Field(..., ge=0)
    exit_for_ms: int = Field(..., ge=0)
