"""데모 playlist runner (이슈 #83).

여러 시나리오를 순차 실행하는 playlist runner + 사전 정의 playlist.
cli.py 의 --playlist 옵션에서 사용한다.
"""
from __future__ import annotations

import asyncio
import logging
from typing import List, Protocol, Tuple

logger = logging.getLogger(__name__)

PLAYLISTS: dict[str, List[Tuple[str, str, str]]] = {
    "demo": [
        ("co2_warning", "sensor-01", "CO₂ 경보 (정상→L1→L2→L3→정상)"),
        ("h2s_warning", "sensor-01", "H₂S 경보"),
        ("fall_detection", "wearable-01", "낙하 감지"),
        ("o2_low", "wearable-01", "O₂ 저농도 경보"),
        ("node_offline", "sensor-01", "노드 오프라인 (LWT)"),
    ],
    "gas": [
        ("co2_warning", "sensor-01", "CO₂ 경보"),
        ("h2s_warning", "sensor-02", "H₂S 경보 (sensor-02)"),
    ],
    "wearable": [
        ("fall_detection", "wearable-01", "낙하 감지"),
        ("o2_low", "wearable-01", "O₂ 저농도"),
    ],
    "connection": [
        ("node_offline", "sensor-01", "sensor-01 오프라인"),
        ("node_offline", "sensor-02", "sensor-02 오프라인"),
    ],
}


class _ScenarioRunnerProtocol(Protocol):
    async def run_scenario(self, name: str, *, node_id: str, run_id: str = "demo") -> None: ...
    def stop(self) -> None: ...


class DemoPlaylistRunner:
    def __init__(self, scenario_runner: _ScenarioRunnerProtocol, gap_seconds: float = 5.0) -> None:
        self._runner = scenario_runner
        self._gap = gap_seconds
        self._stopped = False

    async def run_playlist(
        self,
        items: List[Tuple[str, str, str]],
        run_id: str = "demo",
    ) -> None:
        total = len(items)
        logger.info("playlist started (run_id=%s, %d items)", run_id, total)
        for idx, (scenario, node_id, label) in enumerate(items):
            if self._stopped:
                logger.info("playlist interrupted at item %d/%d", idx + 1, total)
                break
            logger.info("playlist [%d/%d] %s → %s", idx + 1, total, label, scenario)
            await self._runner.run_scenario(scenario, node_id=node_id, run_id=run_id)
            if self._gap > 0 and not self._stopped and idx < total - 1:
                await asyncio.sleep(self._gap)
        logger.info("playlist finished")

    def reset(self) -> None:
        self._stopped = False

    def stop(self) -> None:
        self._stopped = True
        try:
            self._runner.stop()
        except Exception:
            pass
