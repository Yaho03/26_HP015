"""경보 저장 통합 테스트 — 실제 DB (이슈 #124).

#102 는 alert_publisher 가 TIMESTAMPTZ 컬럼에 문자열을 넘겨 경보 저장이 전부
실패한 P0 였다. 단위 테스트는 DB 를 mock 해서 무엇을 넘기든 통과했다. 실제 DB 에
넣어보는 테스트가 하나만 있었어도 즉시 걸렸을 결함이다.

여기 있는 테스트는 mock 을 쓰지 않는다.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

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


def transition(
    *, to_level: AlertLevel = AlertLevel.LEVEL2, node_id: str = "sensor-01"
) -> AlertTransition:
    return AlertTransition(
        node_id=node_id,
        metric="co2_ppm",
        from_level=AlertLevel.LEVEL1,
        to_level=to_level,
        value=2100.0,
        threshold=2000.0,
        timestamp=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_transition_actually_lands_in_db(db_pool):
    """★ #102 회귀 방지 — 실제로 행이 들어가는지 본다.

    타임스탬프 바인딩이 틀리면 asyncpg 가 DataError 를 던진다. mock 은 못 잡는다.
    """
    publisher = AlertEventPublisher(mqtt_client=FakeMqttClient())
    t = transition(node_id="sensor-integration-01")

    await publisher.publish_transition(t)

    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM alert_events WHERE source_node_id = $1",
            "sensor-integration-01",
        )
        assert len(rows) == 1, "경보가 DB 에 저장되지 않았다"
        row = rows[0]
        assert row["level"] == "level2_warning"
        assert row["trigger_value"] == pytest.approx(2100.0)
        # TIMESTAMPTZ 컬럼이 datetime 으로 돌아와야 한다. str 이 들어갔다면 애초에
        # INSERT 가 실패했을 것이다.
        assert isinstance(row["activated_at"], datetime)
        assert isinstance(row["published_at"], datetime)

        await conn.execute(
            "DELETE FROM alert_events WHERE source_node_id = $1", "sensor-integration-01"
        )


@pytest.mark.asyncio
async def test_timestamps_round_trip_with_timezone(db_pool):
    """저장한 시각이 그대로 돌아오는지. 타임존이 날아가면 경보 이력이 어긋난다."""
    publisher = AlertEventPublisher(mqtt_client=FakeMqttClient())
    t = transition(node_id="sensor-integration-02")
    sent_at = t.timestamp

    await publisher.publish_transition(t)

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT activated_at FROM alert_events WHERE source_node_id = $1",
            "sensor-integration-02",
        )
        assert row is not None
        stored = row["activated_at"]
        assert stored.tzinfo is not None, "타임존 정보가 사라졌다"
        assert abs(stored - sent_at) < timedelta(seconds=1)

        await conn.execute(
            "DELETE FROM alert_events WHERE source_node_id = $1", "sensor-integration-02"
        )


@pytest.mark.asyncio
async def test_duplicate_message_id_does_not_raise(db_pool):
    """ON CONFLICT DO NOTHING 이 실제로 동작하는지. 재발행 시 터지면 안 된다."""
    publisher = AlertEventPublisher(mqtt_client=FakeMqttClient())
    t = transition(node_id="sensor-integration-03")

    await publisher.publish_transition(t)
    await publisher.publish_transition(t)  # 같은 전환을 다시

    async with db_pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM alert_events WHERE source_node_id = $1", "sensor-integration-03"
        )


@pytest.mark.asyncio
async def test_all_levels_persist(db_pool):
    """레벨 문자열이 컬럼 제약에 걸리지 않는지 전 등급 확인."""
    publisher = AlertEventPublisher(mqtt_client=FakeMqttClient())
    node = "sensor-integration-04"

    for level in (AlertLevel.LEVEL1, AlertLevel.LEVEL2, AlertLevel.LEVEL3):
        await publisher.publish_transition(transition(to_level=level, node_id=node))

    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT level FROM alert_events WHERE source_node_id = $1", node
        )
        assert {r["level"] for r in rows} == {
            "level1_caution",
            "level2_warning",
            "level3_critical",
        }
        await conn.execute("DELETE FROM alert_events WHERE source_node_id = $1", node)
