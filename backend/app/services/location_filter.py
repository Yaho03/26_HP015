"""UWB 위치 필터링 (이슈 #70).

wearable/{node_id}/location 메시지로 들어오는 (x_m, y_m, z_m) 에 대해:
1. 이상치 제거: 마지막 수용 raw 위치/시간 기준으로 max_speed_mps 를 초과한 샘플은 스킵
   (UWB 다중경로/반사 아티팩트 방지)
2. EMA smoothing: alpha * raw + (1-alpha) * prev 로 노이즈 감소
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class FilteredPosition:
    node_id: str
    x: float
    y: float
    z: float
    timestamp: datetime


@dataclass
class RawPosition:
    node_id: str
    x: float
    y: float
    z: float
    timestamp: datetime


class LocationFilter:
    def __init__(
        self,
        alpha: float = 0.3,
        max_jump_m: Optional[float] = None,
        max_speed_mps: Optional[float] = None,
        reject_limit: int = 5,
        min_delta_seconds: float = 0.1,
    ) -> None:
        self._alpha = alpha
        self._max_speed_mps = (
            float(max_speed_mps)
            if max_speed_mps is not None
            else float(max_jump_m) if max_jump_m is not None else 2.0
        )
        self._reject_limit = reject_limit
        self._min_delta_seconds = min_delta_seconds
        self._last: Dict[str, FilteredPosition] = {}
        self._last_accepted_raw: Dict[str, RawPosition] = {}
        self._reject_counts: Dict[str, int] = {}

    def update(
        self,
        node_id: str,
        x: float,
        y: float,
        z: float,
        timestamp: datetime,
    ) -> Optional[FilteredPosition]:
        last = self._last.get(node_id)
        last_raw = self._last_accepted_raw.get(node_id)
        if last is None:
            pos = FilteredPosition(node_id, float(x), float(y), float(z), timestamp)
            self._last[node_id] = pos
            self._last_accepted_raw[node_id] = RawPosition(
                node_id, float(x), float(y), float(z), timestamp
            )
            self._reject_counts[node_id] = 0
            return pos

        # Outlier detection uses the last accepted raw sample, not the lagging EMA value.
        if last_raw is None:
            last_raw = RawPosition(node_id, last.x, last.y, last.z, last.timestamp)
        dist = math.sqrt(
            (x - last_raw.x) ** 2
            + (y - last_raw.y) ** 2
            + (z - last_raw.z) ** 2
        )
        delta_seconds = max(
            self._seconds_between(last_raw.timestamp, timestamp),
            self._min_delta_seconds,
        )
        max_allowed_m = self._max_speed_mps * delta_seconds
        if dist > max_allowed_m:
            reject_count = self._reject_counts.get(node_id, 0) + 1
            self._reject_counts[node_id] = reject_count
            if reject_count >= self._reject_limit:
                pos = FilteredPosition(node_id, float(x), float(y), float(z), timestamp)
                self._last[node_id] = pos
                self._last_accepted_raw[node_id] = RawPosition(
                    node_id, float(x), float(y), float(z), timestamp
                )
                self._reject_counts[node_id] = 0
                logger.warning(
                    "location filter rebased after consecutive rejections "
                    "(node=%s count=%d dist=%.3fm allowed=%.3fm)",
                    node_id, reject_count, dist, max_allowed_m,
                )
                return pos
            logger.warning(
                "location outlier rejected "
                "(node=%s dist=%.3fm allowed=%.3fm dt=%.3fs "
                "speed=%.3fm/s max=%.3fm/s count=%d)",
                node_id,
                dist,
                max_allowed_m,
                delta_seconds,
                dist / delta_seconds,
                self._max_speed_mps,
                reject_count,
            )
            return None

        nx = self._alpha * x + (1 - self._alpha) * last.x
        ny = self._alpha * y + (1 - self._alpha) * last.y
        nz = self._alpha * z + (1 - self._alpha) * last.z
        pos = FilteredPosition(node_id, nx, ny, nz, timestamp)
        self._last[node_id] = pos
        self._last_accepted_raw[node_id] = RawPosition(
            node_id, float(x), float(y), float(z), timestamp
        )
        self._reject_counts[node_id] = 0
        return pos

    def latest(self, node_id: str) -> Optional[FilteredPosition]:
        """마지막으로 채택된 필터링 위치. 없으면 None.

        노출량 적산이 최근접 센서 노드를 정할 때 쓴다 (ADR-008). 위치를 모르면
        **추측하지 않고** 출처 없음으로 내려간다 — 잘못된 노드의 농도를 작업자에게
        귀속시키느니 산출 불가가 낫다.

        오래된 값인지는 호출부가 timestamp 를 보고 판단한다. 여기서 임의의 유효기간을
        정하면 그 숫자가 곧 하드코딩된 임계값이 된다.
        """
        return self._last.get(node_id)

    @staticmethod
    def _seconds_between(previous: datetime, current: datetime) -> float:
        if previous.tzinfo is None and current.tzinfo is not None:
            previous = previous.replace(tzinfo=timezone.utc)
        elif previous.tzinfo is not None and current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        return max((current - previous).total_seconds(), 0.0)
