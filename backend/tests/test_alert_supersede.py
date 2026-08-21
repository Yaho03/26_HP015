"""이슈 #194: 경보 해제 시 alert_events active 행이 남는 문제.

두 가지 결함을 잠근다.

1. 한 alert_id 의 등급이 바뀔 때마다 새 행이 INSERT 되는데 이전 행이 계속
   status='active' 로 남았다. has_active_alerts_at_or_above()(AUTH-7 세션 유휴
   연장)와 GET /api/alert-events?status=active 가 이 컬럼을 그대로 믿는다.

2. _active_alert_ids 가 메모리에만 있어서, 백엔드 재시작 뒤 NORMAL 전이가
   publish_transition 의 #111 가드에 걸려 통째로 버려졌다. 재시작 전에 뜬 경보가
   영구 미해제로 남는 경로다.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from app.models.alert import AlertLevel, AlertTransition

TS = datetime(2026, 8, 21, 12, 0, 0, tzinfo=timezone.utc)


def _transition(
    *,
    from_level: AlertLevel = AlertLevel.NORMAL,
    to_level: AlertLevel = AlertLevel.LEVEL1,
    metric: str = "co2_ppm",
    node_id: str = "sensor-01",
    value: float = 1100.0,
    threshold: float = 1000.0,
) -> AlertTransition:
    return AlertTransition(
        node_id=node_id,
        metric=metric,
        from_level=from_level,
        to_level=to_level,
        value=value,
        threshold=threshold,
        timestamp=TS,
    )


class _FakeTx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeConn:
    def __init__(self, fetch_rows: list | None = None):
        self.executed: list[tuple[str, tuple]] = []
        self._fetch_rows = fetch_rows or []

    def transaction(self):
        return _FakeTx()

    async def execute(self, sql: str, *args):
        self.executed.append((sql, args))

    async def fetch(self, sql: str, *args):
        self.executed.append((sql, args))
        return self._fetch_rows

    def sql_containing(self, needle: str) -> list[tuple[str, tuple]]:
        return [(s, a) for s, a in self.executed if needle in s]


class FakePool:
    def __init__(self, conn):
        self._conn = conn

    class _A:
        def __init__(self, conn):
            self._conn = conn

        async def __aenter__(self):
            return self._conn

        async def __aexit__(self, *e):
            return False

    def acquire(self):
        return FakePool._A(self._conn)


# ============================================================
# 1. supersede — 이전 행을 닫는다
# ============================================================


@pytest.mark.asyncio
async def test_persist_supersedes_previous_rows_of_same_alert_id(monkeypatch):
    """INSERT 와 함께 같은 alert_id 의 이전 active 행을 resolved 로 닫아야 한다."""
    from app.services import alert_publisher

    conn = FakeConn()
    monkeypatch.setattr(alert_publisher, "get_pool", lambda: FakePool(conn))

    publisher = alert_publisher.AlertEventPublisher(mqtt_client=None)
    monkeypatch.setattr(publisher, "_publish_mqtt", lambda *a, **k: None)
    monkeypatch.setattr(publisher, "_assigned_worker", _async_none)

    await publisher.publish_transition(_transition(to_level=AlertLevel.LEVEL1))

    updates = conn.sql_containing("UPDATE alert_events")
    assert len(updates) == 1, "INSERT 후 이전 행을 닫는 UPDATE 가 없다"

    sql, args = updates[0]
    assert "status = 'resolved'" in sql
    assert "message_id <> " in sql, "새로 넣은 행까지 닫으면 안 된다"
    assert "status = 'active'" in sql, "이미 resolved 인 행의 resolved_at 을 덮어쓰면 안 된다"
    # args = (alert_id, published_at, message_id)
    assert len(args) == 3


@pytest.mark.asyncio
async def test_persist_runs_insert_and_update_in_one_transaction(monkeypatch):
    """중간에 끊기면 새 행만 남고 옛 행이 active 로 남아 고치려던 상태가 된다."""
    from app.services import alert_publisher

    entered: list[str] = []

    class TxTrackingConn(FakeConn):
        def transaction(self):
            entered.append("tx")
            return _FakeTx()

    conn = TxTrackingConn()
    monkeypatch.setattr(alert_publisher, "get_pool", lambda: FakePool(conn))

    publisher = alert_publisher.AlertEventPublisher(mqtt_client=None)
    monkeypatch.setattr(publisher, "_publish_mqtt", lambda *a, **k: None)
    monkeypatch.setattr(publisher, "_assigned_worker", _async_none)

    await publisher.publish_transition(_transition(to_level=AlertLevel.LEVEL2))

    assert entered, "INSERT/UPDATE 가 트랜잭션 밖에서 실행된다"
    assert conn.sql_containing("INSERT INTO alert_events")
    assert conn.sql_containing("UPDATE alert_events")


@pytest.mark.asyncio
async def test_escalation_chain_keeps_only_latest_row_active(monkeypatch):
    """normal→L1→L2→L3 각 단계마다 직전 행을 닫는 UPDATE 가 나가야 한다."""
    from app.services import alert_publisher

    conn = FakeConn()
    monkeypatch.setattr(alert_publisher, "get_pool", lambda: FakePool(conn))

    publisher = alert_publisher.AlertEventPublisher(mqtt_client=None)
    monkeypatch.setattr(publisher, "_publish_mqtt", lambda *a, **k: None)
    monkeypatch.setattr(publisher, "_assigned_worker", _async_none)

    await publisher.publish_transition(
        _transition(from_level=AlertLevel.NORMAL, to_level=AlertLevel.LEVEL1)
    )
    await publisher.publish_transition(
        _transition(from_level=AlertLevel.LEVEL1, to_level=AlertLevel.LEVEL2)
    )
    await publisher.publish_transition(
        _transition(from_level=AlertLevel.LEVEL2, to_level=AlertLevel.LEVEL3)
    )

    inserts = conn.sql_containing("INSERT INTO alert_events")
    updates = conn.sql_containing("UPDATE alert_events")
    assert len(inserts) == 3
    assert len(updates) == 3, "단계가 오를 때마다 이전 행을 닫아야 한다"

    # 세 전이 모두 같은 alert_id 를 공유한다 → UPDATE 의 첫 인자가 동일하다
    alert_ids = {args[0] for _, args in updates}
    assert len(alert_ids) == 1, "같은 경보인데 alert_id 가 갈라졌다"


# ============================================================
# 2. 재시작 복구 — _active_alert_ids 를 DB 에서 되살린다
# ============================================================


@pytest.mark.asyncio
async def test_restore_active_alerts_rehydrates_tracking(monkeypatch):
    from app.services import alert_publisher

    rows = [
        {
            "source_node_id": "sensor-01",
            "alert_key": "co2_ppm",
            "alert_id": "01AAAAAAAAAAAAAAAAAAAAAAAA",
            "activated_at": TS,
            "status": "active",
        },
        {
            "source_node_id": "sensor-02",
            "alert_key": "co2_ppm",
            "alert_id": "01BBBBBBBBBBBBBBBBBBBBBBBB",
            "activated_at": TS,
            "status": "resolved",
        },
    ]
    conn = FakeConn(fetch_rows=rows)
    monkeypatch.setattr(alert_publisher, "get_pool", lambda: FakePool(conn))

    publisher = alert_publisher.AlertEventPublisher(mqtt_client=None)
    restored = await publisher.restore_active_alerts()

    assert restored == 1, "최신 행이 resolved 인 경보까지 되살리면 안 된다"
    assert ("sensor-01", "co2_ppm") in publisher._active_alert_ids
    assert ("sensor-02", "co2_ppm") not in publisher._active_alert_ids

    alert_id, activated_at = publisher._active_alert_ids[("sensor-01", "co2_ppm")]
    assert alert_id == "01AAAAAAAAAAAAAAAAAAAAAAAA"
    assert activated_at == TS


@pytest.mark.asyncio
async def test_resolve_after_restart_is_not_swallowed(monkeypatch):
    """재시작 뒤 NORMAL 전이가 #111 가드에 걸려 버려지면 안 된다.

    이게 2026-08-16~17 경보가 며칠 뒤까지 남아 있던 경로다. 복구가 없으면
    _active_alert_ids 가 비어 있어 해제가 통째로 사라진다.
    """
    from app.services import alert_publisher

    rows = [
        {
            "source_node_id": "sensor-01",
            "alert_key": "co2_ppm",
            "alert_id": "01AAAAAAAAAAAAAAAAAAAAAAAA",
            "activated_at": TS,
            "status": "active",
        }
    ]
    conn = FakeConn(fetch_rows=rows)
    monkeypatch.setattr(alert_publisher, "get_pool", lambda: FakePool(conn))

    # 재시작 직후 상태: 추적 딕셔너리가 비어 있다
    publisher = alert_publisher.AlertEventPublisher(mqtt_client=None)
    assert publisher._active_alert_ids == {}

    await publisher.restore_active_alerts()

    published: list[Any] = []
    monkeypatch.setattr(
        publisher, "_publish_mqtt", lambda topic, payload, retain: published.append(topic)
    )
    monkeypatch.setattr(publisher, "_assigned_worker", _async_none)

    await publisher.publish_transition(
        _transition(from_level=AlertLevel.LEVEL3, to_level=AlertLevel.NORMAL)
    )

    assert published, "복구했는데도 NORMAL 전이가 발행되지 않았다"
    assert any(t.startswith("alerts/state/") for t in published), (
        "retained 상태 토픽이 갱신되지 않으면 브로커에 active 가 영구히 남는다"
    )


@pytest.mark.asyncio
async def test_resolve_without_restore_is_swallowed(monkeypatch):
    """복구 이전 동작을 명시적으로 남긴다 — 이 테스트가 결함 자체를 기술한다."""
    from app.services import alert_publisher

    conn = FakeConn()
    monkeypatch.setattr(alert_publisher, "get_pool", lambda: FakePool(conn))

    publisher = alert_publisher.AlertEventPublisher(mqtt_client=None)
    published: list[Any] = []
    monkeypatch.setattr(
        publisher, "_publish_mqtt", lambda topic, payload, retain: published.append(topic)
    )
    monkeypatch.setattr(publisher, "_assigned_worker", _async_none)

    await publisher.publish_transition(
        _transition(from_level=AlertLevel.LEVEL3, to_level=AlertLevel.NORMAL)
    )

    assert published == [], "추적 중인 경보가 없으면 해제는 발행하지 않는다 (#111 가드)"


@pytest.mark.asyncio
async def test_restore_failure_does_not_block_startup(monkeypatch):
    """복구 실패가 기동을 막으면 신규 경보까지 못 받는다. 로그만 남기고 0 을 준다."""
    from app.services import alert_publisher

    class ExplodingPool:
        def acquire(self):
            raise RuntimeError("db down")

    monkeypatch.setattr(alert_publisher, "get_pool", lambda: ExplodingPool())
    alert_publisher.init_publisher(mqtt_client=None)

    assert await alert_publisher.restore_active_alerts() == 0


@pytest.mark.asyncio
async def test_restore_without_publisher_is_noop(monkeypatch):
    from app.services import alert_publisher

    monkeypatch.setattr(alert_publisher, "_publisher", None)
    assert await alert_publisher.restore_active_alerts() == 0


async def _async_none(*args, **kwargs):
    return None
