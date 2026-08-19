#!/usr/bin/env bash
# 브로커 tap — PR #171 hw_verify.py tap 대체 (git 워크트리 없이 동작).
# 사용: scripts/hw/tap.sh [토픽]   (기본 '#')
# 출력: test_results/hardware/<오늘>/mqtt_tap.jsonl 에 append + 화면 표시
set -euo pipefail

TOPIC="${1:-#}"
DAY="$(date +%Y-%m-%d)"
OUT="test_results/hardware/${DAY}/mqtt_tap.jsonl"
mkdir -p "$(dirname "$OUT")"

echo "tap: topic='${TOPIC}' → ${OUT}  (Ctrl-C 로 중지)"
docker exec hp015-mosquitto mosquitto_sub \
  -h localhost -p 1883 -u hp015 -P hp015_dev_pw \
  -t "$TOPIC" -v -F '%I %t %p' \
  | tee -a "$OUT"
