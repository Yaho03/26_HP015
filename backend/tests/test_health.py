"""/health 가 실제 상태를 반영하는지 (이슈 #119).

기존 구현은 클라이언트 객체와 커넥션 풀의 **존재 여부**만 봤다. MQTT 인증이
거부돼 구독을 못 한 상태에서도 ok 를 반환했다 (#115 연쇄). 사이드바 연결 표시가
이 응답을 그대로 믿으므로(#123), 여기서 거짓을 말하면 화면도 같이 거짓말한다.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import db
from app.routers import health as health_router
from app.services import mqtt_subscriber


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(health_router.router)
    return TestClient(app)


@pytest.fixture
def all_good(monkeypatch):
    monkeypatch.setattr(mqtt_subscriber, "is_healthy", lambda: True)

    async def ok_ping() -> bool:
        return True

    monkeypatch.setattr(db, "ping", ok_ping)


def test_healthy_when_everything_works(client, all_good):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["mqtt"]["connected"] is True
    assert body["db"]["pool_initialized"] is True


def test_mqtt_down_is_reported(client, all_good, monkeypatch):
    """가장 중요한 계약 — 구독을 못 하고 있으면 숨기지 않는다."""
    monkeypatch.setattr(mqtt_subscriber, "is_healthy", lambda: False)
    body = client.get("/health").json()
    assert body["mqtt"]["connected"] is False
    assert body["status"] != "ok"


def test_db_down_is_reported(client, all_good, monkeypatch):
    """풀 객체가 있어도 실제로 응답하지 않으면 정상이 아니다."""

    async def dead_ping() -> bool:
        return False

    monkeypatch.setattr(db, "ping", dead_ping)
    body = client.get("/health").json()
    assert body["db"]["pool_initialized"] is False
    assert body["status"] != "ok"


def test_health_stays_http_200_when_degraded(client, all_good, monkeypatch):
    """상태는 본문으로 알린다. 200 을 유지해야 컨테이너 헬스체크·프록시가
    엔드포인트 자체를 죽은 것으로 오해하지 않는다."""
    monkeypatch.setattr(mqtt_subscriber, "is_healthy", lambda: False)
    assert client.get("/health").status_code == 200


class TestMqttHealth:
    def setup_method(self):
        mqtt_subscriber._client = None
        mqtt_subscriber._subscribed = False

    def teardown_method(self):
        mqtt_subscriber._client = None
        mqtt_subscriber._subscribed = False

    def test_no_client_is_unhealthy(self):
        assert mqtt_subscriber.is_healthy() is False

    def test_client_without_subscription_is_unhealthy(self):
        """인증이 거부되면 클라이언트 객체는 남지만 구독은 못 한다.
        객체 존재만 보던 옛 구현이 여기서 ok 를 반환했다."""

        class FakeClient:
            def is_connected(self):
                return True

        mqtt_subscriber._client = FakeClient()
        mqtt_subscriber._subscribed = False
        assert mqtt_subscriber.is_healthy() is False

    def test_subscribed_but_disconnected_is_unhealthy(self):
        class FakeClient:
            def is_connected(self):
                return False

        mqtt_subscriber._client = FakeClient()
        mqtt_subscriber._subscribed = True
        assert mqtt_subscriber.is_healthy() is False

    def test_connected_and_subscribed_is_healthy(self):
        class FakeClient:
            def is_connected(self):
                return True

        mqtt_subscriber._client = FakeClient()
        mqtt_subscriber._subscribed = True
        assert mqtt_subscriber.is_healthy() is True


class TestConnectCallbacks:
    def setup_method(self):
        mqtt_subscriber._subscribed = False

    def test_failed_connect_does_not_mark_subscribed(self):
        class Reason:
            is_failure = True

        class FakeClient:
            def subscribe(self, *a, **kw):
                raise AssertionError("실패한 연결에서 구독하면 안 된다")

        mqtt_subscriber._on_connect(FakeClient(), None, None, Reason())
        assert mqtt_subscriber._subscribed is False

    def test_successful_connect_marks_subscribed(self):
        class Reason:
            is_failure = False

        subscribed = []

        class FakeClient:
            def subscribe(self, pattern, qos=1):
                subscribed.append(pattern)

        mqtt_subscriber._on_connect(FakeClient(), None, None, Reason())
        assert mqtt_subscriber._subscribed is True
        assert len(subscribed) == len(mqtt_subscriber._TOPIC_HANDLERS)

    def test_disconnect_clears_subscription_and_counts_reconnect(self):
        from app.observability import metrics

        mqtt_subscriber._subscribed = True
        before = metrics.snapshot()["mqtt_reconnects"]
        mqtt_subscriber._on_disconnect(None, None, None, None)
        assert mqtt_subscriber._subscribed is False
        assert metrics.snapshot()["mqtt_reconnects"] == before + 1


class TestDbConnectGuard:
    @pytest.mark.asyncio
    async def test_empty_timescale_url_fails_fast(self, monkeypatch):
        """빈 URL 로 두면 asyncpg 가 기본값으로 엉뚱한 DB 에 붙는다 (이슈 #128)."""
        from app.config import settings as cfg

        monkeypatch.setattr(cfg, "timescale_url", "")
        with pytest.raises(RuntimeError, match="TIMESCALE_URL"):
            await db.connect()
