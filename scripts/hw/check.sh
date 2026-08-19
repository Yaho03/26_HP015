#!/usr/bin/env bash
# DB 판정 — PR #171 hw_verify.py check 대체.
# 사용: scripts/hw/check.sh [node_id]
set -euo pipefail

NODE="${1:-}"
Q() { docker exec hp015-timescaledb psql -U hp015 -d hp015 -qAX -c "$1"; }

echo "=== sensor_data 최근 5건 ==="
if [ -n "$NODE" ]; then
  Q "SELECT time, node_id, metric, value FROM sensor_data WHERE node_id='${NODE}' ORDER BY time DESC LIMIT 5;"
else
  Q "SELECT time, node_id, metric, value FROM sensor_data ORDER BY time DESC LIMIT 5;"
fi

echo
echo "=== 노드별 수집 현황 (최근 30분) ==="
Q "SELECT node_id, count(*) AS rows, min(time) AS first, max(time) AS last
   FROM sensor_data WHERE time > now() - interval '30 min' GROUP BY node_id ORDER BY node_id;"

echo
echo "=== sampled_at 시각 편차 (now - time, ±2초 이내여야 함 / #103) ==="
Q "SELECT node_id, max(time) AS last_sample, now() - max(time) AS skew
   FROM sensor_data GROUP BY node_id ORDER BY node_id;"

echo
echo "=== node_status (연결 감지 / #52 #111 #153) ==="
Q "SELECT node_id, connection_status, connection_updated_at FROM node_status ORDER BY node_id;"

echo
echo "=== alert_events 최근 10건 + 지연 (#67) ==="
Q "SELECT source_node_id, level, activated_at, published_at, published_at - activated_at AS delay
   FROM alert_events ORDER BY activated_at DESC LIMIT 10;"

echo
echo "=== 백엔드 카운터 (#49 손실률·중복률·재연결) ==="
# 계획서 §4 B-6 의 /metrics 는 오답. 실제 경로는 /api/metrics.
curl -s --max-time 10 localhost:8000/api/metrics | python -m json.tool

echo
echo "=== 적재된 metric 이름 (§6 교정 후 확인) ==="
Q "SELECT DISTINCT metric FROM sensor_data ORDER BY metric;"
