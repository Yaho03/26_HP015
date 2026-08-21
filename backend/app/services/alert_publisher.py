"""경보 이벤트 발행 (이슈 #57).

AlertTransition → AlertEvent (schema 준수) 생성 후:
1. alert_events 테이블에 INSERT
2. alerts/events/{node_id} MQTT 토픽 발행 (QoS 1, retain=False)
3. alerts/state/{node_id}/{alert_key} MQTT 토픽 발행 (QoS 1, retain=True)

alert_id 정책:
- 같은 (node_id, alert_key) 가 active 동안 하나의 alert_id 유지
- to_level != NORMAL: status=active, resolved_at=None
- to_level == NORMAL: status=resolved, resolved_at=timestamp

alert_type 매핑:
- o2_low metric → alert_type="o2_low"
- o2_high metric → alert_type="o2_high"
- 그 외 가스 metric → alert_type="gas_threshold"
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

from ulid import ULID

from app.db import get_pool
from app.models.alert import AlertLevel, AlertTransition
from app.observability import metrics
from app.utils import to_iso_z

logger = logging.getLogger(__name__)

_ALERT_TYPE_MAP = {
    "o2_low": "o2_low",
    "o2_high": "o2_high",
    # 가스 임계값이 아니라 상황 자체가 경보다 — 안전한 대피 경로가 사라졌다
    # (FR-803, 12_EVACUATION_ROUTE_SPEC §3.5). gas_threshold 로 분류되면
    # 대시보드가 센서 경보와 섞어 보여준다.
    "no_safe_route": "evacuation",
}


def _alert_type_for(metric: str) -> str:
    return _ALERT_TYPE_MAP.get(metric, "gas_threshold")


class AlertEventPublisher:
    def __init__(self, mqtt_client) -> None:
        self._mqtt = mqtt_client
        self._active_alert_ids: Dict[Tuple[str, str], Tuple[str, datetime]] = {}
        self.last_event: Optional[dict] = None

    async def publish_transition(self, transition: AlertTransition) -> None:
        # to_level==NORMAL인데 해당 (node_id, metric)에 대해 active 상태로 추적 중인
        # 경보가 없으면 발행하지 않는다 (이슈 #111 P2 후속) — connection_lost는
        # offline이 timeout(connection_monitor가 실제로 L3 경보를 띄운 경우)이든
        # LWT/명시적 offline(경보를 띄운 적 없는 경우)이든 상관없이 ingest_connection이
        # offline→online 전이만 보고 무조건 NORMAL transition을 만들어 보내므로,
        # 여기서 "진짜 해제할 active 경보가 있었는지"를 최종적으로 걸러줘야 한다.
        # 이 가드는 connection_lost뿐 아니라 모든 metric의 resolved-only 오발행을
        # 막아준다 (active_alert_ids에 없으면 애초에 해제할 게 없다는 뜻이므로).
        key = (transition.node_id, transition.metric)
        if transition.to_level == AlertLevel.NORMAL and key not in self._active_alert_ids:
            logger.debug(
                "skipping resolved-only publish, no active alert tracked for %s", key
            )
            return

        worker = await self._assigned_worker(transition)
        event = self._build_event(transition, worker)
        await self._persist_event(event)
        wire_event = self._to_wire(event)
        self.last_event = wire_event
        self._publish_mqtt(f"alerts/events/{transition.node_id}", wire_event, retain=False)
        self._publish_mqtt(
            f"alerts/state/{transition.node_id}/{transition.metric}",
            wire_event,
            retain=True,
        )
        if wire_event["status"] == "active":
            metrics.increment("alerts_published")
        else:
            metrics.increment("alerts_resolved")

    @staticmethod
    async def _assigned_worker(transition: AlertTransition):
        """경보 발생 시각에 이 노드를 착용하던 작업자 (이슈 #136).

        조회는 경보 발행을 막을 수 없다. 명부가 비어 있든 DB 가 흔들리든 경보는
        나가야 한다 — 이름을 못 붙이는 것과 경보를 못 보내는 것은 위험도가 다르다.
        실패하면 None 으로 떨어져 예전처럼 노드 ID 만 나온다.
        """
        try:
            from app.repositories import worker_repository

            return await worker_repository.assigned_at_time(
                transition.node_id, transition.timestamp
            )
        except Exception:
            logger.exception(
                "assigned worker lookup failed for %s — 경보는 노드 ID 로 계속 발행한다",
                transition.node_id,
            )
            return None

    def _build_event(self, transition: AlertTransition, worker=None) -> dict:
        key = (transition.node_id, transition.metric)
        now = datetime.now(timezone.utc)

        if transition.to_level == AlertLevel.NORMAL:
            alert_id, activated_at = self._active_alert_ids.pop(key, (str(ULID()), transition.timestamp))
            status = "resolved"
            resolved_at = transition.timestamp
            level = transition.from_level.value
        else:
            if key in self._active_alert_ids:
                alert_id, activated_at = self._active_alert_ids[key]
            else:
                alert_id = str(ULID())
                activated_at = transition.timestamp
                self._active_alert_ids[key] = (alert_id, activated_at)
            status = "active"
            resolved_at = None
            level = transition.to_level.value

        return {
            "schema_version": "1.1",
            "message_id": str(ULID()),
            "alert_id": alert_id,
            "source_node_id": transition.node_id,
            "alert_key": transition.metric,
            "alert_type": _alert_type_for(transition.metric),
            "level": level,
            "trigger_value": transition.value,
            "threshold": transition.threshold,
            "metric": transition.metric,
            "message": self._human_message(transition, worker),
            "status": status,
            "activated_at": activated_at,
            "resolved_at": resolved_at,
            "published_at": now,
        }

    @staticmethod
    def _to_wire(event: dict) -> dict:
        """DB에 저장된 datetime 객체를 MQTT 페이로드용 ISO8601 문자열로 변환."""
        wire = dict(event)
        wire["activated_at"] = to_iso_z(event["activated_at"])
        wire["resolved_at"] = to_iso_z(event["resolved_at"]) if event["resolved_at"] else None
        wire["published_at"] = to_iso_z(event["published_at"])
        return wire

    @staticmethod
    def _human_message(transition: AlertTransition, worker=None) -> str:
        direction = "진입" if transition.to_level != AlertLevel.NORMAL else "해제"
        base = (
            f"{transition.metric} {transition.from_level.value}→{transition.to_level.value} "
            f"{direction}: value={transition.value:.2f}, threshold={transition.threshold:.2f}"
        )
        if worker is None:
            return base
        # 이슈 #136 — 관리자가 읽는 첫 줄에 사람이 있어야 대피 지시가 나간다.
        # 이 문자열은 alert_events 에 그대로 저장된다. 나중에 명부에서 이름을 고쳐도
        # 사고 기록은 당시 표기를 유지하는 편이 맞다.
        return f"{worker.name}({worker.employee_no}) — {base}"

    async def _persist_event(self, event: dict) -> None:
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO alert_events (message_id, schema_version, alert_id, source_node_id,
                                           alert_key, alert_type, level, trigger_value, threshold,
                                           metric, message, status, activated_at, resolved_at, published_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
                ON CONFLICT (message_id) DO NOTHING
                """,
                event["message_id"],
                event["schema_version"],
                event["alert_id"],
                event["source_node_id"],
                event["alert_key"],
                event["alert_type"],
                event["level"],
                event["trigger_value"],
                event["threshold"],
                event["metric"],
                event["message"],
                event["status"],
                event["activated_at"],
                event["resolved_at"],
                event["published_at"],
            )

    def _publish_mqtt(self, topic: str, payload: dict, retain: bool) -> None:
        if self._mqtt is None:
            return
        import paho.mqtt.client as mqtt
        qos = 1
        info = self._mqtt.publish(topic, json.dumps(payload), qos=qos, retain=retain)
        logger.debug("MQTT publish topic=%s qos=%d retain=%s rc=%s", topic, qos, retain, info.rc)


_publisher: Optional[AlertEventPublisher] = None


def init_publisher(mqtt_client) -> None:
    global _publisher
    _publisher = AlertEventPublisher(mqtt_client=mqtt_client)


async def publish_transition(transition: AlertTransition) -> None:
    if _publisher is None:
        logger.debug("publisher not initialized, skipping transition")
        return
    await _publisher.publish_transition(transition)
