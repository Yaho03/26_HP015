// 경보 유형·등급의 한국어 표기 (10_UI_FLOW §6.3).
//
// Screen 1 ④ 최근 위험 로그와 Screen 4 이벤트 로그가 같은 표를 봐야 한다.
// 두 화면이 각자 매핑을 들고 있으면 유형이 하나 늘 때 한쪽만 갱신되어,
// 같은 사건이 화면마다 다른 이름으로 보인다.

export const ALERT_TYPE_LABEL: Record<string, string> = {
  gas_threshold: "가스 임계값",
  fall_detection: "낙상 감지",
  o2_low: "O₂ 저농도",
  o2_high: "O₂ 고농도",
  zone_intrusion: "위험 구역 진입",
  connection_lost: "연결 끊김",
};

export const ALERT_LEVEL_LABEL: Record<string, string> = {
  level1_caution: "L1 주의",
  level2_warning: "L2 경고",
  level3_critical: "L3 위험",
};

/** 알 수 없는 유형은 서버가 준 원문을 그대로 보여준다 — 삼키지 않는다. */
export function alertTypeLabel(type: string): string {
  return ALERT_TYPE_LABEL[type] ?? type;
}

/** alert_key 는 `${node_id}:${metric}` 형식이다 (useWebSocket.deriveAlertKey). */
export function metricFromAlertKey(alertKey: string): string {
  const idx = alertKey.lastIndexOf(":");
  return idx >= 0 ? alertKey.slice(idx + 1) : alertKey;
}

/** 경보 지표의 한국어 이름. 가스 지표는 유형 표에 없으므로 따로 둔다. */
export const ALERT_METRIC_LABEL: Record<string, string> = {
  co2_ppm: "CO₂ 농도",
  co_ppm: "CO 농도",
  h2s_ppm: "H₂S 농도",
  temperature_c: "온도",
  humidity_pct: "습도",
  gas_resistance_ohm: "가스저항",
  o2_low: "O₂ 저농도",
  o2_high: "O₂ 고농도",
  fall_detection: "낙상 감지",
  connection_lost: "연결 끊김",
  zone_intrusion: "위험 구역 진입",
};

export function alertMetricLabel(metric: string): string {
  return ALERT_METRIC_LABEL[metric] ?? metric;
}
