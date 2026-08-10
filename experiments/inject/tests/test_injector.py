"""이슈 #82: injector (MQTT 발행 로직) — TDD 테스트."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from injector import ScenarioRunner


class FakeMQTT:
    def __init__(self):
        self.published: list[tuple[str, str]] = []
        self.connected = False

    def connect(self, host, port=1883):
        self.connected = True

    def disconnect(self):
        self.connected = False

    def publish(self, topic, payload, qos=1, retain=False):
        self.published.append((topic, payload))
        return type("Info", (), {"rc": 0})()

    def loop_start(self): pass
    def loop_stop(self): pass


@pytest.mark.asyncio
async def test_runner_publishes_all_messages_in_scenario():
    fake = FakeMQTT()
    runner = ScenarioRunner(mqtt_client=fake, delay_seconds=0)
    await runner.run_scenario("co2_warning", node_id="sensor-01")
    assert len(fake.published) > 0
    topics = [t for t, _ in fake.published]
    assert all("sensor-01" in t for t in topics)


@pytest.mark.asyncio
async def test_runner_unknown_scenario_raises():
    fake = FakeMQTT()
    runner = ScenarioRunner(mqtt_client=fake, delay_seconds=0)
    with pytest.raises(KeyError):
        await runner.run_scenario("unknown", node_id="sensor-01")


@pytest.mark.asyncio
async def test_runner_publishes_correct_topics_per_scenario():
    fake = FakeMQTT()
    runner = ScenarioRunner(mqtt_client=fake, delay_seconds=0)
    await runner.run_scenario("fall_detection", node_id="wearable-01")
    topics = [t for t, _ in fake.published]
    assert all("wearable/wearable-01/imu" in t for t in topics)


@pytest.mark.asyncio
async def test_runner_run_id_propagates():
    fake = FakeMQTT()
    runner = ScenarioRunner(mqtt_client=fake, delay_seconds=0)
    await runner.run_scenario("co2_warning", node_id="sensor-01", run_id="custom-run-001")
    import json
    first_payload = json.loads(fake.published[0][1])
    assert first_payload["simulation"]["run_id"] == "custom-run-001"


@pytest.mark.asyncio
async def test_runner_stop_interrupts_long_scenario(monkeypatch):
    """stop() 호출 시 실행 중인 시나리오가 중단되어야 한다."""
    fake = FakeMQTT()
    runner = ScenarioRunner(mqtt_client=fake, delay_seconds=0.1)
    await runner.start("co2_warning", node_id="sensor-01")
    runner.stop()
    # stop 후에도 일부는 발행되었을 수 있지만, 전체는 아님
    assert len(fake.published) < 19  # co2_warning 은 19개 메시지


def test_runner_list_scenarios():
    fake = FakeMQTT()
    runner = ScenarioRunner(mqtt_client=fake, delay_seconds=0)
    scenarios = runner.list_scenarios()
    assert "co2_warning" in scenarios
    assert "h2s_warning" in scenarios
    assert "fall_detection" in scenarios
    assert "o2_low" in scenarios
    assert "node_offline" in scenarios
