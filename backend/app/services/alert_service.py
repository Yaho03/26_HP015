"""경보 서비스 진입점 (이슈 #54).

startup 시 thresholds repository 에서 모든 임계값을 로드해 AlertEvaluator 를 초기화하고
ingest.set_alert_callback 으로 주입한다.
transition 이 발생하면 일단 로그만 남긴다 (MQTT 발행은 #57).
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime
from typing import Dict, List

from app.models.alert import AlertLevel, AlertTransition
from app.models.threshold import Threshold
from app.repositories import threshold_repository
from app.services import alert_publisher, ingest
from app.services.alert_engine import AlertEvaluator

logger = logging.getLogger(__name__)

METRIC_TO_ALERT_KEYS: Dict[str, List[str]] = {
    "o2_pct": ["o2_low", "o2_high"],
}

_evaluator: AlertEvaluator | None = None


def _group_by_metric(thresholds: List[Threshold]) -> Dict[str, List[Threshold]]:
    grouped: Dict[str, List[Threshold]] = defaultdict(list)
    for t in thresholds:
        grouped[t.metric].append(t)
    return dict(grouped)


async def init() -> None:
    """thresholds repository 에서 임계값을 로드해 evaluator 초기화."""
    global _evaluator
    thresholds = await threshold_repository.list_all()
    _evaluator = AlertEvaluator(thresholds=_group_by_metric(thresholds))
    ingest.set_alert_callback(_on_metric_ingested)
    logger.info("alert evaluator initialized with %d thresholds", len(thresholds))


async def _on_metric_ingested(
    node_id: str, metric: str, value: float, sampled_at: datetime
) -> None:
    """ingest_telemetry 에서 호출하는 콜백. METRIC_TO_ALERT_KEYS 로 매핑된 모든
    alert_key 에 대해 평가한다. 매핑이 없으면 metric 자체를 alert_key 로 사용."""
    if _evaluator is None:
        return
    alert_keys = METRIC_TO_ALERT_KEYS.get(metric, [metric])
    for alert_key in alert_keys:
        transition = await _evaluator.evaluate(node_id, alert_key, value, sampled_at)
        if transition is not None:
            await _handle_transition(transition)


async def handle_transition(transition: AlertTransition) -> None:
    """AlertTransition을 발행/브로드캐스트 경로로 전달하는 공개 API (이슈 #111).
    connection_monitor처럼 AlertEvaluator를 거치지 않고 자체적으로 transition을
    만드는 호출자가 내부 함수(_handle_transition)에 직접 접근하지 않도록 한다."""
    await _handle_transition(transition)


async def _handle_transition(transition: AlertTransition) -> None:
    logger.info(
        "alert transition: node=%s metric=%s %s→%s value=%.2f threshold=%.2f",
        transition.node_id,
        transition.metric,
        transition.from_level.value,
        transition.to_level.value,
        transition.value,
        transition.threshold,
    )
    # 모듈 함수를 통해 매번 현재 publisher 를 찾는다. 예전에는 main.py 가
    # alert_publisher._publisher 를 여기로 복사했는데, 복사 시점의 객체를 붙들고
    # 있어서 MQTT 재연결로 publisher 가 교체되면 죽은 클라이언트를 계속 썼다
    # (이슈 #118).
    #
    # 저장·발행이 실패해도 아래 WS 브로드캐스트는 반드시 실행한다. 저장이 화면
    # 경보까지 막는 것이 #102 에서 실제로 일어난 일이다.
    try:
        await alert_publisher.publish_transition(transition)
    except Exception:
        logger.exception(
            "alert publish failed (node=%s metric=%s)",
            transition.node_id, transition.metric,
        )

    try:
        from app.services.ws_manager import manager
        await manager.broadcast({
            "type": "alert",
            "node_id": transition.node_id,
            "metric": transition.metric,
            "from_level": transition.from_level.value,
            "to_level": transition.to_level.value,
            "value": transition.value,
            "threshold": transition.threshold,
            "timestamp": transition.timestamp.isoformat(),
        })
    except Exception:
        logger.exception("ws broadcast failed for transition")

    # 고정 센서의 경보 등급이 바뀌면 위험 구역도 바뀐다. 위치가 그대로여도
    # 탈출 경로를 즉시 다시 계산해야 EXP-8.1의 자동 우회가 실제 배선에서 동작한다.
    # 지연 import로 alert_service ↔ evacuation_service 순환 import를 피한다.
    try:
        from app.services import evacuation_service

        await evacuation_service.recompute_all(reason="hazard_changed")
    except Exception:
        # 경로 부가 기능의 실패가 핵심 가스 경보 발행을 되돌리면 안 된다.
        logger.exception("evacuation recompute failed after alert transition")


def get_evaluator() -> AlertEvaluator | None:
    return _evaluator


async def reload() -> None:
    """thresholds 업데이트 시 (PUT /api/thresholds) evaluator 재초기화."""
    await init()


async def recover_from_retain_messages(messages: list) -> None:
    """백엔드 재시작 시 MQTT alerts/state/# Retain 메시지로부터 활성 alert 복구 (#87).
    04_DATA_CONTRACT 199번 줄: 이미 active인 경보는 그대로 유지(timers reset 안 함)."""
    if _evaluator is None:
        logger.warning("recover_from_retain_messages called before init(), skipping")
        return
    recovered = 0
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        try:
            node_id = msg.get("source_node_id")
            alert_key = msg.get("alert_key")
            level_str = msg.get("level")
            status = msg.get("status")
            if not (node_id and alert_key and level_str and status):
                continue
            if status != "active":
                continue
            levels = _evaluator._thresholds.get(alert_key)
            if not levels:
                continue
            target_level = AlertLevel(level_str)
            state = _evaluator.get_state(node_id, alert_key)
            state.current_level = target_level
            state.enter_started_at = None
            state.exit_started_at = None
            recovered += 1
        except (ValueError, KeyError):
            continue
    logger.info("recovered %d active alerts from retain messages", recovered)
