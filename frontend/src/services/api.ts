import type { MetricKey } from "../types";

// 상대 경로 기본값 — nginx(배포)와 vite dev proxy(개발) 둘 다 /api를 백엔드로
// 프록시하므로 프론트엔드가 :8000을 직접 호출할 필요가 없다 (이슈 #105).
export const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "";

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

export async function fetchThresholds(): Promise<Threshold[]> {
  const resp = await fetch(`${API_BASE}/api/thresholds`);
  if (!resp.ok) {
    throw new Error(`thresholds fetch failed: ${resp.status}`);
  }
  return (await resp.json()) as Threshold[];
}

export async function updateThreshold(
  metric: string,
  level: ThresholdLevel,
  payload: ThresholdUpdate,
): Promise<Threshold> {
  const resp = await fetch(`${API_BASE}/api/thresholds/${metric}/${level}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!resp.ok) {
    throw new Error(`threshold update failed: ${resp.status}`);
  }
  return (await resp.json()) as Threshold;
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

/** 서버가 한국어 detail 을 주면 그대로 보여준다 (사번 중복, 중복 배정 등). */
async function readError(resp: Response, fallback: string): Promise<never> {
  let detail = "";
  try {
    detail = ((await resp.json()) as { detail?: string }).detail ?? "";
  } catch {
    // 본문이 JSON 이 아니면 상태 코드만 쓴다
  }
  throw new Error(detail || `${fallback}: ${resp.status}`);
}

export async function fetchWorkers(): Promise<Worker[]> {
  const resp = await fetch(`${API_BASE}/api/workers`);
  if (!resp.ok) throw new Error(`workers fetch failed: ${resp.status}`);
  return (await resp.json()) as Worker[];
}

export async function fetchAssignments(): Promise<AssignedWorker[]> {
  const resp = await fetch(`${API_BASE}/api/workers/assignments`);
  if (!resp.ok) throw new Error(`assignments fetch failed: ${resp.status}`);
  return (await resp.json()) as AssignedWorker[];
}

export async function createWorker(payload: WorkerInput): Promise<Worker> {
  const resp = await fetch(`${API_BASE}/api/workers`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!resp.ok) await readError(resp, "작업자 등록 실패");
  return (await resp.json()) as Worker;
}

export async function deleteWorker(workerId: number): Promise<void> {
  const resp = await fetch(`${API_BASE}/api/workers/${workerId}`, { method: "DELETE" });
  if (!resp.ok) await readError(resp, "작업자 삭제 실패");
}

export async function assignWorker(workerId: number, nodeId: string): Promise<void> {
  const resp = await fetch(`${API_BASE}/api/workers/${workerId}/assign`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ node_id: nodeId }),
  });
  if (!resp.ok) await readError(resp, "배정 실패");
}

export async function releaseNode(nodeId: string): Promise<void> {
  const resp = await fetch(`${API_BASE}/api/workers/nodes/${nodeId}/release`, {
    method: "POST",
  });
  if (!resp.ok) await readError(resp, "배정 해제 실패");
}

export async function fetchHealth(): Promise<HealthStatus> {
  const resp = await fetch(`${API_BASE}/health`);
  if (!resp.ok) {
    throw new Error(`health fetch failed: ${resp.status}`);
  }
  return (await resp.json()) as HealthStatus;
}

export async function fetchMetrics(): Promise<Record<string, number>> {
  const resp = await fetch(`${API_BASE}/api/metrics`);
  if (!resp.ok) {
    throw new Error(`metrics fetch failed: ${resp.status}`);
  }
  return (await resp.json()) as Record<string, number>;
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
  const resp = await fetch(`${API_BASE}/api/demo/scenarios`);
  if (resp.status === 404) return null;
  if (!resp.ok) throw new Error(`demo scenarios fetch failed: ${resp.status}`);
  return (await resp.json()) as DemoScenario[];
}

export async function fetchDemoStatus(): Promise<DemoRunState | null> {
  const resp = await fetch(`${API_BASE}/api/demo/status`);
  if (resp.status === 404) return null;
  if (!resp.ok) throw new Error(`demo status fetch failed: ${resp.status}`);
  return (await resp.json()) as DemoRunState;
}

export async function runDemoScenario(
  scenario: string,
  duration_s?: number,
): Promise<DemoRunState> {
  const resp = await fetch(`${API_BASE}/api/demo/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(duration_s ? { scenario, duration_s } : { scenario }),
  });
  if (!resp.ok) throw new Error(`시나리오 실행 실패 (${resp.status})`);
  return (await resp.json()) as DemoRunState;
}

export async function stopDemoScenario(): Promise<DemoRunState> {
  const resp = await fetch(`${API_BASE}/api/demo/stop`, { method: "POST" });
  if (!resp.ok) throw new Error(`시나리오 중지 실패 (${resp.status})`);
  return (await resp.json()) as DemoRunState;
}
