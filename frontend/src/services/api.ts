import type { MetricKey } from "../types";

// 상대 경로 기본값 — nginx(배포)와 vite dev proxy(개발) 둘 다 /api를 백엔드로
// 프록시하므로 프론트엔드가 :8000을 직접 호출할 필요가 없다 (이슈 #105).
const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "";

export interface SensorDataPoint {
  time: string;
  value: number;
}

export interface AlertEvent {
  message_id: string;
  alert_id: string;
  source_node_id: string;
  alert_key: string;
  alert_type: string;
  level: string;
  trigger_value: number | null;
  threshold: number | null;
  metric: string | null;
  message: string;
  status: "active" | "resolved";
  schema_version: string;
  activated_at: string;
  resolved_at: string | null;
  published_at: string;
}

export interface AlertEventFilter {
  nodeId?: string;
  alertKey?: string;
  status?: "active" | "resolved";
  start?: string;
  end?: string;
  limit?: number;
}

export async function fetchSensorData(
  nodeId: string,
  metric: MetricKey,
  startIso: string,
  endIso: string,
  interval?: "1min",
): Promise<SensorDataPoint[]> {
  const params = new URLSearchParams({
    node_id: nodeId,
    metric,
    start: startIso,
    end: endIso,
  });
  if (interval) params.set("interval", interval);
  const resp = await fetch(`${API_BASE}/api/sensor-data?${params.toString()}`);
  if (!resp.ok) {
    throw new Error(`sensor-data fetch failed: ${resp.status}`);
  }
  return (await resp.json()) as SensorDataPoint[];
}

export async function fetchAlertEvents(filter: AlertEventFilter = {}): Promise<AlertEvent[]> {
  const params = new URLSearchParams();
  if (filter.nodeId) params.set("node_id", filter.nodeId);
  if (filter.alertKey) params.set("alert_key", filter.alertKey);
  if (filter.status) params.set("status", filter.status);
  if (filter.start) params.set("start", filter.start);
  if (filter.end) params.set("end", filter.end);
  if (filter.limit) params.set("limit", String(filter.limit));
  const resp = await fetch(`${API_BASE}/api/alert-events?${params.toString()}`);
  if (!resp.ok) {
    throw new Error(`alert-events fetch failed: ${resp.status}`);
  }
  return (await resp.json()) as AlertEvent[];
}

export async function fetchThresholds(): Promise<unknown[]> {
  const resp = await fetch(`${API_BASE}/api/thresholds`);
  if (!resp.ok) {
    throw new Error(`thresholds fetch failed: ${resp.status}`);
  }
  return (await resp.json()) as unknown[];
}

export async function fetchMetrics(): Promise<Record<string, number>> {
  const resp = await fetch(`${API_BASE}/api/metrics`);
  if (!resp.ok) {
    throw new Error(`metrics fetch failed: ${resp.status}`);
  }
  return (await resp.json()) as Record<string, number>;
}
