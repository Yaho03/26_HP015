import { create } from "zustand";
import { setThresholdTable, type ServerThreshold } from "../utils/alerts";
import type {
  AlertKey,
  AlertState,
  ConnectionStatus,
  MetricKey,
  NodeId,
  SensorNodeState,
  Position3D,
  WearableState,
} from "../types";

/** One point of a node's CO₂ trend buffer (10_UI_FLOW §3.2 미니 차트). */
export interface TrendPoint {
  t: number;
  v: number;
}

/** Trend window kept per node. Older points are dropped on write so the buffer
 *  cannot grow without bound during a long watch. */
export const CO2_TREND_WINDOW_MS = 60 * 60 * 1000;

interface DashboardStore {
  sensor_nodes: Record<NodeId, SensorNodeState>;
  co2_trend: Record<NodeId, TrendPoint[]>;
  wearable: WearableState | null;
  active_alerts: Record<AlertKey, AlertState>;
  connection_status: ConnectionStatus;
  /** 서버 임계값 (PRD FR-204). 비어 있으면 아직 못 받은 것. */
  thresholds: ServerThreshold[];

  setSensorNodeReading: (
    node_id: NodeId,
    metric: MetricKey,
    value: number,
    timestamp: string,
  ) => void;
  setSensorNodeStatus: (node_id: NodeId, patch: Partial<SensorNodeState>) => void;
  setWearableState: (state: WearableState) => void;
  setWearableO2Reading: (node_id: NodeId, value: number, timestamp: string) => void;
  setWearablePosition: (
    node_id: NodeId,
    x: number,
    y: number,
    z: number,
    timestamp: string,
    metadata?: Partial<Pick<WearableState, "position_raw" | "source_coordinate_system" | "source_mode">>,
  ) => void;
  addAlert: (alert: AlertState) => void;
  resolveAlert: (alert_key: AlertKey) => void;
  setConnectionStatus: (patch: Partial<ConnectionStatus>) => void;
  setThresholds: (rows: ServerThreshold[]) => void;
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
  co2_trend: {},
  wearable: null,
  active_alerts: {},
  connection_status: initial_connection_status,
  thresholds: [],

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
      const nodes = {
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
      if (metric !== "co2_ppm") return nodes;

      const t = Date.parse(timestamp);
      if (Number.isNaN(t)) return nodes;
      const cutoff = t - CO2_TREND_WINDOW_MS;
      const kept = (state.co2_trend[node_id] ?? []).filter((p) => p.t > cutoff);
      return {
        ...nodes,
        co2_trend: { ...state.co2_trend, [node_id]: [...kept, { t, v: value }] },
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

  // 웨어러블 O₂ 는 센서 노드 카드가 아니라 웨어러블 카드에 들어가야 한다
  // (10_UI_FLOW 3.3). node_id 가 wearable- 이면 여기로 보낸다.
  setWearableO2Reading: (node_id, value, timestamp) =>
    set((state) => ({
      wearable: {
        ...(state.wearable ?? {
          node_id,
          position_raw: null,
          fall_detected: false,
          heart_rate: null,
          battery_pct: null,
          connection_status: "online" as const,
        }),
        node_id,
        o2_pct: value,
        last_seen_at: timestamp,
      },
    })),

  setWearablePosition: (node_id, x, y, z, timestamp, metadata) =>
    set((state) => {
      const existing = state.wearable ?? {
        node_id,
        o2_pct: null,
        position_raw: null,
        fall_detected: false,
        heart_rate: null,
        battery_pct: null,
        connection_status: "online" as const,
      };
      // 구버전 백엔드는 position_raw 없이 x/y/z 만 보낸다. 그 경우 x/y/z 가 실측값이다.
      const rawPosition: Position3D = metadata?.position_raw ?? { x_m: x, y_m: y, z_m: z };
      return {
        wearable: {
          ...existing,
          ...metadata,
          node_id,
          position_raw: rawPosition,
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

  setThresholds: (rows) =>
    set((state) => {
      setThresholdTable(rows);
      // 노드 객체 참조를 새로 만들어 등급을 다시 그리게 한다. 등급 판정은
      // 컴포넌트가 렌더 시점에 하므로, 참조가 그대로면 새 임계값이 화면에
      // 반영되지 않는다 (이슈 #114 완료 조건: "변경 시 색상 즉시 반영").
      const sensor_nodes: Record<NodeId, SensorNodeState> = {};
      for (const [id, node] of Object.entries(state.sensor_nodes)) {
        sensor_nodes[id] = { ...node };
      }
      return {
        thresholds: rows,
        sensor_nodes,
        wearable: state.wearable ? { ...state.wearable } : null,
      };
    }),

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
