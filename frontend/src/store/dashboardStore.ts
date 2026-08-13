import { create } from "zustand";
import type {
  AlertKey,
  AlertState,
  ConnectionStatus,
  MetricKey,
  NodeId,
  SensorNodeState,
  WearableState,
} from "../types";

interface DashboardStore {
  sensor_nodes: Record<NodeId, SensorNodeState>;
  wearable: WearableState | null;
  active_alerts: Record<AlertKey, AlertState>;
  connection_status: ConnectionStatus;

  setSensorNodeReading: (
    node_id: NodeId,
    metric: MetricKey,
    value: number,
    timestamp: string,
  ) => void;
  setSensorNodeStatus: (node_id: NodeId, patch: Partial<SensorNodeState>) => void;
  setWearableState: (state: WearableState) => void;
  setWearablePosition: (node_id: NodeId, x: number, y: number, z: number, timestamp: string) => void;
  addAlert: (alert: AlertState) => void;
  resolveAlert: (alert_key: AlertKey) => void;
  setConnectionStatus: (patch: Partial<ConnectionStatus>) => void;
  hydrateSnapshot: (
    nodes: Record<string, Partial<SensorNodeState>>,
    alerts: Record<string, AlertState>,
  ) => void;
}

const initial_connection_status: ConnectionStatus = {
  backend_connected: false,
  mqtt_connected: false,
  websocket_connected: false,
};

export const useDashboardStore = create<DashboardStore>((set) => ({
  sensor_nodes: {},
  wearable: null,
  active_alerts: {},
  connection_status: initial_connection_status,

  setSensorNodeReading: (node_id, metric, value, timestamp) =>
    set((state) => {
      const existing = state.sensor_nodes[node_id] ?? {
        node_id,
        readings: {},
        battery_pct: null,
        wifi_rssi_dbm: null,
        connection_status: "online" as const,
        last_seen_at: null,
      };
      return {
        sensor_nodes: {
          ...state.sensor_nodes,
          [node_id]: {
            ...existing,
            readings: {
              ...existing.readings,
              [metric]: { metric, value, sampled_at: timestamp },
            },
            last_seen_at: timestamp,
          },
        },
      };
    }),

  setSensorNodeStatus: (node_id, patch) =>
    set((state) => {
      // node_status는 gas/env 측정값보다 먼저 도착할 수 있으므로(#106), 기존
      // entry가 없으면 setSensorNodeReading과 동일한 기본값으로 새로 만든다.
      const existing = state.sensor_nodes[node_id] ?? {
        node_id,
        readings: {},
        battery_pct: null,
        wifi_rssi_dbm: null,
        connection_status: "online" as const,
        last_seen_at: null,
      };
      return {
        sensor_nodes: {
          ...state.sensor_nodes,
          [node_id]: { ...existing, ...patch },
        },
      };
    }),

  setWearableState: (wearable) => set({ wearable }),

  setWearablePosition: (node_id, x, y, z, timestamp) =>
    set((state) => {
      const existing = state.wearable ?? {
        node_id,
        o2_pct: null,
        position: null,
        fall_detected: false,
        heart_rate: null,
        battery_pct: null,
        connection_status: "online" as const,
      };
      return {
        wearable: {
          ...existing,
          node_id,
          position: { x_m: x, y_m: y, z_m: z },
          last_seen_at: timestamp,
        },
      };
    }),

  addAlert: (alert) =>
    set((state) => ({
      active_alerts: { ...state.active_alerts, [alert.alert_key]: alert },
    })),

  resolveAlert: (alert_key) =>
    set((state) => {
      const next = { ...state.active_alerts };
      delete next[alert_key];
      return { active_alerts: next };
    }),

  setConnectionStatus: (patch) =>
    set((state) => ({
      connection_status: { ...state.connection_status, ...patch },
    })),

  // WS 연결 직후 snapshot 메시지로 현재 상태를 한 번에 채운다 (#106) — 이게
  // 없으면 새로고침할 때마다 경보가 다시 발생하기 전까지 화면이 비어 보인다.
  hydrateSnapshot: (nodes, alerts) =>
    set((state) => {
      const sensor_nodes = { ...state.sensor_nodes };
      for (const [node_id, patch] of Object.entries(nodes)) {
        const existing = sensor_nodes[node_id] ?? {
          node_id,
          readings: {},
          battery_pct: null,
          wifi_rssi_dbm: null,
          connection_status: "online" as const,
          last_seen_at: null,
        };
        sensor_nodes[node_id] = { ...existing, ...patch };
      }
      return { sensor_nodes, active_alerts: { ...state.active_alerts, ...alerts } };
    }),
}));
