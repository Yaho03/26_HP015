"""UWB 위치 필터링 (이슈 #70).

wearable/{node_id}/location 메시지로 들어오는 (x_m, y_m, z_m) 에 대해:
1. 이상치 제거: 이전 위치에서 max_jump_m 초도 이동한 샘플은 스킵 (UWB 다중경로/반사 아티팩트 방지)
2. EMA smoothing: alpha * raw + (1-alpha) * prev 로 노이즈 감소
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class FilteredPosition:
    node_id: str
    x: float
    y: float
    z: float
    timestamp: datetime


class LocationFilter:
    def __init__(self, alpha: float = 0.3, max_jump_m: float = 1.0) -> None:
        self._alpha = alpha
        self._max_jump_m = max_jump_m
        self._last: Dict[str, FilteredPosition] = {}

    def update(
        self,
        node_id: str,
        x: float,
        y: float,
        z: float,
        timestamp: datetime,
    ) -> Optional[FilteredPosition]:
        last = self._last.get(node_id)
        if last is None:
            pos = FilteredPosition(node_id, float(x), float(y), float(z), timestamp)
            self._last[node_id] = pos
            return pos

        dist = math.sqrt((x - last.x) ** 2 + (y - last.y) ** 2 + (z - last.z) ** 2)
        if dist > self._max_jump_m:
            logger.warning(
                "location outlier rejected (node=%s dist=%.3fm max=%.3fm)",
                node_id, dist, self._max_jump_m,
            )
            return None

        nx = self._alpha * x + (1 - self._alpha) * last.x
        ny = self._alpha * y + (1 - self._alpha) * last.y
        nz = self._alpha * z + (1 - self._alpha) * last.z
        pos = FilteredPosition(node_id, nx, ny, nz, timestamp)
        self._last[node_id] = pos
        return pos
