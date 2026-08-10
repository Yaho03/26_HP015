"""데이터 주입 도구 CLI (이슈 #82).

사용법:
  python -m experiments.inject.cli --list
  python -m experiments.inject.cli --scenario co2_warning --node-id sensor-01
  python -m experiments.inject.cli --scenario o2_low --node-id wearable-01 --host broker.local

기본 MQTT host: localhost:1883 (backend/.env 와 동일).
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import paho.mqtt.client as mqtt

from injector import ScenarioRunner
from scenarios import SCENARIOS
from demo_runner import PLAYLISTS, DemoPlaylistRunner

logger = logging.getLogger("inject")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="데모 데이터 주입 도구 — 시나리오별 MQTT 메시지 시뮬레이션",
    )
    parser.add_argument("--list", action="store_true", help="사용 가능한 시나리오 목록 출력")
    parser.add_argument("--list-playlists", action="store_true", help="사용 가능한 playlist 목록 출력")
    parser.add_argument("--scenario", help="실행할 단일 시나리오 이름")
    parser.add_argument("--playlist", help="실행할 playlist 이름 (여러 시나리오 순차 실행)")
    parser.add_argument("--node-id", default="sensor-01", help="단일 시나리오 실행 시 사용할 노드 ID")
    parser.add_argument("--run-id", default=None, help="시뮬레이션 run_id (기본: 자동 생성)")
    parser.add_argument("--host", default="localhost", help="MQTT 브로커 호스트")
    parser.add_argument("--port", type=int, default=1883, help="MQTT 브로커 포트")
    parser.add_argument(
        "--delay", type=float, default=1.0,
        help="메시지 간 딜레이 (초). 0이면 즉시 발행.",
    )
    parser.add_argument(
        "--gap", type=float, default=5.0,
        help="playlist 모드에서 시나리오 간 대기 (초).",
    )
    parser.add_argument("--dry-run", action="store_true", help="실제 발행 없이 메시지 출력만")
    return parser.parse_args(argv)


def _make_run_id() -> str:
    from datetime import datetime, timezone
    return "demo-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


async def _run(args: argparse.Namespace) -> int:
    run_id = args.run_id or _make_run_id()

    if args.dry_run:
        scenario_runner = ScenarioRunner(mqtt_client=_DryRunClient(), delay_seconds=0)
    else:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        client.connect(args.host, args.port)
        client.loop_start()
        scenario_runner = ScenarioRunner(mqtt_client=client, delay_seconds=args.delay)

    try:
        if args.playlist:
            if args.playlist not in PLAYLISTS:
                print(f"error: unknown playlist '{args.playlist}'", file=sys.stderr)
                return 2
            demo = DemoPlaylistRunner(scenario_runner=scenario_runner, gap_seconds=args.gap)
            await demo.run_playlist(PLAYLISTS[args.playlist], run_id=run_id)
        else:
            await scenario_runner.run_scenario(args.scenario, node_id=args.node_id, run_id=run_id)
    finally:
        if not args.dry_run:
            client.loop_stop()
            client.disconnect()
    return 0


class _DryRunClient:
    def publish(self, topic, payload, qos=1, retain=False):
        print(f"[dry-run] {topic}: {payload}")
        return type("Info", (), {"rc": 0})()


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args(argv)

    if args.list:
        print("Available scenarios:")
        for name in SCENARIOS:
            print(f"  - {name}")
        return 0

    if args.list_playlists:
        print("Available playlists:")
        for name, items in PLAYLISTS.items():
            print(f"  - {name} ({len(items)} scenarios)")
            for scenario, node_id, label in items:
                print(f"      · {scenario} @ {node_id} — {label}")
        return 0

    if not args.scenario and not args.playlist:
        print("error: --scenario or --playlist required (or --list / --list-playlists)", file=sys.stderr)
        return 2

    if args.scenario and args.scenario not in SCENARIOS:
        print(f"error: unknown scenario '{args.scenario}'. Use --list.", file=sys.stderr)
        return 2

    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
