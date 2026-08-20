"""alert_service 가 현재 publisher 를 쓰는지 (이슈 #118).

main.py 가 alert_publisher._publisher 를 alert_service._publisher 로 복사했다.
복사 시점의 객체를 붙들고 있으므로, MQTT 재연결로 init_publisher() 가 다시 불려
publisher 가 교체되면 alert_service 는 죽은 클라이언트를 쥔 옛 객체를 계속 쓴다.
경보가 조용히 발행되지 않는다.
"""
from __future__ import annotations

import pytest

from app.services import alert_publisher, alert_service
from datetime import datetime, timezone

from app.models.alert import AlertLevel, AlertTransition


class FakePublisher:
    def __init__(self, name: str):
        self.name = name
        self.published: list = []

    async def publish_transition(self, transition):
        self.published.append(transition)


def transition() -> AlertTransition:
    return AlertTransition(
        node_id="sensor-01",
        metric="co2_ppm",
        from_level=AlertLevel.NORMAL,
        to_level=AlertLevel.LEVEL1,
        value=1200.0,
        threshold=1000.0,
        timestamp=datetime(2026, 8, 16, tzinfo=timezone.utc),
    )


@pytest.fixture(autouse=True)
def quiet_broadcast(monkeypatch):
    """이 테스트는 발행 경로만 본다. WS 브로드캐스트는 막는다."""
    from app.services import ws_manager

    async def noop(message):
        return None

    monkeypatch.setattr(ws_manager.manager, "broadcast", noop)


@pytest.fixture(autouse=True)
def clean_publisher(monkeypatch):
    monkeypatch.setattr(alert_publisher, "_publisher", None)


@pytest.mark.asyncio
async def test_transition_goes_to_current_publisher(monkeypatch):
    pub = FakePublisher("first")
    monkeypatch.setattr(alert_publisher, "_publisher", pub)
    await alert_service._handle_transition(transition())
    assert len(pub.published) == 1


@pytest.mark.asyncio
async def test_replaced_publisher_is_used(monkeypatch):
    """★ 재연결로 publisher 가 교체되면 새 것으로 나가야 한다.

    복사본을 붙들던 옛 구현은 여기서 old 로 계속 보냈다.
    """
    old, new = FakePublisher("old"), FakePublisher("new")
    monkeypatch.setattr(alert_publisher, "_publisher", old)
    await alert_service._handle_transition(transition())

    monkeypatch.setattr(alert_publisher, "_publisher", new)
    await alert_service._handle_transition(transition())

    assert len(old.published) == 1, "교체 후에도 옛 publisher 로 나갔다"
    assert len(new.published) == 1


@pytest.mark.asyncio
async def test_no_publisher_does_not_crash():
    """publisher 가 아직 없어도 전환 처리 자체는 계속돼야 한다.
    발행이 안 되더라도 WS 브로드캐스트는 나가야 화면이 반응한다."""
    await alert_service._handle_transition(transition())


@pytest.mark.asyncio
async def test_publish_failure_does_not_stop_ws_broadcast(monkeypatch):
    """DB 저장이 실패해도 화면 경보는 떠야 한다 (#102 에서 실제로 겪은 상황)."""
    broadcasts: list = []

    class Boom:
        async def publish_transition(self, t):
            raise RuntimeError("DB 저장 실패")

    from app.services import ws_manager

    async def capture(message):
        broadcasts.append(message)

    monkeypatch.setattr(alert_publisher, "_publisher", Boom())
    monkeypatch.setattr(ws_manager.manager, "broadcast", capture)

    await alert_service._handle_transition(transition())
    assert len(broadcasts) == 1, "저장 실패가 화면 경보까지 막았다"


def test_alert_service_has_no_publisher_global():
    """전역 복사본이 남아 있으면 같은 문제가 재발한다."""
    assert not hasattr(alert_service, "_publisher")
