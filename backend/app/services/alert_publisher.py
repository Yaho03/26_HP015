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
}


def _alert_type_for(metric: str) -> str:
    return _ALERT_TYPE_MAP.get(metric, "gas_threshold")


class AlertEventPublisher:
    def __init__(self, mqtt_client) -> None:
        self._mqtt = mqtt_client
        self._active_alert_ids: Dict[Tuple[str, str], Tuple[str, datetime]] = {}
        self.last_event: Optional[dict] = None

    async def publish_transition(self, transition: AlertTransition) -> None:
        event = self._build_event(transition)
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

    def _build_event(self, transition: AlertTransition) -> dict:
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
            "message": self._human_message(transition),
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
    def _human_message(transition: AlertTransition) -> str:
        direction = "진입" if transition.to_level != AlertLevel.NORMAL else "해제"
        return (
            f"{transition.metric} {transition.from_level.value}→{transition.to_level.value} "
            f"{direction}: value={transition.value:.2f}, threshold={transition.threshold:.2f}"
        )

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
