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
  x: number;
  y: number;
  z: number;
  timestamp: string;
}

export type WSMessage = SnapshotMessage | AlertMessage | LocationMessage;
