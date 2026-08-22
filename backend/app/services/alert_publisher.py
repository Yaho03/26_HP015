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

#: 누적 노출량 경보의 alert_key (11_EXPOSURE_DOSE_SPEC.md §5.3). 전부
#: alert_type "exposure_dose" 로 묶인다.
#:
#: 이 alert_type 이 필요한 이유는 **해제 규칙이 다르기** 때문이다. 가스 농도 경보는
#: 값이 내려가면 Hysteresis 로 해제되지만, 누적값은 줄어들지 않으므로 노출량 경보에는
#: exit_threshold 개념 자체가 없다 (§5.2). 소비자(대시보드·MQTT 구독자)가 두 종류를
#: 구분하지 못하면 "왜 값이 정상인데 경보가 안 꺼지나"를 고장으로 오해한다.
EXPOSURE_ALERT_KEYS = frozenset({
    "exposure_co2", "exposure_co", "exposure_h2s", "o2_deficiency_time",
})


def _alert_type_for(alert_key: str) -> str:
    if alert_key in EXPOSURE_ALERT_KEYS:
        return "exposure_dose"
    return _ALERT_TYPE_MAP.get(alert_key, "gas_threshold")


def _key_of(transition: AlertTransition) -> Tuple[str, str]:
    """활성 경보 추적 키 — metric 이 아니라 **alert_key** 다.

    이 파일 상단의 alert_id 정책이 원래 "(node_id, alert_key)"라고 적고 있었는데
    코드는 metric 을 쓰고 있었다. 기존 경보는 alert_key == metric 이라 차이가 없었다.

    누적 노출량에서는 달라진다. 시간 누적 O2 경보(alert_key `o2_deficiency_time`)와
    순간값 경보(`o2_low`)는 **둘 다 metric 이 o2_pct** 라, metric 으로 키를 잡으면
    한쪽이 다른 쪽의 alert_id 를 가져가고 해제까지 서로 덮어쓴다. §5.4 가 "두 경보는
    독립적으로 동작하며 서로 대체하지 않는다"고 못박은 바로 그 충돌이다.
    """
    return (transition.node_id, transition.alert_key or transition.metric)


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
        key = _key_of(transition)
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
        key = _key_of(transition)
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
            "alert_key": transition.alert_key or transition.metric,
            "alert_type": _alert_type_for(transition.alert_key or transition.metric),
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
            # INSERT 와 supersede 를 한 트랜잭션에 묶는다. 중간에 끊기면 새 행만
            # 들어가고 옛 행이 active 로 남아, 고치려던 상태를 그대로 만든다.
            async with conn.transaction():
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
                await self._supersede_previous_rows(conn, event)

    @staticmethod
    async def _supersede_previous_rows(conn, event: dict) -> None:
        """같은 alert_id 의 이전 행들을 닫는다 (이슈 #194).

        한 경보(alert_id)의 등급이 바뀔 때마다 새 행이 INSERT 되는데, 이전 행은
        계속 status='active' 로 남아 있었다. 그래서 CO2 가 한 번 올랐다 내려오면
        (normal→L1→L2→L3→L2→L1→normal) 7개 행 중 6개가 active 로 고정된다.

        이게 화면에서만 지저분한 게 아니다. 두 곳이 이 컬럼을 그대로 믿는다.

        - alert_events_repository.has_active_alerts_at_or_above() — AUTH-7 이 세션
          유휴 만료를 연장할지 판단하는 근거다. 죽은 L3 행이 남아 있으면 활성
          경보가 없는데도 세션이 영원히 연장된다.
        - GET /api/alert-events?status=active — 이벤트 로그 화면의 active 필터가
          이미 해제된 경보를 계속 보여준다.

        한 alert_id 에서 active 로 남는 행은 **가장 최근 것 하나뿐**이어야 한다.
        NORMAL 전이일 때는 새 행 자체가 resolved 이므로 결과적으로 전부 닫힌다.

        status enum 은 active/resolved 둘뿐이라(alert-event.schema.json) 승격으로
        밀려난 행도 'resolved' 로 적는다. 그 등급 구간이 실제로 끝난 것은 맞다.
        """
        await conn.execute(
            """
            UPDATE alert_events
               SET status = 'resolved',
                   resolved_at = COALESCE(resolved_at, $2)
             WHERE alert_id = $1
               AND message_id <> $3
               AND status = 'active'
            """,
            event["alert_id"],
            event["published_at"],
            event["message_id"],
        )

    @staticmethod
    async def _load_latest_alert_rows() -> list:
        """키별 최신 경보 행을 한 번만 읽는다 (#194, #196)."""
        pool = get_pool()
        async with pool.acquire() as conn:
            return await conn.fetch(
                """
                SELECT DISTINCT ON (source_node_id, alert_key)
                       source_node_id, alert_key, alert_id, activated_at, status, level
                  FROM alert_events
                 ORDER BY source_node_id, alert_key, published_at DESC
                """
            )

    def restore_active_alert_rows(self, rows: list) -> int:
        """조회된 최신 행으로 발행 측 추적 상태를 복구한다."""
        restored = 0
        for row in rows:
            if row["status"] != "active":
                continue
            key = (row["source_node_id"], row["alert_key"])
            self._active_alert_ids[key] = (row["alert_id"], row["activated_at"])
            restored += 1
        logger.info("restored %d publisher alert state(s) from alert_events", restored)
        return restored

    async def restore_active_alerts(self) -> int:
        """DB 에서 활성 경보를 읽어 _active_alert_ids 를 복구한다 (이슈 #194).

        _active_alert_ids 는 메모리에만 있어서 백엔드가 재시작하면 비어 버린다.
        그런데 publish_transition() 의 #111 가드가 "추적 중인 active 경보가 없으면
        NORMAL 전이를 발행하지 않는다"로 동작한다. 두 가지가 겹치면 이렇게 된다.

            1. 경보 발생 → alert_events 에 active 행, retained 에 active 상태
            2. 백엔드 재시작 → _active_alert_ids 가 빈 딕셔너리
            3. 값이 정상 복귀 → NORMAL 전이가 가드에 걸려 **통째로 버려진다**
            4. active 행과 retained active 상태가 영구히 남는다

        2026-08-16~17 경보 6건이 며칠 뒤까지 남아 있던 것이 이 경로다. 재시작이
        경보를 영구 미해제 상태로 만드는 것은 안전 기능으로서 받아들일 수 없다.

        복구 대상은 (node_id, alert_key) 별 **가장 최근 행이 active 인 것**뿐이다.
        published_at DESC 로 최신 행을 고른 뒤 status 를 본다 — 옛 행이 active 로
        남아 있어도 최신이 resolved 면 복구하지 않는다.
        """
        rows = await self._load_latest_alert_rows()
        return self.restore_active_alert_rows(rows)

    def _publish_mqtt(self, topic: str, payload: dict, retain: bool) -> None:
        if self._mqtt is None:
            return
        import paho.mqtt.client as mqtt
        qos = 1
        info = self._mqtt.publish(topic, json.dumps(payload), qos=qos, retain=retain)
        # QoS1 은 '큐에 넣음'이지 '전달됨'이 아니다 (#239). rc 가 실패면(브로커
        # 미연결 등) 메시지는 가지 않았는데 예전엔 debug 로그 한 줄로 끝나 — 경보
        # 전달 실패가 은폐됐다. 실패는 error 로그 + 카운터로 노출한다.
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            metrics.increment("alerts_publish_failed")
            logger.error(
                "MQTT publish FAILED (topic=%s qos=%d retain=%s rc=%d) — 경보가 웨어러블/구독자에게 전달되지 않았다",
                topic, qos, retain, info.rc,
            )
        else:
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


async def restore_active_alerts() -> int:
    """기동 시 활성 경보 추적 상태를 DB 에서 복구한다 (이슈 #194).

    실패해도 기동을 막지 않는다. 복구가 안 되면 재시작 전 경보가 해제되지 않는
    문제가 남지만, 그것 때문에 서버가 아예 안 뜨면 신규 경보까지 못 받는다 —
    후자가 더 나쁘다. 대신 예외를 조용히 삼키지 않고 로그로 남긴다 (이슈 #154).
    """
    if _publisher is None:
        logger.warning("publisher not initialized, skipping active alert restore")
        return 0
    try:
        return await _publisher.restore_active_alerts()
    except Exception:
        logger.exception(
            "active alert restore failed — 재시작 전 경보가 해제되지 않을 수 있다 (이슈 #194)"
        )
        return 0


async def restore_runtime_alert_state() -> tuple[int, int]:
    """DB 한 번 조회로 발행 측과 판정 측 상태를 함께 복구한다 (#194, #196).

    실패해도 서버 기동을 막지 않는다. 복구 실패보다 신규 경보 수집 전체가
    멈추는 것이 더 위험하므로 로그를 남기고 빈 결과로 진행한다 (#154).
    """
    if _publisher is None:
        logger.warning("publisher not initialized, skipping runtime alert restore")
        return (0, 0)
    try:
        rows = await _publisher._load_latest_alert_rows()
        publisher_count = _publisher.restore_active_alert_rows(rows)

        # alert_service가 이 모듈을 import하므로 모듈 상단에서 역으로 import하면
        # 순환 초기화가 생긴다. 기동 시점의 지역 import는 두 모듈 로드가 끝난 뒤다.
        from app.services import alert_service

        evaluator_count = alert_service.restore_active_alert_rows(rows)
        return (publisher_count, evaluator_count)
    except Exception:
        logger.exception(
            "runtime alert restore failed — 재시작 전 경보가 재발화하거나 "
            "해제되지 않을 수 있다 (이슈 #194, #196)"
        )
        return (0, 0)
