#!/usr/bin/env bash
# 시연 전 경보 초기화 — DB 이력과 브로커 retained 메시지를 함께 비운다.
#
# 왜 두 곳인가: 값이 정상으로 돌아와도 alert_events 의 상위 레벨 행이
# active 로 남고(SUBMISSION_1ST.md §4.6), alerts/state/... 토픽은 retained 라
# 새로 접속한 대시보드에 옛 경보가 그대로 재생된다. 한쪽만 지우면 다시 나타난다.
#
# 사용: MQTT_PASSWORD=... scripts/hw/reset_alerts.sh
set -euo pipefail

MQTT_USER="${MQTT_USERNAME:-hp015}"
MQTT_PASS="${MQTT_PASSWORD:-}"
if [ -z "$MQTT_PASS" ]; then
  echo "MQTT_PASSWORD 가 비어 있다. docker/.env 의 값을 넣어라." >&2
  exit 1
fi

echo "1/2  alert_events 비우기"
docker exec hp015-timescaledb psql -U hp015 -d hp015 -c "TRUNCATE alert_events;"

echo "2/2  브로커 retained 경보 비우기"
TOPICS="$(timeout 5 docker exec hp015-mosquitto mosquitto_sub \
  -h localhost -p 1883 -u "$MQTT_USER" -P "$MQTT_PASS" \
  -t 'alerts/#' -v 2>/dev/null | awk '{print $1}' | sort -u | tr -d '\r' || true)"

if [ -z "$TOPICS" ]; then
  echo "     retained 없음"
else
  while IFS= read -r topic; do
    [ -z "$topic" ] && continue
    # 빈 페이로드를 retained 로 발행하면 해당 토픽의 retained 가 삭제된다
    docker exec hp015-mosquitto mosquitto_pub \
      -h localhost -p 1883 -u "$MQTT_USER" -P "$MQTT_PASS" \
      -t "$topic" -r -m ""
    echo "     지움 $topic"
  done <<< "$TOPICS"
fi

echo "완료. 대시보드를 새로고침하면 경보가 비어 있어야 한다."
