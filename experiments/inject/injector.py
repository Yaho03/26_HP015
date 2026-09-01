"""데이터 주입 도구 — 시나리오 실행기 (이슈 #82).

ScenarioRunner: 시나리오 생성기가 반환한 메시지를 순차적으로 MQTT 발행.
start()/stop() 으로 백그라운드 실행 및 중단 제어.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from envelope import build_connection_envelope
from scenarios import SCENARIOS

# 백엔드 connection_monitor 는 backend_received_at 이 30초 넘게 과거인 online 노드를
# offline 으로 뒤집는다 (app/services/connection_monitor.py TIMEOUT_SECONDS). 그리고
# 그 컬럼은 가스·환경 데이터로는 갱신되지 않고 연결/status 메시지에만 반응한다.
# 타임아웃의 1/3 주기로 재발행해 한 번 놓쳐도 끊김으로 뒤집히지 않게 한다.
_ONLINE_REFRESH_SECONDS = 10.0

logger = logging.getLogger(__name__)


class ScenarioRunner:
    def __init__(self, mqtt_client, delay_seconds: float = 1.0) -> None:
        self._mqtt = mqtt_client
        self._delay = delay_seconds
        self._task: Optional[asyncio.Task] = None
        self._stopped = False

    def list_scenarios(self) -> list[str]:
        return list(SCENARIOS.keys())

    async def run_scenario(
        self, name: str, *, node_id: str, run_id: str = "demo", **scenario_kwargs
    ) -> None:
        if name not in SCENARIOS:
            raise KeyError(f"unknown scenario: {name}")
        gen = SCENARIOS[name]
        start = datetime.now(timezone.utc)
        messages = gen(start=start, node_id=node_id, run_id=run_id, **scenario_kwargs)
        self._stopped = False
        logger.info(
            "scenario %s started (node=%s, run_id=%s, %d messages)",
            name, node_id, run_id, len(messages),
        )
        # 실물 노드는 접속 직후 nodes/<id>/connection 으로 online 을 알린다
        # (firmware/src/sensor_node/main.cpp connectMqtt). 시뮬레이터가 이걸
        # 빠뜨리면 측정값이 흘러도 대시보드는 계속 "연결 끊김" 으로 남는다.
        # 시나리오마다 따로 넣으면 빠뜨리는 곳이 생기므로 여기서 한 번에 맡는다.
        boot_id = self._announce_online(node_id, start)
        last_online_at = time.monotonic()

        for index, (topic, payload) in enumerate(messages):
            if self._stopped:
                logger.info("scenario %s interrupted", name)
                break
            if time.monotonic() - last_online_at >= _ONLINE_REFRESH_SECONDS:
                self._announce_online(node_id, datetime.now(timezone.utc), boot_id=boot_id)
                last_online_at = time.monotonic()
            self._mqtt.publish(topic, json.dumps(payload), qos=1)
            next_sampled_at = (
                messages[index + 1][1].get("sampled_at")
                if index + 1 < len(messages)
                else None
            )
            same_sample_time_follows = next_sampled_at == payload.get("sampled_at")
            if self._delay > 0 and not same_sample_time_follows:
                await asyncio.sleep(self._delay)
        logger.info("scenario %s finished", name)

    def _announce_online(
        self, node_id: str, timestamp: datetime, *, boot_id: Optional[str] = None
    ) -> str:
        """nodes/<id>/connection 으로 online 을 발행하고 boot_id 를 돌려준다.

        재발행에도 같은 boot_id 를 쓴다 — 값이 바뀌면 노드가 재부팅한 것처럼 보인다.
        reason 은 node-connection.schema.json 의 enum 안이어야 하고, 실물 노드도
        online 은 언제나 connect 로 낸다.
        """
        envelope = build_connection_envelope(
            node_id=node_id,
            status="online",
            reason="connect",
            timestamp=timestamp,
            boot_id=boot_id,
        )
        self._mqtt.publish(
            f"nodes/{node_id}/connection", json.dumps(envelope), qos=1
        )
        return envelope["boot_id"]

    async def start(
        self, name: str, *, node_id: str, run_id: str = "demo"
    ) -> None:
        self._task = asyncio.create_task(
            self.run_scenario(name, node_id=node_id, run_id=run_id)
        )

    def stop(self) -> None:
        self._stopped = True
        if self._task is not None and not self._task.done():
            self._task.cancel()
