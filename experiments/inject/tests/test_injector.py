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
    assert "sensors/sensor-01/gas" in topics
    assert "wearable/wearable-01/location" in topics
    assert "wearable/wearable-01/vital" in topics


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
    assert topics[0] == "nodes/wearable-01/connection"
    assert all("wearable/wearable-01/imu" in t for t in topics[1:])


@pytest.mark.asyncio
async def test_runner_run_id_propagates():
    fake = FakeMQTT()
    runner = ScenarioRunner(mqtt_client=fake, delay_seconds=0)
    await runner.run_scenario("co2_warning", node_id="sensor-01", run_id="custom-run-001")
    import json
    # [0] 은 러너가 앞세우는 연결 알림이라 simulation 블록이 없다.
    first_payload = json.loads(fake.published[1][1])
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


@pytest.mark.asyncio
async def test_runner_forwards_scenario_kwargs():
    """normal_steady 의 duration_seconds 같은 시나리오 전용 인자가 전달되어야 한다."""
    short = ScenarioRunner(mqtt_client=FakeMQTT(), delay_seconds=0)
    long = ScenarioRunner(mqtt_client=FakeMQTT(), delay_seconds=0)
    await short.run_scenario("normal_steady", node_id="sensor-01", duration_seconds=5)
    await long.run_scenario("normal_steady", node_id="sensor-01", duration_seconds=30)
    assert len(long._mqtt.published) > len(short._mqtt.published)


@pytest.mark.asyncio
async def test_runner_does_not_delay_between_messages_sampled_at_same_time(monkeypatch):
    sleep_delays: list[float] = []

    async def record_sleep(delay: float):
        sleep_delays.append(delay)

    monkeypatch.setattr("injector.asyncio.sleep", record_sleep)
    runner = ScenarioRunner(mqtt_client=FakeMQTT(), delay_seconds=1)
    await runner.run_scenario("gas_spread", node_id="sensor-03", duration_seconds=2)

    # 3개 시각(0·1·2초)마다 가스+위치 두 메시지가 있지만 대기는 시각당 한 번이다.
    assert sleep_delays == [1, 1, 1]


def test_runner_list_scenarios():
    fake = FakeMQTT()
    runner = ScenarioRunner(mqtt_client=fake, delay_seconds=0)
    scenarios = runner.list_scenarios()
    assert "co2_warning" in scenarios
    assert "h2s_warning" in scenarios
    assert "fall_detection" in scenarios
    assert "o2_low" in scenarios
    assert "node_offline" in scenarios


@pytest.mark.asyncio
async def test_runner_announces_node_online_for_every_scenario():
    """측정값만 흘리면 대시보드는 계속 "연결 끊김" 으로 남는다.

    backend_received_at 은 가스·환경 데이터로 갱신되지 않고 연결/status
    메시지에만 반응하므로(app/services/ingest.py), 실물 노드처럼 접속 직후
    online 을 알려야 한다. 시나리오마다 넣으면 빠뜨리므로 러너가 맡는다.
    """
    import json
    for scenario, node in (
        ("gas_spread", "sensor-01"), ("co2_warning", "sensor-01"),
        ("o2_low", "wearable-01"), ("normal_steady", "sensor-01"),
    ):
        fake = FakeMQTT()
        runner = ScenarioRunner(mqtt_client=fake, delay_seconds=0)
        await runner.run_scenario(scenario, node_id=node)
        topic, raw = fake.published[0]
        payload = json.loads(raw)
        assert topic == f"nodes/{node}/connection", scenario
        assert payload["status"] == "online", scenario
        # schemas/node-connection.schema.json 의 enum 밖 값은 계약 위반이다.
        assert payload["reason"] == "connect", scenario


@pytest.mark.asyncio
async def test_runner_refreshes_online_before_backend_timeout(monkeypatch):
    """30초 타임아웃 전에 같은 boot_id 로 재발행해야 한다.

    boot_id 가 바뀌면 노드가 재부팅한 것처럼 보인다.
    """
    import json
    import injector

    clock = iter([0.0, 0.0, 11.0, 11.0, 22.0, 22.0] + [22.0] * 400)
    monkeypatch.setattr(injector.time, "monotonic", lambda: next(clock))

    fake = FakeMQTT()
    runner = ScenarioRunner(mqtt_client=fake, delay_seconds=0)
    await runner.run_scenario("normal_steady", node_id="sensor-01", duration_seconds=30)

    connections = [json.loads(raw) for topic, raw in fake.published
                   if topic.endswith("/connection")]
    assert len(connections) >= 3
    assert {c["status"] for c in connections} == {"online"}
    assert len({c["boot_id"] for c in connections}) == 1
