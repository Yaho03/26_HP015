"""데이터 주입 도구 — 시나리오 실행기 (이슈 #82).

ScenarioRunner: 시나리오 생성기가 반환한 메시지를 순차적으로 MQTT 발행.
start()/stop() 으로 백그라운드 실행 및 중단 제어.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from scenarios import SCENARIOS

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
        for index, (topic, payload) in enumerate(messages):
            if self._stopped:
                logger.info("scenario %s interrupted", name)
                break
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
