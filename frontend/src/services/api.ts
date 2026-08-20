import type { MetricKey } from "../types";
import { ApiError, fetchApi } from "./fetchWithAuth";

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
  // 경보 발생 시점에 해당 노드를 착용하고 있던 작업자 (이슈 #136).
  // 배정 이력이 없던 시절의 경보는 전부 null 이다.
  worker_id: number | null;
  worker_name: string | null;
  worker_employee_no: string | null;
  worker_emergency_contact: string | null;
}

export interface AlertEventFilter {
  nodeId?: string;
  alertKey?: string;
  status?: "active" | "resolved";
  start?: string;
  end?: string;
  limit?: number;
}

export type ThresholdLevel = "level1_caution" | "level2_warning" | "level3_critical";
export type ThresholdDirection = "above" | "below";

export interface Threshold {
  metric: string;
  level: ThresholdLevel;
  direction: ThresholdDirection;
  enter_threshold: number;
  exit_threshold: number;
  enter_for_ms: number;
  exit_for_ms: number;
  updated_at: string | null;
}

export interface ThresholdUpdate {
  direction: ThresholdDirection;
  enter_threshold: number;
  exit_threshold: number;
  enter_for_ms: number;
  exit_for_ms: number;
}

export interface HealthStatus {
  status: string;
  mqtt: { connected: boolean };
  db: { pool_initialized: boolean };
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
  return fetchApi<SensorDataPoint[]>(`/api/sensor-data?${params.toString()}`);
}

export async function fetchAlertEvents(filter: AlertEventFilter = {}): Promise<AlertEvent[]> {
  const params = new URLSearchParams();
  if (filter.nodeId) params.set("node_id", filter.nodeId);
  if (filter.alertKey) params.set("alert_key", filter.alertKey);
  if (filter.status) params.set("status", filter.status);
  if (filter.start) params.set("start", filter.start);
  if (filter.end) params.set("end", filter.end);
  if (filter.limit) params.set("limit", String(filter.limit));
  return fetchApi<AlertEvent[]>(`/api/alert-events?${params.toString()}`);
}

export async function fetchThresholds(): Promise<Threshold[]> {
  return fetchApi<Threshold[]>("/api/thresholds");
}

export async function updateThreshold(
  metric: string,
  level: ThresholdLevel,
  payload: ThresholdUpdate,
): Promise<Threshold> {
  return fetchApi<Threshold>(`/api/thresholds/${metric}/${level}`, {
    method: "PUT",
    csrf: true,
    body: JSON.stringify(payload),
  });
}

// ── 작업자 명부 + 웨어러블 배정 (이슈 #136, FR-306) ─────────────────────
// 작업자는 로그인 주체가 아니다. 대시보드 계정과 다른 개념이라 인증과 무관하게 쓴다.

export interface Worker {
  id: number;
  employee_no: string;
  name: string;
  phone: string | null;
  emergency_contact: string | null;
}

export interface WorkerInput {
  employee_no: string;
  name: string;
  phone?: string | null;
  emergency_contact?: string | null;
}

/** 현재 착용 중인 배정. node_id 로 사람을 찾을 때 쓴다. */
export interface AssignedWorker {
  worker_id: number;
  employee_no: string;
  name: string;
  phone: string | null;
  emergency_contact: string | null;
  node_id: string;
  assigned_at: string;
}

export async function fetchWorkers(): Promise<Worker[]> {
  return fetchApi<Worker[]>("/api/workers");
}

export async function fetchAssignments(): Promise<AssignedWorker[]> {
  return fetchApi<AssignedWorker[]>("/api/workers/assignments");
}

export async function createWorker(payload: WorkerInput): Promise<Worker> {
  return fetchApi<Worker>("/api/workers", {
    method: "POST",
    csrf: true,
    body: JSON.stringify(payload),
  });
}

export async function deleteWorker(workerId: number): Promise<void> {
  await fetchApi<void>(`/api/workers/${workerId}`, { method: "DELETE", csrf: true });
}

export async function assignWorker(workerId: number, nodeId: string): Promise<void> {
  await fetchApi<void>(`/api/workers/${workerId}/assign`, {
    method: "POST",
    csrf: true,
    body: JSON.stringify({ node_id: nodeId }),
  });
}

export async function releaseNode(nodeId: string): Promise<void> {
  await fetchApi<void>(`/api/workers/nodes/${nodeId}/release`, {
    method: "POST",
    csrf: true,
  });
}

export async function fetchHealth(): Promise<HealthStatus> {
  return fetchApi<HealthStatus>("/health");
}

export async function fetchMetrics(): Promise<Record<string, number>> {
  return fetchApi<Record<string, number>>("/api/metrics");
}

// ── 데모 시나리오 제어 (09_DEMO_SCENARIOS 4절) ────────────────────────
// 백엔드에서 기본 비활성이다. 꺼져 있으면 전 경로가 404 를 낸다.

export interface DemoScenario {
  name: string;
  label: string;
  description: string;
  default_nodes: string[];
  supports_duration: boolean;
  default_duration_s: number | null;
}

export interface DemoRunState {
  running: boolean;
  scenario: string | null;
  node_ids: string[];
  started_at: string | null;
}

/** 시나리오 목록. 기능이 꺼져 있으면 null 을 반환한다 (에러가 아니다). */
export async function fetchDemoScenarios(): Promise<DemoScenario[] | null> {
  try {
    return await fetchApi<DemoScenario[]>("/api/demo/scenarios");
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null;
    throw err;
  }
}

export async function fetchDemoStatus(): Promise<DemoRunState | null> {
  try {
    return await fetchApi<DemoRunState>("/api/demo/status");
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null;
    throw err;
  }
}

export async function runDemoScenario(
  scenario: string,
  duration_s?: number,
): Promise<DemoRunState> {
  return fetchApi<DemoRunState>("/api/demo/run", {
    method: "POST",
    csrf: true,
    body: JSON.stringify(duration_s ? { scenario, duration_s } : { scenario }),
  });
}

export async function stopDemoScenario(): Promise<DemoRunState> {
  return fetchApi<DemoRunState>("/api/demo/stop", { method: "POST", csrf: true });
}
