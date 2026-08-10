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

export type AlertLevel = "normal" | "level1_caution" | "level2_warning" | "level3_critical";
export type AlertStatus = "active" | "resolved";

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
}

export type CalibrationKey =
  | "co_calibration_status"
  | "h2s_calibration_status"
  | "mq2_calibration_status";

export type CalibrationState = "not_started" | "in_progress" | "done" | "error";

export interface WearableState {
  node_id: NodeId;
  o2_pct: number | null;
  position: { x_m: number; y_m: number; z_m: number } | null;
  fall_detected: boolean;
  heart_rate: number | null;
  battery_pct: number | null;
  connection_status: "online" | "offline";
  last_seen_at?: string | null;
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
