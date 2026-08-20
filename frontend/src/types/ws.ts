import type { CoordinateSystem, Position3D } from "./index";

export type WSMessageType = "snapshot" | "alert" | "sensor_reading" | "node_status" | "location";

export interface WSBaseMessage {
  type: WSMessageType;
}

export interface SnapshotMessage extends WSBaseMessage {
  type: "snapshot";
  nodes: Record<string, unknown>;
  alerts: Record<string, unknown>;
}

export interface AlertMessage extends WSBaseMessage {
  type: "alert";
  node_id: string;
  metric: string;
  from_level: string;
  to_level: string;
  value: number;
  threshold: number;
  timestamp: string;
}

export interface LocationMessage extends WSBaseMessage {
  type: "location";
  node_id: string;
  timestamp: string;
  // 하위호환 — 구버전 백엔드는 좌표계 없이 x/y/z 만 보낸다.
  // 새 코드는 position_raw 를 쓰고, 없을 때만 이 값으로 폴백한다.
  x: number;
  y: number;
  z: number;
  // 실측 좌표와 그 좌표계. 표시 좌표는 프론트가 뷰별로 파생하므로 전송하지 않는다.
  position_raw?: Position3D;
  source_coordinate_system?: CoordinateSystem;
  source_mode?: "live" | "simulation";
}

/** 평상시 센서 값 브로드캐스트 (#106). (node_id, metric) 별 1초 스로틀. */
export interface SensorReadingMessage extends WSBaseMessage {
  type: "sensor_reading";
  node_id: string;
  metric: string;
  value: number;
  timestamp: string;
}

export interface NodeStatusMessage extends WSBaseMessage {
  type: "node_status";
  node_id: string;
  battery_pct: number | null;
  wifi_rssi_dbm: number | null;
  sensors_online: string[];
  sensors_error: string[];
  timestamp: string;
}

export type WSMessage =
  | SnapshotMessage
  | AlertMessage
  | LocationMessage
  | SensorReadingMessage
  | NodeStatusMessage;
