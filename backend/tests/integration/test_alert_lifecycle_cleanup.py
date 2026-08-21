"""경보 생애주기 정합 통합 테스트 — 실제 DB (이슈 #194).

단위 테스트는 SQL 이 나갔는지만 본다. 여기서는 진짜 DB 에 넣고 **행이 실제로
어떤 상태로 남는지** 센다. #194 의 증상이 "행이 남는다"였으므로, 남은 행을
직접 세지 않으면 고쳤는지 알 수 없다.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.models.alert import AlertLevel, AlertTransition
from app.services.alert_publisher import AlertEventPublisher


class FakeMqttClient:
    """MQTT 만 가짜다. DB 는 진짜를 쓴다."""

    def __init__(self):
        self.published: list = []

    def publish(self, topic, payload, qos=1, retain=False):
        self.published.append((topic, payload, qos, retain))

        class _Info:
            rc = 0

        return _Info()


def _t(
    from_level: AlertLevel,
    to_level: AlertLevel,
    *,
    node_id: str,
    value: float = 2100.0,
) -> AlertTransition:
    return AlertTransition(
        node_id=node_id,
        metric="co2_ppm",
        from_level=from_level,
        to_level=to_level,
        value=value,
        threshold=2000.0,
        timestamp=datetime.now(timezone.utc),
    )


async def _cleanup(conn, node_id: str) -> None:
    await conn.execute("DELETE FROM alert_events WHERE source_node_id = $1", node_id)


@pytest.mark.asyncio
async def test_full_cycle_leaves_no_active_rows(db_pool):
    """★ #194 본증상 — 한 사이클 뒤 active 행이 0개여야 한다.

    수정 전에는 normal→L1→L2→L3→L2→L1→normal 에서 7개 행 중 6개가 active 로
    고정됐다. 대시보드가 아니라 has_active_alerts_at_or_above() 와
    /api/alert-events?status=active 가 이 행들을 그대로 믿는다.
    """
    node = "sensor-cycle-01"
    publisher = AlertEventPublisher(mqtt_client=FakeMqttClient())

    chain = [
        (AlertLevel.NORMAL, AlertLevel.LEVEL1),
        (AlertLevel.LEVEL1, AlertLevel.LEVEL2),
        (AlertLevel.LEVEL2, AlertLevel.LEVEL3),
        (AlertLevel.LEVEL3, AlertLevel.LEVEL2),
        (AlertLevel.LEVEL2, AlertLevel.LEVEL1),
        (AlertLevel.LEVEL1, AlertLevel.NORMAL),
    ]
    for frm, to in chain:
        await publisher.publish_transition(_t(frm, to, node_id=node))

    async with db_pool.acquire() as conn:
        try:
            active = await conn.fetchval(
                "SELECT count(*) FROM alert_events WHERE source_node_id = $1 AND status = 'active'",
                node,
            )
            total = await conn.fetchval(
                "SELECT count(*) FROM alert_events WHERE source_node_id = $1", node
            )
            assert total == len(chain), "전이마다 이력 행은 남아야 한다 (사고 조사용)"
            assert active == 0, f"해제됐는데 active 행이 {active}개 남았다"

            unresolved = await conn.fetchval(
                """
                SELECT count(*) FROM alert_events
                 WHERE source_node_id = $1 AND status = 'resolved' AND resolved_at IS NULL
                """,
                node,
            )
            assert unresolved == 0, "resolved 인데 resolved_at 이 비어 있다"
        finally:
            await _cleanup(conn, node)


@pytest.mark.asyncio
async def test_only_latest_row_stays_active_mid_escalation(db_pool):
    """승격 도중에는 최신 행 하나만 active 여야 한다."""
    node = "sensor-cycle-02"
    publisher = AlertEventPublisher(mqtt_client=FakeMqttClient())

    await publisher.publish_transition(_t(AlertLevel.NORMAL, AlertLevel.LEVEL1, node_id=node))
    await publisher.publish_transition(_t(AlertLevel.LEVEL1, AlertLevel.LEVEL2, node_id=node))
    await publisher.publish_transition(_t(AlertLevel.LEVEL2, AlertLevel.LEVEL3, node_id=node))

    async with db_pool.acquire() as conn:
        try:
            rows = await conn.fetch(
                """
                SELECT level, status FROM alert_events
                 WHERE source_node_id = $1 AND status = 'active'
                """,
                node,
            )
            assert len(rows) == 1, f"active 행이 {len(rows)}개다. 하나여야 한다"
            assert rows[0]["level"] == "level3_critical", "가장 최근 등급이 남아야 한다"
        finally:
            await _cleanup(conn, node)


@pytest.mark.asyncio
async def test_session_extension_gate_clears_after_resolve(db_pool):
    """★ AUTH-7 연동 — 해제 뒤 세션 유휴 연장 근거가 사라져야 한다.

    has_active_alerts_at_or_above() 는 status='active' 를 전 행에서 센다.
    죽은 L3 행이 남으면 활성 경보가 없는데도 세션이 무기한 연장된다 —
    인증(#184)을 넣은 목적이 훼손된다.
    """
    from app.repositories import alert_events_repository as repo

    node = "sensor-cycle-03"
    publisher = AlertEventPublisher(mqtt_client=FakeMqttClient())

    await publisher.publish_transition(_t(AlertLevel.NORMAL, AlertLevel.LEVEL3, node_id=node))

    async with db_pool.acquire() as conn:
        try:
            assert await repo.has_active_alerts_at_or_above("level2_warning") is True

            await publisher.publish_transition(
                _t(AlertLevel.LEVEL3, AlertLevel.NORMAL, node_id=node, value=100.0)
            )

            remaining = await conn.fetchval(
                "SELECT count(*) FROM alert_events WHERE source_node_id = $1 AND status = 'active'",
                node,
            )
            assert remaining == 0, "해제 후에도 active 행이 남아 세션이 계속 연장된다"
        finally:
            await _cleanup(conn, node)


@pytest.mark.asyncio
async def test_resolve_survives_backend_restart(db_pool):
    """★ #194 원인 B — 재시작이 해제를 삼키면 안 된다.

    _active_alert_ids 는 메모리라 재시작하면 비어 버리고, publish_transition 의
    #111 가드가 NORMAL 전이를 통째로 버린다. 8/16~8/17 경보가 며칠 뒤까지
    남아 있던 경로가 이것이다.
    """
    node = "sensor-cycle-04"

    # 재시작 전 인스턴스
    before = AlertEventPublisher(mqtt_client=FakeMqttClient())
    await before.publish_transition(_t(AlertLevel.NORMAL, AlertLevel.LEVEL3, node_id=node))

    # 재시작 — 새 인스턴스는 추적 딕셔너리가 비어 있다
    after = AlertEventPublisher(mqtt_client=FakeMqttClient())
    assert after._active_alert_ids == {}

    restored = await after.restore_active_alerts()
    assert restored >= 1, "DB 에 active 행이 있는데 복구되지 않았다"

    await after.publish_transition(
        _t(AlertLevel.LEVEL3, AlertLevel.NORMAL, node_id=node, value=100.0)
    )

    async with db_pool.acquire() as conn:
        try:
            active = await conn.fetchval(
                "SELECT count(*) FROM alert_events WHERE source_node_id = $1 AND status = 'active'",
                node,
            )
            assert active == 0, "재시작 뒤 해제가 반영되지 않았다"

            # retained 상태 토픽도 resolved 로 갱신됐어야 한다 (계약서 §3.4)
            state_topics = [
                p for p in after._mqtt.published if p[0].startswith("alerts/state/")
            ]
            assert state_topics, "retained 상태 토픽이 갱신되지 않았다"
            assert state_topics[-1][3] is True, "상태 토픽은 retain=True 로 나가야 한다"
        finally:
            await _cleanup(conn, node)


@pytest.mark.asyncio
async def test_restore_ignores_already_resolved_alerts(db_pool):
    """최신 행이 resolved 인 경보를 되살리면 유령 경보가 생긴다."""
    node = "sensor-cycle-05"
    publisher = AlertEventPublisher(mqtt_client=FakeMqttClient())

    await publisher.publish_transition(_t(AlertLevel.NORMAL, AlertLevel.LEVEL2, node_id=node))
    await publisher.publish_transition(
        _t(AlertLevel.LEVEL2, AlertLevel.NORMAL, node_id=node, value=100.0)
    )

    fresh = AlertEventPublisher(mqtt_client=FakeMqttClient())
    await fresh.restore_active_alerts()

    async with db_pool.acquire() as conn:
        try:
            assert (node, "co2_ppm") not in fresh._active_alert_ids, (
                "이미 해제된 경보가 활성으로 복구됐다"
            )
        finally:
            await _cleanup(conn, node)
