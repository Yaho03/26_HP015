"""경보 상태/전환 모델 (이슈 #54).

- AlertLevel: NORMAL, LEVEL1, LEVEL2, LEVEL3 (06_ALERT_RULES 섹션 2)
- AlertState: 한 alert_key(node_id, metric) 의 현재 상태 (in-memory)
- AlertTransition: 상태 전환 이벤트 (발행은 #57)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class AlertLevel(str, Enum):
    NORMAL = "normal"
    LEVEL1 = "level1_caution"
    LEVEL2 = "level2_warning"
    LEVEL3 = "level3_critical"

    @property
    def numeric(self) -> int:
        return {self.NORMAL: 0, self.LEVEL1: 1, self.LEVEL2: 2, self.LEVEL3: 3}[self]

    @classmethod
    def from_numeric(cls, n: int) -> "AlertLevel":
        for member in cls:
            if member.numeric == n:
                return member
        raise ValueError(f"no AlertLevel with numeric={n}")


@dataclass
class AlertState:
    """alert_key 별 경보 상태. 메모리 전용(영속성은 #87)."""

    current_level: AlertLevel = AlertLevel.NORMAL
    enter_started_at: datetime | None = None
    exit_started_at: datetime | None = None


class AlertTransition(BaseModel):
    """경보 상태 전환 이벤트. evaluate() 가 반환하며, #57 이 발행한다."""

    node_id: str
    metric: str
    from_level: AlertLevel
    to_level: AlertLevel
    value: float
    threshold: float
    timestamp: datetime
