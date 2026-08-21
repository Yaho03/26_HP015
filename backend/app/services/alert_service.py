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


def get_evaluator() -> AlertEvaluator | None:
    return _evaluator


async def reload() -> None:
    """thresholds 업데이트 시 (PUT /api/thresholds) evaluator 재초기화."""
    await init()


def restore_active_alert_rows(rows: list) -> int:
    """DB 최신 행으로 AlertEvaluator의 현재 level을 복구한다 (#196).

    발행 측 상태와 같은 DB snapshot을 사용해야 두 메모리 상태가 서로 다른
    시점을 보지 않는다. connection_lost처럼 임계값 판정기 소관이 아닌 경보는
    AlertEvaluator.restore_active_state()가 건너뛴다.
    """
    if _evaluator is None:
        logger.warning("evaluator not initialized, skipping active alert restore")
        return 0
    recovered = 0
    for row in rows:
        try:
            node_id = row.get("source_node_id")
            alert_key = row.get("alert_key")
            level_str = row.get("level")
            status = row.get("status")
            if not (node_id and alert_key and level_str and status):
                continue
            if status != "active":
                continue
            if _evaluator.restore_active_state(
                node_id, alert_key, AlertLevel(level_str)
            ):
                recovered += 1
        except (AttributeError, TypeError, ValueError, KeyError):
            continue
    logger.info("restored %d evaluator alert state(s) from alert_events", recovered)
    return recovered
