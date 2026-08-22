import type { MetricKey } from "../types";
import type { WorkerExposureMessage } from "../types/ws";
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

/** 탈출 경로 기능 가용성 (FR-806). 통행 구조 검증에 실패하면 경로 기능만 꺼지고
 *  사유가 여기 실린다. optional 인 이유는 이 필드가 없는 구버전 백엔드에 붙어도
 *  화면이 깨지지 않아야 해서다. */
export interface EvacuationHealth {
  enabled: boolean;
  reason: string | null;
  /** 통행 구조가 실측 도면이 아니라 가정값인가 (OQ-V5). */
  provisional: boolean;
  node_count: number;
  edge_count: number;
  exit_count: number;
}

export interface HealthStatus {
  status: string;
  mqtt: { connected: boolean };
  db: { pool_initialized: boolean };
  evacuation?: EvacuationHealth;
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

// ── 누적 노출량 (FR-701~708, 11_EXPOSURE_DOSE_SPEC §6.2) ────────────────

/**
 * 활성 노출 윈도우 전체.
 *
 * 초기 로드 전용이다. 이후 갱신은 WebSocket 의 `worker_exposure` 가 맡는다 (§6.1).
 * REST 가 필요한 이유는 새로고침 직후다 — WS 는 다음 브로드캐스트(최대 5초)까지
 * 아무것도 보내지 않아서, 그동안 화면이 "노출량 데이터 없음"으로 보인다.
 */
export async function fetchExposureCurrent(): Promise<WorkerExposureMessage[]> {
  return fetchApi<WorkerExposureMessage[]>("/api/exposure/current");
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

// ── 사용자 관리 (AUTH-10, 이슈 #140) ────────────────────────────────

export interface AdminUser {
  id: number;
  username: string;
  display_name: string;
  role: "admin" | "supervisor" | "viewer";
  is_active: boolean;
  must_change_password: boolean;
  failed_login_attempts: number;
  locked_until: string | null;
}

export async function fetchUsers(): Promise<AdminUser[]> {
  return fetchApi<AdminUser[]>("/api/users");
}

export async function createUser(payload: {
  username: string;
  password: string;
  role: AdminUser["role"];
}): Promise<AdminUser> {
  return fetchApi<AdminUser>("/api/users", {
    method: "POST",
    csrf: true,
    body: JSON.stringify(payload),
  });
}

export async function updateUser(
  userId: number,
  patch: { role?: AdminUser["role"]; is_active?: boolean },
): Promise<AdminUser> {
  return fetchApi<AdminUser>(`/api/users/${userId}`, {
    method: "PATCH",
    csrf: true,
    body: JSON.stringify(patch),
  });
}

export async function resetUserPassword(
  userId: number,
): Promise<{ user: AdminUser; temporary_password: string }> {
  return fetchApi<{ user: AdminUser; temporary_password: string }>(
    `/api/users/${userId}/reset-password`,
    { method: "POST", csrf: true },
  );
}
