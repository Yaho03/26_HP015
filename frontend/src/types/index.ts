export type NodeId = string;
export type AlertKey = string;
export type MetricKey =
  | "co2_ppm"
  | "co_ppm"
  | "h2s_ppm"
  | "temperature_c"
  | "humidity_pct"
  | "gas_resistance_ohm"
  | "o2_pct";

// "unknown" 은 서버 임계값을 아직 못 받아 판정이 불가능한 상태다 (이슈 #165).
// "normal" 과 반드시 구분해야 한다 — 모르는 것을 안전하다고 표시하면
// 실제 위험 수준의 값이 초록색으로 보인다.
export type AlertLevel =
  "unknown" | "normal" | "level1_caution" | "level2_warning" | "level3_critical";
export type AlertStatus = "active" | "resolved";

/** AI 이상징후 상태 (연구용). **AlertLevel 과 절대 섞지 않는다.**
 *
 *  앞의 넷은 "판단하지 않았다" 이고 normal_pattern 으로 변환되지 않는다.
 *  두 타입을 서로 변환하는 함수를 만들지 않는다 — 만들면 언젠가 누가 호출하고,
 *  그 순간 연구용 참고 지표가 산업안전 경보 등급으로 둔갑한다. */
export type AiAnomalyStatus =
  | "model_not_ready"
  | "insufficient_data"
  | "stale_data"
  | "feature_mismatch"
  | "normal_pattern"
  | "anomaly_candidate"
  | "anomaly";

/** 판단하지 않은 상태. 화면은 이것을 "정상" 이 아니라 "데이터 부족" 으로 그린다. */
export const AI_UNDECIDED: readonly AiAnomalyStatus[] = [
  "model_not_ready",
  "insufficient_data",
  "stale_data",
  "feature_mismatch",
] as const;

export interface AiContributor {
  metric: string;
  error: number;
}

export interface AiAnomalyState {
  node_id: NodeId;
  status: AiAnomalyStatus;
  /** 판단 불가일 때 null. 0 으로 채우면 "완벽히 정상" 으로 읽힌다. */
  score: number | null;
  threshold: number | null;
  consecutive_exceedances: number;
  top_contributors: AiContributor[];
  model_version: string | null;
  evaluated_at: string;
  source_mode?: "live" | "simulation" | null;
  /** 항상 true. 화면이 Research 배지를 그리는 근거다. */
  is_research_only: boolean;
}
export type CoordinateSystem = "model-local" | "demo-local" | "ship-visual";
export type VisualMapping = "none" | "demo-to-ship-scale";

export interface Position3D {
  x_m: number;
  y_m: number;
  z_m: number;
}

export interface SensorReading {
  metric: MetricKey;
  value: number;
  sampled_at: string;
}

export interface SensorNodeState {
  node_id: NodeId;
  readings: Partial<Record<MetricKey, SensorReading>>;
  battery_pct: number | null;
  wifi_rssi_dbm: number | null;
  connection_status: "online" | "offline";
  last_seen_at: string | null;
  calibration_status?: Partial<Record<CalibrationKey, CalibrationState>>;
  // Spec 10_UI_FLOW §3.2: per-node alert level. Optional — derived from
  // readings when the backend has not pushed an explicit level yet.
  alert_level?: AlertLevel;
  // Data contract §2: distinguishes live vs injected simulation data.
  source_mode?: "live" | "simulation";
}

export type CalibrationKey =
  "co_calibration_status" | "h2s_calibration_status" | "mq2_calibration_status";

export type CalibrationState = "not_started" | "in_progress" | "done" | "error";

export interface WearableState {
  node_id: NodeId;
  o2_pct: number | null;
  // 실측 좌표만 저장한다. 화면 표시 좌표는 뷰마다 매핑 프리셋이 다르므로
  // (모니터링=FILL, 트윈 상세=TRUE SCALE) 저장하지 않고 utils/coordinates 로
  // 렌더 시점에 파생한다. 둘을 같이 저장하면 어느 값이 실측인지 다시 모호해진다.
  position_raw: Position3D | null;
  // position_raw 가 측정된 좌표계. 'ship-visual' 이면 이미 표시 좌표이므로
  // 비율 매핑을 적용하지 않는다 (중복 변환 방지).
  source_coordinate_system?: CoordinateSystem;
  source_mode?: "live" | "simulation";
  fall_detected: boolean;
  heart_rate: number | null;
  battery_pct: number | null;
  connection_status: "online" | "offline";
  last_seen_at?: string | null;
  // Spec 10_UI_FLOW §3.3: UWB location quality. Optional — not wired until the
  // UWB pipeline lands (#121); rendered as a "대기" (pending) state meanwhile.
  location_quality?: { quality_score: number; anchor_count: number } | null;
}

export interface AlertState {
  alert_key: AlertKey;
  node_id: NodeId;
  level: AlertLevel;
  status: AlertStatus;
  trigger_value: number;
  threshold: number;
  activated_at: string;
  resolved_at: string | null;
}

export interface ConnectionStatus {
  backend_connected: boolean;
  mqtt_connected: boolean;
  websocket_connected: boolean;
}
