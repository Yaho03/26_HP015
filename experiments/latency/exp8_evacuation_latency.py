"""EXP-8.1: level3 주입부터 탈출 경로 WebSocket 발행까지의 지연 측정.

통합 스택이 실행 중인 상태에서 30회 반복하고 원본 CSV를 남긴다.
Docker Compose 네트워크에서 실행하는 예:

  docker run --rm --network docker_default \
    -e MQTT_USERNAME=hp015 -e MQTT_PASSWORD=... \
    -v "$PWD:/repo" -w /repo docker-backend \
    python experiments/latency/exp8_evacuation_latency.py
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import statistics
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from http.cookies import SimpleCookie
from pathlib import Path

import paho.mqtt.client as mqtt
import websockets
from ulid import ULID


@dataclass(frozen=True)
class Sample:
    iteration: int
    published_at: datetime
    received_at: datetime
    latency_ms: float
    route_id: str
    target_exit_id: str | None


def percentile(values: list[float], fraction: float) -> float:
    """Nearest-rank percentile. EXP 문서의 P95 판정과 동일한 보수적 방식."""
    if not values:
        raise ValueError("at least one value is required")
    ordered = sorted(values)
    rank = max(1, int((len(ordered) * fraction) + 0.999999999))
    return ordered[min(rank, len(ordered)) - 1]


def gas_payload(node_id: str, co2_ppm: float, sampled_at: datetime, iteration: int) -> str:
    return json.dumps(
        {
            "schema_version": "1.1",
            "message_id": str(ULID()),
            "node_id": node_id,
            "sampled_at": sampled_at.isoformat().replace("+00:00", "Z"),
            "source_mode": "simulation",
            "simulation": {"run_id": "exp8-1", "scenario_id": "evacuation_latency", "step": iteration},
            "data": {"co2_ppm": co2_ppm, "temperature_c": 25.0, "humidity_pct": 50.0},
        },
        ensure_ascii=False,
    )


def location_payload(sampled_at: datetime, iteration: int) -> str:
    """경로 계산에 사용할 최신 작업자 위치를 각 반복마다 갱신한다."""
    return json.dumps(
        {
            "schema_version": "1.1",
            "message_id": str(ULID()),
            "node_id": "wearable-01",
            "sampled_at": sampled_at.isoformat().replace("+00:00", "Z"),
            "source_mode": "simulation",
            "simulation": {"run_id": "exp8-1", "scenario_id": "evacuation_latency"},
            "sequence": iteration,
            "data": {
                # demo-local 중앙점은 ship-visual의 nav.floor.mid (30, 0)에 대응한다.
                "x_m": 1.25,
                "y_m": 1.0,
                "z_m": 0.0,
                "coordinate_system": "demo-local",
                "method": "ds_twr",
                "anchor_count": 4,
                "quality_score": 1.0,
                "is_filtered": True,
            },
        },
        ensure_ascii=False,
    )


async def next_route(ws, *, target_not: str | None = None, target_is: str | None = None, timeout: float = 5.0) -> dict:
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise TimeoutError("evacuation_route WebSocket message timed out")
        message = json.loads(await asyncio.wait_for(ws.recv(), remaining))
        if message.get("type") != "evacuation_route":
            continue
        target = message.get("target_exit_id")
        if target_not is not None and target == target_not:
            continue
        if target_is is not None and target != target_is:
            continue
        return message


async def run(args: argparse.Namespace) -> list[Sample]:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    if args.mqtt_username:
        client.username_pw_set(args.mqtt_username, args.mqtt_password)
    client.connect(args.mqtt_host, args.mqtt_port, keepalive=30)
    client.loop_start()
    samples: list[Sample] = []
    try:
        cookie = login_cookie(args.api_base, args.username, args.password)
        async with websockets.connect(args.ws_url, additional_headers={"Cookie": cookie}) as ws:
            baseline_at = datetime.now(timezone.utc)
            client.publish(
                "wearable/wearable-01/location",
                location_payload(baseline_at, 0),
                qos=1,
            ).wait_for_publish(timeout=2.0)
            baseline = await next_route(ws, timeout=args.timeout)
            current_target = baseline.get("target_exit_id")
            if current_target not in {"trunk-fwd", "trunk-aft"}:
                raise RuntimeError(f"baseline route has no usable exit: {baseline}")

            for iteration in range(1, args.samples + 1):
                sensor_id = "sensor-01" if current_target == "trunk-fwd" else "sensor-02"
                expected_target = "trunk-aft" if current_target == "trunk-fwd" else "trunk-fwd"
                published_at = datetime.now(timezone.utc)
                client.publish(
                    "wearable/wearable-01/location",
                    location_payload(published_at, iteration),
                    qos=1,
                ).wait_for_publish(timeout=2.0)
                started = time.perf_counter()
                info = client.publish(
                    f"sensors/{sensor_id}/gas",
                    gas_payload(sensor_id, 5500.0, published_at, iteration),
                    qos=1,
                )
                info.wait_for_publish(timeout=2.0)
                route = await next_route(ws, target_is=expected_target, timeout=args.timeout)
                received_at = datetime.now(timezone.utc)
                latency_ms = (time.perf_counter() - started) * 1000.0
                samples.append(
                    Sample(
                        iteration=iteration,
                        published_at=published_at,
                        received_at=received_at,
                        latency_ms=latency_ms,
                        route_id=route["route_id"],
                        target_exit_id=route.get("target_exit_id"),
                    )
                )

                # 해제는 L3→L2→L1→normal의 단계적 하향이고 각 단계가 5초다.
                # 미래 sampled_at은 ingest가 거부하므로 실제 시간으로 세 단계를
                # 해제한다. 이 휴지시간은 위에서 이미 끝난 지연 측정에 포함되지 않는다.
                for _ in range(3):
                    client.publish(
                        f"sensors/{sensor_id}/gas",
                        gas_payload(sensor_id, 700.0, datetime.now(timezone.utc), iteration),
                        qos=1,
                    ).wait_for_publish(2.0)
                    await asyncio.sleep(args.clear_wait)
                    client.publish(
                        f"sensors/{sensor_id}/gas",
                        gas_payload(sensor_id, 700.0, datetime.now(timezone.utc), iteration),
                        qos=1,
                    ).wait_for_publish(2.0)
                    await asyncio.sleep(0.1)
                current_target = expected_target
    finally:
        client.loop_stop()
        client.disconnect()
    return samples


def write_csv(path: Path, samples: list[Sample]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["iteration", "published_at", "received_at", "latency_ms", "route_id", "target_exit_id"])
        for sample in samples:
            writer.writerow(
                [sample.iteration, sample.published_at.isoformat(), sample.received_at.isoformat(), f"{sample.latency_ms:.3f}", sample.route_id, sample.target_exit_id or ""]
            )


def login_cookie(api_base: str, username: str, password: str) -> str:
    if not username or not password:
        raise ValueError("EXP8_USERNAME and EXP8_PASSWORD are required")
    body = json.dumps({"username": username, "password": password}).encode()
    request = urllib.request.Request(
        f"{api_base.rstrip('/')}/api/auth/login",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5.0) as response:
        cookies = SimpleCookie()
        for header in response.headers.get_all("Set-Cookie", []):
            cookies.load(header)
    if "hp015_session" not in cookies:
        raise RuntimeError("login succeeded without hp015_session cookie")
    return f"hp015_session={cookies['hp015_session'].value}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--threshold-ms", type=float, default=1000.0)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--clear-wait", type=float, default=5.1)
    parser.add_argument("--ws-url", default="ws://frontend:8080/ws")
    parser.add_argument("--api-base", default="http://frontend:8080")
    parser.add_argument("--mqtt-host", default="mosquitto")
    parser.add_argument("--mqtt-port", type=int, default=1883)
    parser.add_argument("--mqtt-username", default=os.getenv("MQTT_USERNAME", ""))
    parser.add_argument("--mqtt-password", default=os.getenv("MQTT_PASSWORD", ""))
    parser.add_argument("--username", default=os.getenv("EXP8_USERNAME", ""))
    parser.add_argument("--password", default=os.getenv("EXP8_PASSWORD", ""))
    parser.add_argument("--output", type=Path, default=Path("experiments/results/exp8_1_evacuation_latency.csv"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    samples = asyncio.run(run(args))
    write_csv(args.output, samples)
    latencies = [sample.latency_ms for sample in samples]
    p95 = percentile(latencies, 0.95)
    print(f"samples={len(samples)} mean_ms={statistics.mean(latencies):.3f} p95_ms={p95:.3f} max_ms={max(latencies):.3f}")
    print(f"result={'PASS' if p95 <= args.threshold_ms else 'FAIL'} threshold_ms={args.threshold_ms:.1f}")
    print(f"csv={args.output}")
    return 0 if p95 <= args.threshold_ms else 1


if __name__ == "__main__":
    raise SystemExit(main())
