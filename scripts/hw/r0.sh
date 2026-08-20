#!/usr/bin/env bash
# MQ R0 교정 후보 계산 — 시리얼 [MQ CAL] 없이 DB 만으로 판정한다.
#
# 펌웨어의 [MQ CAL] 은 시리얼 전용이라 보드가 USB 에서 빠지면 볼 수 없다.
# 다만 rs_ohm 은 MQTT 로 발행되므로 R0 = Rs / clean_air_ratio 를 직접 계산할 수 있다.
# clean-air Rs/R0 (데이터시트): MQ-7 27.5 / MQ-136 3.4 / MQ-2 9.83
#
# 펌웨어는 60샘플(1분) 창의 spread 만 보므로 느린 드리프트를 놓친다.
# 여기서는 창을 인자로 받아 길게 볼 수 있다.
#
# 사용: scripts/hw/r0.sh [분]   (기본 5)
set -euo pipefail

WIN="${1:-5}"

docker exec hp015-timescaledb psql -U hp015 -d hp015 -qAX -c "
SELECT
  CASE metric WHEN 'co_rs_ohm'  THEN 'mq7 (CO)'
              WHEN 'h2s_rs_ohm' THEN 'mq136 (H2S)'
              WHEN 'mq2_rs_ohm' THEN 'mq2' END AS sensor,
  count(*) AS n,
  round(avg(value)::numeric,1) AS rs_avg,
  round(((max(value)-min(value))/avg(value)*100)::numeric,2) AS spread_pct,
  round((avg(value) / CASE metric WHEN 'co_rs_ohm'  THEN 27.5
                                  WHEN 'h2s_rs_ohm' THEN 3.4
                                  WHEN 'mq2_rs_ohm' THEN 9.83 END)::numeric,2) AS r0_candidate,
  CASE WHEN ((max(value)-min(value))/avg(value)*100) <= 5 THEN 'OK' ELSE '불안정' END AS verdict
FROM sensor_data
WHERE metric IN ('co_rs_ohm','h2s_rs_ohm','mq2_rs_ohm')
  AND time > now() - interval '${WIN} min'
GROUP BY metric ORDER BY metric;"

echo
echo "-- 드리프트 확인: 1분 단위 R0 후보 추이 (최근 ${WIN}분) --"
docker exec hp015-timescaledb psql -U hp015 -d hp015 -qAX -c "
SELECT date_trunc('minute', time) AS minute,
  round(avg(value) FILTER (WHERE metric='co_rs_ohm')  ::numeric / 27.5, 1) AS mq7_r0,
  round(avg(value) FILTER (WHERE metric='h2s_rs_ohm') ::numeric / 3.4,  1) AS mq136_r0,
  round(avg(value) FILTER (WHERE metric='mq2_rs_ohm') ::numeric / 9.83, 1) AS mq2_r0
FROM sensor_data
WHERE metric IN ('co_rs_ohm','h2s_rs_ohm','mq2_rs_ohm')
  AND time > now() - interval '${WIN} min'
GROUP BY 1 ORDER BY 1;"
