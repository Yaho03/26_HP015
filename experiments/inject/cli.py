"""데이터 주입 도구 CLI (이슈 #82).

사용법:
  python -m experiments.inject.cli --list
  python -m experiments.inject.cli --scenario co2_warning --node-id sensor-01
  python -m experiments.inject.cli --scenario o2_low --node-id wearable-01 --host broker.local

  # Scenario 1 정상 상태 — 센서 4개를 5분간 동시 주입
  python -m experiments.inject.cli --scenario normal_steady \
      --node-id sensor-01,sensor-02,sensor-03,sensor-04 --duration 300

기본 MQTT host: localhost:1883, 인증 정보는 MQTT_USERNAME/MQTT_PASSWORD 환경변수
(backend/.env 와 동일한 키).
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import paho.mqtt.client as mqtt

from injector import ScenarioRunner
from scenarios import SCENARIOS
from demo_runner import PLAYLISTS, DemoPlaylistRunner

logger = logging.getLogger("inject")

# --duration 을 받는 시나리오. 나머지는 길이가 고정되어 있다.
DURATION_SCENARIOS = {
    "normal_steady", "worker_walk", "worker_walk_uwb", "gas_spread",
    "exposure_h2s_danger",
}

CONNECT_TIMEOUT_SECONDS = 5.0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="데모 데이터 주입 도구 — 시나리오별 MQTT 메시지 시뮬레이션",
    )
    parser.add_argument("--list", action="store_true", help="사용 가능한 시나리오 목록 출력")
    parser.add_argument("--list-playlists", action="store_true", help="사용 가능한 playlist 목록 출력")
    parser.add_argument("--scenario", help="실행할 단일 시나리오 이름")
    parser.add_argument("--playlist", help="실행할 playlist 이름 (여러 시나리오 순차 실행)")
    parser.add_argument(
        "--node-id", default="sensor-01",
        help="노드 ID. 쉼표로 여러 개 지정하면 동시에 주입한다 (예: sensor-01,sensor-02)",
    )
    parser.add_argument("--run-id", default=None, help="시뮬레이션 run_id (기본: 자동 생성)")
    parser.add_argument("--host", default="localhost", help="MQTT 브로커 호스트")
    parser.add_argument("--port", type=int, default=1883, help="MQTT 브로커 포트")
    parser.add_argument(
        "--username", default=os.environ.get("MQTT_USERNAME", ""),
        help="MQTT 사용자명 (기본: MQTT_USERNAME 환경변수)",
    )
    parser.add_argument(
        "--password", default=os.environ.get("MQTT_PASSWORD", ""),
        help="MQTT 비밀번호 (기본: MQTT_PASSWORD 환경변수)",
    )
    parser.add_argument(
        "--duration", type=int, default=None,
        help=f"주입 길이 (초). {'/'.join(sorted(DURATION_SCENARIOS))} 에만 적용된다.",
    )
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


def resolve_nodes(args: argparse.Namespace) -> list[str]:
    """--node-id 의 쉼표 구분 목록을 노드 ID 리스트로 변환한다."""
    return [n.strip() for n in args.node_id.split(",") if n.strip()]


def scenario_kwargs_for(scenario: str, args: argparse.Namespace) -> dict:
    """시나리오 전용 인자를 조립한다. 지원하지 않는 조합이면 종료한다."""
    if args.duration is None:
        return {}
    if scenario not in DURATION_SCENARIOS:
        print(
            f"error: --duration is not supported by '{scenario}' "
            f"(supported: {', '.join(sorted(DURATION_SCENARIOS))})",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return {"duration_seconds": args.duration}


def _connect(args: argparse.Namespace) -> mqtt.Client:
    """브로커에 연결한다. 인증 거부를 조용히 넘기지 않고 예외로 알린다."""
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    if args.username:
        client.username_pw_set(args.username, args.password)

    failures: list[str] = []

    def on_connect(_client, _userdata, _flags, reason_code, _properties=None):
        if reason_code != 0:
            failures.append(str(reason_code))

    client.on_connect = on_connect
    client.connect(args.host, args.port)
    client.loop_start()

    deadline = time.monotonic() + CONNECT_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if client.is_connected():
            return client
        if failures:
            break
        time.sleep(0.05)

    client.loop_stop()
    detail = failures[0] if failures else f"{CONNECT_TIMEOUT_SECONDS:.0f}초 내 CONNACK 없음"
    hint = "" if args.username else " (MQTT_USERNAME/MQTT_PASSWORD 가 비어 있음)"
    raise ConnectionError(f"MQTT 연결 실패 {args.host}:{args.port} — {detail}{hint}")


async def _run(args: argparse.Namespace) -> int:
    run_id = args.run_id or _make_run_id()
    client = None

    if args.dry_run:
        def make_runner() -> ScenarioRunner:
            return ScenarioRunner(mqtt_client=_DryRunClient(), delay_seconds=0)
    else:
        client = _connect(args)

        def make_runner() -> ScenarioRunner:
            return ScenarioRunner(mqtt_client=client, delay_seconds=args.delay)

    try:
        if args.playlist:
            if args.playlist not in PLAYLISTS:
                print(f"error: unknown playlist '{args.playlist}'", file=sys.stderr)
                return 2
            demo = DemoPlaylistRunner(scenario_runner=make_runner(), gap_seconds=args.gap)
            await demo.run_playlist(PLAYLISTS[args.playlist], run_id=run_id)
        else:
            kwargs = scenario_kwargs_for(args.scenario, args)
            nodes = resolve_nodes(args)
            # 노드마다 별도 runner — ScenarioRunner 는 중단 상태를 인스턴스에 들고 있다.
            await asyncio.gather(*(
                make_runner().run_scenario(
                    args.scenario, node_id=node, run_id=run_id, **kwargs
                )
                for node in nodes
            ))
    finally:
        if client is not None:
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

    try:
        return asyncio.run(_run(args))
    except ConnectionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
