#!/usr/bin/env bash
# 브로커 tap — PR #171 hw_verify.py tap 대체 (git 워크트리 없이 동작).
# 사용: scripts/hw/tap.sh [토픽]   (기본 '#')
# 출력: test_results/hardware/<오늘>/mqtt_tap.jsonl 에 append + 화면 표시
set -euo pipefail

# 자격증명은 docker/.env 와 같은 키를 환경변수로 받는다. 공개 저장소라 하드코딩하지 않는다.
MQTT_USER="${MQTT_USERNAME:-hp015}"
MQTT_PASS="${MQTT_PASSWORD:-}"
if [ -z "$MQTT_PASS" ]; then
  echo "MQTT_PASSWORD 가 비어 있다. 예: MQTT_PASSWORD=... scripts/hw/tap.sh" >&2
  exit 1
fi

TOPIC="${1:-#}"
DAY="$(date +%Y-%m-%d)"
OUT="test_results/hardware/${DAY}/mqtt_tap.jsonl"
mkdir -p "$(dirname "$OUT")"

echo "tap: topic='${TOPIC}' → ${OUT}  (Ctrl-C 로 중지)"
docker exec hp015-mosquitto mosquitto_sub \
  -h localhost -p 1883 -u "$MQTT_USER" -P "$MQTT_PASS" \
  -t "$TOPIC" -v -F '%I %t %p' \
  | tee -a "$OUT"
