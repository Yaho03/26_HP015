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
import type { EvacuationRouteMessage, WorkerExposureMessage } from "../types/ws";

/** One point of a node's trend buffer (10_UI_FLOW §3.2 미니 차트). */
export interface TrendPoint {
  t: number;
  v: number;
}

/**
 * 트렌드를 쌓는 지표. O₂ 는 센서 노드가 아니라 웨어러블 값이라 제외한다
 * (10_UI_FLOW §3.3).
 */
export type TrendMetric = Exclude<MetricKey, "o2_pct">;

/** Trend window kept per node/metric. Older points are dropped on write so the
 *  buffer cannot grow without bound during a long watch. */
export const SENSOR_TREND_WINDOW_MS = 60 * 60 * 1000;

/**
 * 버퍼당 최대 점 수. 노드 5 × 지표 6 = 최대 30개 버퍼가 동시에 자라므로
 * 시간 창만으로는 부족하다. 샘플 주기가 빨라지면 창 안에서도 수천 점이 쌓인다.
 */
export const SENSOR_TREND_MAX_POINTS = 360;

/** ⑤ 스파크라인이 그리는 구간. 버퍼는 더 길게 갖고 표시만 잘라 쓴다. */
export const SPARKLINE_WINDOW_MS = 5 * 60 * 1000;

interface DashboardStore {
  sensor_nodes: Record<NodeId, SensorNodeState>;
  /**
   * 노드 × 지표별 링 버퍼. CO₂ 전용이던 것을 6종으로 일반화했다 —
   * ⑤ 노드별 센서 데이터가 지표마다 스파크라인을 그리기 때문이다.
   * 노드 단위로 객체를 새로 만들어, 한 노드의 갱신이 다른 노드를 구독하는
   * 셀렉터를 건드리지 않게 한다 (10_UI_FLOW §10.3).
   */
  sensor_trend: Record<NodeId, Partial<Record<TrendMetric, TrendPoint[]>>>;
  wearable: WearableState | null;
  active_alerts: Record<AlertKey, AlertState>;
  connection_status: ConnectionStatus;
  /** 서버 임계값 (PRD FR-204). 비어 있으면 아직 못 받은 것. */
  thresholds: ServerThreshold[];

  /**
   * 웨어러블 노드별 누적 노출량 (FR-701~708).
   *
   * 웨어러블 상태(`wearable`)와 합치지 않고 따로 둔다 — 갱신 주기가 다르다.
   * 노출량은 5초 스로틀이고 O₂·위치는 그보다 자주 온다. 한 객체에 넣으면
   * 노출량 프레임 하나가 웨어러블을 구독하는 모든 컴포넌트를 다시 그린다
   * (10_UI_FLOW §10.3 렌더링 영역 격리).
   */
  worker_exposure: Record<NodeId, WorkerExposureMessage>;
  /** 웨어러블 노드별 현재 탈출 경로 (FR-801~808). */
  evacuation_route: Record<NodeId, EvacuationRouteMessage>;

  setSensorNodeReading: (
    node_id: NodeId,
    metric: MetricKey,
    value: number,
    timestamp: string,
  ) => void;
  setSensorNodeStatus: (node_id: NodeId, patch: Partial<SensorNodeState>) => void;
  setWearableO2Reading: (node_id: NodeId, value: number, timestamp: string) => void;
  setWearablePosition: (
    node_id: NodeId,
    x: number,
    y: number,
    z: number,
    timestamp: string,
    metadata?: Partial<
      Pick<WearableState, "position_raw" | "source_coordinate_system" | "source_mode">
    >,
  ) => void;
  addAlert: (alert: AlertState) => void;
  resolveAlert: (alert_key: AlertKey) => void;
  setConnectionStatus: (patch: Partial<ConnectionStatus>) => void;
  setThresholds: (rows: ServerThreshold[]) => void;
  setWorkerExposure: (msg: WorkerExposureMessage) => void;
  setEvacuationRoute: (msg: EvacuationRouteMessage) => void;
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
  sensor_trend: {},
  wearable: null,
  active_alerts: {},
  connection_status: initial_connection_status,
  thresholds: [],
  worker_exposure: {},
  evacuation_route: {},

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
      // O₂ 는 웨어러블 소관이라 센서 노드 트렌드에 쌓지 않는다.
      if (metric === "o2_pct") return nodes;

      const t = Date.parse(timestamp);
      if (Number.isNaN(t)) return nodes;
      const cutoff = t - SENSOR_TREND_WINDOW_MS;
      const nodeBuffers = state.sensor_trend[node_id] ?? {};
      const kept = (nodeBuffers[metric] ?? []).filter((p) => p.t > cutoff);
      const next = [...kept, { t, v: value }];
      return {
        ...nodes,
        sensor_trend: {
          ...state.sensor_trend,
          [node_id]: {
            ...nodeBuffers,
            [metric]:
              next.length > SENSOR_TREND_MAX_POINTS
                ? next.slice(next.length - SENSOR_TREND_MAX_POINTS)
                : next,
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

  // 노드 단위로 통째 교체한다. 노출량은 지표별 부분 갱신이 없다 — 백엔드가
  // 매번 전체 metrics 를 함께 보낸다 (11_EXPOSURE_DOSE_SPEC.md §6.1). 부분 병합을
  // 하면 unavailable 로 내려간 지표가 이전 값에 가려져 화면에 남는다.
  setWorkerExposure: (msg) =>
    set((state) => ({
      worker_exposure: { ...state.worker_exposure, [msg.node_id]: msg },
    })),

  // 경로도 통째 교체다. waypoints 를 병합하면 옛 경로의 꼬리가 남는다.
  setEvacuationRoute: (msg) =>
    set((state) => ({
      evacuation_route: { ...state.evacuation_route, [msg.node_id]: msg },
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
