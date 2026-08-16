"""이슈 #57: 경보 이벤트 발행 — TDD 테스트.

검증 범위:
1. AlertEventPublisher 모듈 정의
2. ENTER transition → active event (status=active, resolved_at=None)
3. EXIT to NORMAL → resolved event (status=resolved, resolved_at 채워짐)
4. alert_id: 같은 (node_id, alert_key) active 동안 유지
5. message_id, alert_id: ULID 포맷
6. MQTT 발행: alerts/events/{node_id}, alerts/state/{node_id}/{alert_key}
7. DB INSERT: alert_events 테이블
8. alert-event.schema.json 준수
9. alert_type 매핑: gas_threshold, o2_low, o2_high 등
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from jsonschema import validate, ValidationError, FormatChecker

from app.models.alert import AlertLevel, AlertTransition

SCHEMA_PATH = Path(__file__).resolve().parent.parent.parent / "schemas" / "alert-event.schema.json"


def _transition(
    *, from_level: AlertLevel = AlertLevel.NORMAL,
    to_level: AlertLevel = AlertLevel.LEVEL1,
    metric: str = "co2_ppm",
    value: float = 1100.0,
    threshold: float = 1000.0,
) -> AlertTransition:
    return AlertTransition(
        node_id="sensor-01",
        metric=metric,
        from_level=from_level,
        to_level=to_level,
        value=value,
        threshold=threshold,
        timestamp=datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc),
    )


def _make_async_persist(store):
    async def _f(e):
        store.append(("db", e))
    return _f


async def _async_noop(*args, **kwargs):
    pass


# ============================================================
# 1. 모듈 정의
# ============================================================

def test_publisher_module_importable():
    from app.services import alert_publisher
    assert hasattr(alert_publisher, "AlertEventPublisher")
    assert hasattr(alert_publisher, "publish_transition")


# ============================================================
# 2. ENTER → active event
# ============================================================

@pytest.mark.asyncio
async def test_enter_transition_produces_active_event(monkeypatch):
    from app.services import alert_publisher

    publisher = alert_publisher.AlertEventPublisher(mqtt_client=None)
    events: list[Any] = []
    monkeypatch.setattr(publisher, "_persist_event", _make_async_persist(events))
    monkeypatch.setattr(publisher, "_publish_mqtt", lambda topic, payload, retain: events.append(("mqtt", topic, payload, retain)))

    await publisher.publish_transition(_transition(to_level=AlertLevel.LEVEL1))

    db_events = [e for e in events if e[0] == "db"]
    assert len(db_events) == 1
    event = db_events[0][1]
    assert event["status"] == "active"
    assert event["resolved_at"] is None
    assert event["level"] == "level1_caution"
    assert event["source_node_id"] == "sensor-01"
    assert event["alert_key"] == "co2_ppm"


@pytest.mark.asyncio
async def test_enter_event_uses_alert_type_mapping(monkeypatch):
    from app.services import alert_publisher

    publisher = alert_publisher.AlertEventPublisher(mqtt_client=None)
    monkeypatch.setattr(publisher, "_persist_event", _async_noop)
    monkeypatch.setattr(publisher, "_publish_mqtt", lambda *a, **kw: None)

    await publisher.publish_transition(_transition(metric="co2_ppm", to_level=AlertLevel.LEVEL1))
    assert publisher.last_event["alert_type"] == "gas_threshold"

    await publisher.publish_transition(_transition(metric="o2_low", to_level=AlertLevel.LEVEL1))
    assert publisher.last_event["alert_type"] == "o2_low"

    await publisher.publish_transition(_transition(metric="o2_high", to_level=AlertLevel.LEVEL1))
    assert publisher.last_event["alert_type"] == "o2_high"


# ============================================================
# 3. EXIT to NORMAL → resolved event
# ============================================================

@pytest.mark.asyncio
async def test_exit_to_normal_produces_resolved_event(monkeypatch):
    from app.services import alert_publisher

    publisher = alert_publisher.AlertEventPublisher(mqtt_client=None)
    monkeypatch.setattr(publisher, "_persist_event", _async_noop)
    monkeypatch.setattr(publisher, "_publish_mqtt", lambda *a, **kw: None)

    # 먼저 ENTER
    await publisher.publish_transition(_transition(to_level=AlertLevel.LEVEL1))
    active_alert_id = publisher.last_event["alert_id"]

    # EXIT to NORMAL
    await publisher.publish_transition(
        _transition(
            from_level=AlertLevel.LEVEL1,
            to_level=AlertLevel.NORMAL,
            threshold=900.0,
        )
    )
    resolved_event = publisher.last_event
    assert resolved_event["status"] == "resolved"
    assert resolved_event["resolved_at"] is not None
    assert resolved_event["alert_id"] == active_alert_id, "같은 alert_id 유지"


@pytest.mark.asyncio
async def test_escalation_keeps_same_alert_id(monkeypatch):
    """L1→L2 escalation 시 같은 alert_id 유지 (status=active)."""
    from app.services import alert_publisher

    publisher = alert_publisher.AlertEventPublisher(mqtt_client=None)
    monkeypatch.setattr(publisher, "_persist_event", _async_noop)
    monkeypatch.setattr(publisher, "_publish_mqtt", lambda *a, **kw: None)

    await publisher.publish_transition(_transition(to_level=AlertLevel.LEVEL1))
    l1_alert_id = publisher.last_event["alert_id"]

    await publisher.publish_transition(
        _transition(from_level=AlertLevel.LEVEL1, to_level=AlertLevel.LEVEL2, value=2100.0, threshold=2000.0)
    )
    l2_event = publisher.last_event
    assert l2_event["alert_id"] == l1_alert_id, "escalation 시 alert_id 유지"
    assert l2_event["status"] == "active"
    assert l2_event["level"] == "level2_warning"


# ============================================================
# 4. ULID 포맷
# ============================================================

@pytest.mark.asyncio
async def test_message_id_and_alert_id_are_ulid(monkeypatch):
    from app.services import alert_publisher
    import re

    publisher = alert_publisher.AlertEventPublisher(mqtt_client=None)
    monkeypatch.setattr(publisher, "_persist_event", _async_noop)
    monkeypatch.setattr(publisher, "_publish_mqtt", lambda *a, **kw: None)

    await publisher.publish_transition(_transition(to_level=AlertLevel.LEVEL1))

    ulid_pattern = re.compile(r"^[0-7][0-9A-HJKMNP-TV-Z]{25}$")
    assert ulid_pattern.match(publisher.last_event["message_id"])
    assert ulid_pattern.match(publisher.last_event["alert_id"])


# ============================================================
# 4-1. resolved-only 오발행 방지 (이슈 #111 P2 후속)
# ============================================================

@pytest.mark.asyncio
async def test_resolved_only_transition_skipped_when_no_active_alert(monkeypatch):
    """to_level=NORMAL인데 해당 (node_id, metric)이 active로 추적된 적 없으면
    발행하지 않는다. connection_lost가 LWT/명시적 offline처럼 timeout 경보를
    띄운 적 없는 상태에서 복귀해도 무조건 NORMAL transition이 만들어지므로,
    publisher 단에서 "진짜 해제할 게 있었는지"로 최종 필터링해야 한다."""
    from app.services import alert_publisher

    publisher = alert_publisher.AlertEventPublisher(mqtt_client=None)
    persist_calls: list[Any] = []
    mqtt_calls: list[Any] = []

    async def _fake_persist(event):
        persist_calls.append(event)
    monkeypatch.setattr(publisher, "_persist_event", _fake_persist)
    monkeypatch.setattr(publisher, "_publish_mqtt", lambda *a, **kw: mqtt_calls.append(a))

    transition = _transition(
        from_level=AlertLevel.LEVEL3, to_level=AlertLevel.NORMAL, metric="connection_lost",
    )
    await publisher.publish_transition(transition)

    assert persist_calls == [], "active 경보가 없었으면 DB에 아무것도 써선 안 됨"
    assert mqtt_calls == [], "active 경보가 없었으면 MQTT도 발행하면 안 됨 (retain 오염 방지)"
    assert publisher.last_event is None


@pytest.mark.asyncio
async def test_resolved_transition_published_when_active_alert_exists(monkeypatch):
    """반대로, 진짜 active 경보가 있었으면(ENTER를 먼저 거쳤으면) 정상적으로
    resolved 이벤트를 발행해야 한다 — 기존 계약(조건 유지) 회귀 방지."""
    from app.services import alert_publisher

    publisher = alert_publisher.AlertEventPublisher(mqtt_client=None)
    monkeypatch.setattr(publisher, "_persist_event", _async_noop)
    monkeypatch.setattr(publisher, "_publish_mqtt", lambda *a, **kw: None)

    await publisher.publish_transition(
        _transition(to_level=AlertLevel.LEVEL3, metric="connection_lost")
    )
    await publisher.publish_transition(
        _transition(from_level=AlertLevel.LEVEL3, to_level=AlertLevel.NORMAL, metric="connection_lost")
    )

    assert publisher.last_event["status"] == "resolved"
    assert publisher.last_event["alert_key"] == "connection_lost"


# ============================================================
# 5. MQTT 발행 — 두 토픽
# ============================================================

@pytest.mark.asyncio
async def test_mqtt_publishes_events_and_state_topics(monkeypatch):
    from app.services import alert_publisher

    publisher = alert_publisher.AlertEventPublisher(mqtt_client=None)
    mqtt_calls: list[tuple] = []
    monkeypatch.setattr(publisher, "_persist_event", _async_noop)
    monkeypatch.setattr(
        publisher, "_publish_mqtt",
        lambda topic, payload, retain: mqtt_calls.append((topic, payload, retain)),
    )

    await publisher.publish_transition(_transition(to_level=AlertLevel.LEVEL1))

    topics = [c[0] for c in mqtt_calls]
    assert "alerts/events/sensor-01" in topics
    assert "alerts/state/sensor-01/co2_ppm" in topics

    state_call = next(c for c in mqtt_calls if c[0] == "alerts/state/sensor-01/co2_ppm")
    assert state_call[2] is True, "state 토픽은 retain=True"

    events_call = next(c for c in mqtt_calls if c[0] == "alerts/events/sensor-01")
    assert events_call[2] is False, "events 토픽은 retain=False"


# ============================================================
# 6. schema 준수
# ============================================================

@pytest.mark.asyncio
async def test_event_conforms_to_schema(monkeypatch):
    from app.services import alert_publisher

    schema = json.loads(SCHEMA_PATH.read_text())
    publisher = alert_publisher.AlertEventPublisher(mqtt_client=None)
    monkeypatch.setattr(publisher, "_persist_event", _async_noop)
    monkeypatch.setattr(publisher, "_publish_mqtt", lambda *a, **kw: None)

    await publisher.publish_transition(_transition(to_level=AlertLevel.LEVEL1))
    validate(instance=publisher.last_event, schema=schema, format_checker=FormatChecker())


@pytest.mark.asyncio
async def test_resolved_event_conforms_to_schema(monkeypatch):
    from app.services import alert_publisher

    schema = json.loads(SCHEMA_PATH.read_text())
    publisher = alert_publisher.AlertEventPublisher(mqtt_client=None)
    monkeypatch.setattr(publisher, "_persist_event", _async_noop)
    monkeypatch.setattr(publisher, "_publish_mqtt", lambda *a, **kw: None)

    await publisher.publish_transition(_transition(to_level=AlertLevel.LEVEL1))
    await publisher.publish_transition(
        _transition(from_level=AlertLevel.LEVEL1, to_level=AlertLevel.NORMAL, threshold=900.0)
    )
    validate(instance=publisher.last_event, schema=schema, format_checker=FormatChecker())


# ============================================================
# 9. 이슈 #102 — TIMESTAMPTZ 회귀 방지
# ============================================================

@pytest.mark.asyncio
async def test_mqtt_timestamps_round_trip_through_fromisoformat(monkeypatch):
    """activated_at/resolved_at/published_at이 tz-aware datetime.fromisoformat()으로
    예외 없이 왕복 파싱되는지 확인한다. 수정 전에는 tz-aware datetime에 '+00:00Z'
    이중 오프셋이 붙어 fromisoformat()이 ValueError를 냈다 (이슈 #102)."""
    from app.services import alert_publisher

    publisher = alert_publisher.AlertEventPublisher(mqtt_client=None)
    monkeypatch.setattr(publisher, "_persist_event", _async_noop)
    monkeypatch.setattr(publisher, "_publish_mqtt", lambda *a, **kw: None)

    await publisher.publish_transition(_transition(to_level=AlertLevel.LEVEL1))
    active = publisher.last_event
    datetime.fromisoformat(active["activated_at"].replace("Z", "+00:00"))
    datetime.fromisoformat(active["published_at"].replace("Z", "+00:00"))
    assert active["resolved_at"] is None

    await publisher.publish_transition(
        _transition(from_level=AlertLevel.LEVEL1, to_level=AlertLevel.NORMAL, threshold=900.0)
    )
    resolved = publisher.last_event
    datetime.fromisoformat(resolved["resolved_at"].replace("Z", "+00:00"))


@pytest.mark.asyncio
async def test_persist_event_receives_datetime_not_str(monkeypatch):
    """_persist_event()에 넘어가는 시각 필드가 str이 아니라 datetime 객체여야
    asyncpg가 TIMESTAMPTZ 컬럼에 바인딩할 수 있다 (str을 넘기면 DataError)."""
    from app.services import alert_publisher

    publisher = alert_publisher.AlertEventPublisher(mqtt_client=None)
    captured: list[dict] = []

    async def _capture(event):
        captured.append(event)

    monkeypatch.setattr(publisher, "_persist_event", _capture)
    monkeypatch.setattr(publisher, "_publish_mqtt", lambda *a, **kw: None)

    await publisher.publish_transition(_transition(to_level=AlertLevel.LEVEL1))

    persisted = captured[0]
    assert isinstance(persisted["activated_at"], datetime)
    assert isinstance(persisted["published_at"], datetime)
    assert persisted["resolved_at"] is None


# ============================================================
# 7. DB 영속성 — alert_events 테이블 INSERT
# ============================================================

class _FakeTx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeConn:
    def __init__(self):
        self.executed: list[tuple[str, tuple]] = []

    async def execute(self, sql: str, *args):
        self.executed.append((sql, args))
        return "INSERT 0 1"

    def transaction(self):
        return _FakeTx()


class FakePool:
    def __init__(self, conn):
        self._conn = conn

    class _Acquired:
        def __init__(self, conn):
            self._conn = conn

        async def __aenter__(self):
            return self._conn

        async def __aexit__(self, *exc):
            return False

    def acquire(self):
        return self._Acquired(self._conn)


@pytest.mark.asyncio
async def test_event_persisted_to_alert_events_table(monkeypatch):
    from app.services import alert_publisher
    from app.db import _pool as _

    conn = FakeConn()
    pool = FakePool(conn)
    monkeypatch.setattr(alert_publisher, "get_pool", lambda: pool)

    publisher = alert_publisher.AlertEventPublisher(mqtt_client=None)
    monkeypatch.setattr(publisher, "_publish_mqtt", lambda *a, **kw: None)
    await publisher.publish_transition(_transition(to_level=AlertLevel.LEVEL1))

    insert_calls = [s for s, _ in conn.executed if "INSERT INTO ALERT_EVENTS" in s.upper()]
    assert len(insert_calls) >= 1


# ============================================================
# 8. alert_service 통합 — _handle_transition 이 publisher 호출
# ============================================================

@pytest.mark.asyncio
async def test_alert_service_uses_publisher(monkeypatch):
    from app.services import alert_publisher, alert_service

    publisher_calls: list[Any] = []

    class _FP:
        async def publish_transition(self, t):
            publisher_calls.append(t)

    # alert_service 는 자체 참조를 두지 않고 alert_publisher 의 현재 publisher 를
    # 매번 찾는다 (이슈 #118).
    monkeypatch.setattr(alert_publisher, "_publisher", _FP())

    await alert_service._handle_transition(_transition(to_level=AlertLevel.LEVEL1))

    assert len(publisher_calls) == 1
