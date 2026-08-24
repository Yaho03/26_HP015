"""실측 MQTT tap 로그를 브로커로 되돌려 보낸다 (시연·검증용).

왜 필요한가: `experiments/inject` 의 데모 시나리오는 co2_ppm/co_ppm/h2s_ppm 을 보내는데,
AI 모델이 학습한 feature 는 mq7_rs_ohm / mq136_rs_ohm / mq2_rs_ohm / temperature_c /
humidity_pct 다. 기존 주입기로는 모델이 자기 입력을 한 번도 못 본다.

이 스크립트는 2026-08-24 실측 기록을 그대로 재생해 모델이 실제로 학습한 값을
보게 한다.

**source_mode 는 'simulation' 으로 바꿔 보낸다.** 값 자체는 실측이지만 지금 측정되고
있는 것이 아니기 때문이다. 재생을 live 로 발행하면 DB 에 "그 시각에 센서가 살아
있었다" 는 거짓 기록이 남고, 나중에 이 구간을 학습에 쓰면 같은 데이터를 두 번 배운다.
화면에도 SIM 배지가 뜬다 (04_DATA_CONTRACT §3.5).

  python scripts/replay_tap.py --source <tap.txt>
  python scripts/replay_tap.py --source <tap.txt> --anomaly-after 60
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List

import paho.mqtt.client as mqtt

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.data_loader import _decode  # noqa: E402

RUN_ID = "replay-20260824"
# 이상 주입 대상. 학습 feature 중 하나여야 모델이 반응한다.
ANOMALY_METRIC = "mq7_rs_ohm"
ANOMALY_FACTOR = 1.35


def _load(paths: List[Path]) -> List[tuple]:
    """(topic, envelope) 를 sampled_at 순으로."""
    messages = []
    for path in paths:
        for line in _decode(path).splitlines():
            brace = line.find(" {")
            if brace < 0:
                continue
            topic = line[:brace]
            if topic.rsplit("/", 1)[-1] not in ("gas", "env"):
                continue
            try:
                envelope = json.loads(line[brace + 1:])
            except json.JSONDecodeError:
                continue
            if envelope.get("sampled_at"):
                messages.append((topic, envelope))
    messages.sort(key=lambda item: item[1]["sampled_at"])
    return messages


def main() -> int:
    parser = argparse.ArgumentParser(description="실측 tap 로그 MQTT 재생")
    parser.add_argument("--source", action="append", required=True)
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--username", default="")
    parser.add_argument("--password", default="")
    parser.add_argument("--prefill-s", type=float, default=660.0,
                        help="과거 이 시간만큼을 먼저 채우고(즉시 발행) 그 뒤 실시간으로 잇는다. "
                             "모델 window(10분)를 채우려면 그보다 커야 한다.")
    parser.add_argument("--anomaly-after", type=float, default=None,
                        help="이 초 이후 mq7_rs_ohm 에 편차를 준다 (이상 탐지 시연용)")
    parser.add_argument("--duration", type=float, default=None, help="최대 재생 시간(초)")
    args = parser.parse_args()

    messages = _load([Path(p) for p in args.source])
    if not messages:
        print("재생할 메시지가 없습니다", file=sys.stderr)
        return 1
    print(f"{len(messages)}건 로드, 과거 {args.prefill_s:.0f}s 선충전 후 실시간 재생")

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    if args.username:
        client.username_pw_set(args.username, args.password)
    client.connect(args.host, args.port, 60)
    client.loop_start()

    first = datetime.fromisoformat(messages[0][1]["sampled_at"].replace("Z", "+00:00"))
    wall_start = time.monotonic()
    # 기록 시각을 "지금으로부터 prefill_s 초 전" 에 붙인다. 그 구간은 지연 없이
    # 곧바로 발행해 모델 window 를 채우고, 현재 시각을 따라잡은 뒤부터는 1배속으로
    # 흐른다.
    #
    # 단순 배속 재생을 쓰지 않는 이유: 40배속이면 10분치 기록이 실제 15초에 몰려
    # 60개 리샘플 버킷 중 1~2개만 채워진다. 서비스는 관측 비율 70% 미만을
    # insufficient_data 로 거절하므로(정당하다) 영원히 판정이 나오지 않는다.
    now_base = datetime.now(timezone.utc) - timedelta(seconds=args.prefill_s)
    sent = 0
    counters: Dict[str, int] = {}

    try:
        for topic, envelope in messages:
            sampled = datetime.fromisoformat(envelope["sampled_at"].replace("Z", "+00:00"))
            elapsed = (sampled - first).total_seconds()
            if args.duration is not None and elapsed > args.duration + args.prefill_s:
                break

            # 타임스탬프를 현재 시각 기준으로 옮긴다 — 안 그러면 백엔드가 stale_data 로 본다.
            target = now_base + timedelta(seconds=elapsed)
            sleep_for = (target - datetime.now(timezone.utc)).total_seconds()
            if sleep_for > 0:
                time.sleep(sleep_for)

            stamp = target.isoformat().replace("+00:00", "Z")
            node_id = envelope["node_id"]
            counters[node_id] = counters.get(node_id, 0) + 1

            out = dict(envelope)
            out["sampled_at"] = stamp
            out["published_at"] = stamp
            out["sequence"] = counters[node_id]
            # message_id 는 새로 만든다. 원본 그대로면 processed_messages dedup 에 걸려
            # 두 번째 재생부터 한 건도 저장되지 않는다.
            out["message_id"] = f"01M{int(time.time() * 1000) % 10**10:010d}{sent % 10**13:013d}"[:26]
            out["source_mode"] = "simulation"
            out["simulation"] = {"run_id": RUN_ID, "scenario_id": "live_replay"}

            data = dict(out.get("data") or {})
            if (args.anomaly_after is not None
                    and elapsed >= args.prefill_s + args.anomaly_after
                    and data.get(ANOMALY_METRIC) is not None):
                data[ANOMALY_METRIC] = data[ANOMALY_METRIC] * ANOMALY_FACTOR
            out["data"] = data

            client.publish(topic, json.dumps(out), qos=1)
            sent += 1
            if sent % 500 == 0:
                phase = "prefill" if elapsed < args.prefill_s else "live"
                marker = " [이상주입중]" if (
                    args.anomaly_after is not None
                    and elapsed >= args.prefill_s + args.anomaly_after
                ) else ""
                print(f"  {sent}건 / 기록 {elapsed:.0f}s / {phase}{marker}")
    except KeyboardInterrupt:
        print("\n중단됨")
    finally:
        client.loop_stop()
        client.disconnect()

    print(f"완료: {sent}건 발행")
    return 0


if __name__ == "__main__":
    sys.exit(main())
