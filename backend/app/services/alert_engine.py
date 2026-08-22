"""시간 기반 경보 판정 엔진 (이슈 #54).

06_ALERT_RULES 섹션 3 (시간 기반 판정) 구현.

핵심 규칙:
- value 가 상위 level 의 enter_threshold 조건 만족 → enter_started_at 시작
  → enter_for_ms 경과 시 ENTER 전환 (enter_for_ms=0 이면 즉시)
- value 가 현재 level 의 exit_threshold 회귀 → exit_started_at 시작
  → exit_for_ms 경과 시 한 단계 하향 (#55 De-escalation 기본 동작 포함)
- 값이 oscillation 시 타이머 리셋 (플리커링 방지, Hysteresis)

Hysteresis: enter/exit 임계값 분리 (06_ALERT_RULES 섹션 3.2).
단계적 하향: 한 번에 한 단계씩만 (L3→L2→L1→Normal).

alert_key = (node_id, metric). o2_low/o2_high 는 metric 이름으로 분리되어
별도 alert_key 로 추적됨 (#56 지원).
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, Tuple

from app.models.alert import AlertLevel, AlertState, AlertTransition
from app.models.threshold import Threshold, ThresholdDirection


def _meets_enter_condition(value: float, threshold: Threshold) -> bool:
    if threshold.direction == ThresholdDirection.BELOW:
        return value < threshold.enter_threshold
    return value >= threshold.enter_threshold


def _meets_exit_condition(value: float, threshold: Threshold) -> bool:
    if threshold.direction == ThresholdDirection.BELOW:
        return value >= threshold.exit_threshold
    return value < threshold.exit_threshold


def _ms_elapsed(start: datetime, now: datetime) -> int:
    return int((now - start).total_seconds() * 1000)


class AlertEvaluator:
    """경보 판정 엔진. alert_key → AlertState in-memory dict 유지.

    thresholds: metric → Threshold 리스트 (LEVEL1/2/3 순 정렬 가정).
    """

    def __init__(self, thresholds: Dict[str, List[Threshold]]) -> None:
        self._thresholds = thresholds
        self._states: Dict[Tuple[str, str], AlertState] = {}

    def get_state(self, node_id: str, metric: str) -> AlertState:
        key = (node_id, metric)
        if key not in self._states:
            self._states[key] = AlertState()
        return self._states[key]

    def node_levels(self) -> Dict[str, AlertLevel]:
        """노드별 현재 최고 경보 등급 (normal 인 노드는 제외).

        alert_key 는 (node_id, metric) 단위지만, 위험 구역은 **지점** 단위다 —
        한 노드에서 CO2 가 L2 고 H2S 가 L1 이면 그 자리는 L2 로 취급해야 한다.

        읽기 전용이다. get_state() 는 없는 키를 만들어내므로 순회에 쓸 수 없다.
        """
        out: Dict[str, AlertLevel] = {}
        for (node_id, _metric), state in self._states.items():
            if state.current_level == AlertLevel.NORMAL:
                continue
            known = out.get(node_id)
            if known is None or state.current_level.numeric > known.numeric:
                out[node_id] = state.current_level
        return out

    def restore_active_state(
        self, node_id: str, metric: str, level: AlertLevel
    ) -> bool:
        """DB에 남은 활성 경보를 판정 상태로 복구한다 (#196).

        임계값이 없는 alert_key(connection_lost 등)는 이 판정기가 담당하지
        않으므로 복구하지 않는다. 이미 active인 level을 바로 넣고 모든 pending
        timer를 비운다. 다음 샘플이 같은 level이면 재진입하지 않고, 상향/하향이
        필요할 때만 그 시점부터 새 timer를 시작한다.
        """
        if metric not in self._thresholds or level == AlertLevel.NORMAL:
            return False
        state = self.get_state(node_id, metric)
        state.current_level = level
        state.enter_started_at = None
        state.enter_pending_level = None
        state.exit_started_at = None
        return True

    async def evaluate(
        self,
        node_id: str,
        metric: str,
        value: float,
        now: datetime,
    ) -> Optional[AlertTransition]:
        """측정값을 평가해 transition 반환 (없으면 None)."""
        levels = self._thresholds.get(metric)
        if not levels:
            return None

        sorted_levels = sorted(levels, key=lambda t: t.level.value)
        state = self.get_state(node_id, metric)

        desired_level = self._desired_level_for_value(value, sorted_levels)
        return self._update_state(node_id, metric, value, now, state, desired_level, sorted_levels)

    def _desired_level_for_value(
        self, value: float, sorted_levels: List[Threshold]
    ) -> AlertLevel:
        """측정값이 즉시 진입 조건을 만족하는 가장 높은 level 반환.
        아무 조건도 만족 안 하면 NORMAL."""
        highest = AlertLevel.NORMAL
        for threshold in sorted_levels:
            if _meets_enter_condition(value, threshold):
                if threshold.level.numeric > highest.numeric:
                    highest = threshold.level
        return highest

    def _update_state(
        self,
        node_id: str,
        metric: str,
        value: float,
        now: datetime,
        state: AlertState,
        desired_level: AlertLevel,
        sorted_levels: List[Threshold],
    ) -> Optional[AlertTransition]:
        # ----- ESCALATION (desired > current) -----
        if desired_level.numeric > state.current_level.numeric:
            target_threshold = self._find_threshold(sorted_levels, desired_level)
            if target_threshold and target_threshold.enter_for_ms == 0:
                return self._do_enter(node_id, metric, value, now, state, desired_level, target_threshold)

            # desired_level이 이전 샘플과 다른 level로 바뀌었으면(예: L1 → L3 급등),
            # 이전 level을 향해 쌓인 경과시간을 새 level에 재사용하면 안 되므로
            # 타이머를 새로 시작한다 (이슈 #108).
            if state.enter_pending_level != desired_level:
                state.enter_started_at = now
                state.enter_pending_level = desired_level
                state.exit_started_at = None
            elif _ms_elapsed(state.enter_started_at, now) >= target_threshold.enter_for_ms:
                return self._do_enter(node_id, metric, value, now, state, desired_level, target_threshold)
            return None

        # ----- DE-ESCALATION candidate (desired < current) -----
        if desired_level.numeric < state.current_level.numeric and state.current_level != AlertLevel.NORMAL:
            current_threshold = self._find_threshold(sorted_levels, state.current_level)
            if current_threshold is None:
                return None

            if _meets_exit_condition(value, current_threshold):
                if current_threshold.exit_for_ms == 0:
                    return self._do_exit(node_id, metric, value, now, state, current_threshold, sorted_levels)
                if state.exit_started_at is None:
                    state.exit_started_at = now
                    state.enter_started_at = None
                    state.enter_pending_level = None
                elif _ms_elapsed(state.exit_started_at, now) >= current_threshold.exit_for_ms:
                    return self._do_exit(node_id, metric, value, now, state, current_threshold, sorted_levels)
                return None
            else:
                state.exit_started_at = None
                return None

        # ----- 동일 level 유지 또는 normal 안정 -----
        state.enter_started_at = None
        state.enter_pending_level = None
        state.exit_started_at = None
        return None

    def _find_threshold(
        self, sorted_levels: List[Threshold], level: AlertLevel
    ) -> Optional[Threshold]:
        for t in sorted_levels:
            if t.level == level:
                return t
        return None

    def _do_enter(
        self,
        node_id: str,
        metric: str,
        value: float,
        now: datetime,
        state: AlertState,
        target_level: AlertLevel,
        target_threshold: Threshold,
    ) -> AlertTransition:
        from_level = state.current_level
        state.current_level = target_level
        state.enter_started_at = None
        state.enter_pending_level = None
        state.exit_started_at = None
        return AlertTransition(
            node_id=node_id,
            metric=metric,
            from_level=from_level,
            to_level=target_level,
            value=value,
            threshold=target_threshold.enter_threshold,
            timestamp=now,
        )

    def _do_exit(
        self,
        node_id: str,
        metric: str,
        value: float,
        now: datetime,
        state: AlertState,
        current_threshold: Threshold,
        sorted_levels: List[Threshold],
    ) -> AlertTransition:
        from_level = state.current_level
        target_level = AlertLevel.from_numeric(from_level.numeric - 1)
        state.current_level = target_level
        state.enter_started_at = None
        state.exit_started_at = None
        return AlertTransition(
            node_id=node_id,
            metric=metric,
            from_level=from_level,
            to_level=target_level,
            value=value,
            threshold=current_threshold.exit_threshold,
            timestamp=now,
        )
