import type { CoordinateSystem, Position3D } from "./index";

export type WSMessageType =
  | "snapshot"
  | "alert"
  | "sensor_reading"
  | "node_status"
  | "node_connection"
  | "location"
  | "worker_exposure"
  | "evacuation_route";

/**
 * 경보 등급 — 와이어 값.
 *
 * types/index.ts 의 AlertLevel 과 달리 "unknown" 이 없다. "unknown" 은 프론트가
 * "아직 판정 불가"를 표현하려고 만든 값이고(이슈 #165), 서버는 보내지 않는다.
 */
export type WireAlertLevel = "normal" | "level1_caution" | "level2_warning" | "level3_critical";

export interface WSBaseMessage {
  type: WSMessageType;
}

export interface SnapshotMessage extends WSBaseMessage {
  type: "snapshot";
  nodes: Record<string, unknown>;
  alerts: Record<string, unknown>;
  /**
   * 재연결/새로고침 시 초기 상태 (#209). 경로는 route_id가 바뀔 때만 발행되므로
   * snapshot이 없으면 안정 상태의 현재 경로를 영영 못 받는다. 구버전 백엔드
   * 호환을 위해 optional.
   */
  worker_exposures?: WorkerExposureMessage[];
  evacuation_routes?: Record<string, EvacuationRouteMessage>;
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

export interface NodeConnectionMessage extends WSBaseMessage {
  type: "node_connection";
  node_id: string;
  connection_status: "online" | "offline";
  timestamp: string;
}

// ─────────────────────────────────────────────────────────────────────────────
// 작업자 누적 노출량 (FR-701~708)
// schemas/worker-exposure.schema.json · docs/11_EXPOSURE_DOSE_SPEC.md §6.1
// ─────────────────────────────────────────────────────────────────────────────

/** 노출 농도를 어디서 가져왔는가. IDW 보간값은 출처가 될 수 없다 (ADR-008). */
export type ExposureSource = "wearable_direct" | "nearest_node" | "unavailable";

/** dose 를 신뢰할 수 있는 정도 (11_EXPOSURE_DOSE_SPEC.md §4.4). */
export type ExposureTrustLevel = "high" | "medium" | "low";

/** 값을 산출할 수 없는 이유. limit_unverified = 노출 기준값 원문 대조 전이라 미시드. */
export type ExposureUnavailableReason =
  "uncalibrated" | "limit_unverified" | "no_position" | "no_source_node" | "sensor_error";

/**
 * 지표별 노출량.
 *
 * status 가 "unavailable" 이면 dose 관련 필드가 전부 없다. 화면은 이 상태를
 * **0% 로 렌더링하면 안 된다** — 측정 못 한 것을 "노출 없음"으로 보여주면
 * 안전하다고 오해한다 (§6.4).
 */
export interface ExposureDoseMetric {
  status: "active" | "unavailable";
  reason?: ExposureUnavailableReason;
  exposure_source?: ExposureSource;
  source_node_id?: string | null;
  /** 작업자와 농도를 가져온 노드 사이의 2D 거리. 멀수록 추정이 약하다. */
  source_distance_m?: number | null;
  /** 누적 노출량 (ppm·min). 한 윈도우 안에서 단조 증가한다. */
  dose_ppm_min?: number | null;
  dose_limit_ppm_min?: number | null;
  /** dose / limit. 1.0 = 8시간 기준 소진. 1.0 을 넘을 수 있다. */
  dose_fraction?: number | null;
  /** 전 노드 최댓값 기준 누적. 표시 전용이며 경보 판정에 쓰지 않는다 (ADR-008). */
  dose_worst_case_ppm_min?: number | null;
  twa_8h_ppm?: number | null;
  twa_15min_ppm?: number | null;
  stel_limit_ppm?: number | null;
  stel_exceeded?: boolean;
  peak_ppm?: number | null;
  peak_at?: string | null;
  alert_level?: WireAlertLevel;
}

/**
 * O₂ 노출.
 *
 * 산소는 몸에 "축적"되지 않는다. 결핍 상태에 노출된 **시간**을 누적한다 (§2.4).
 */
export interface ExposureO2Metric {
  status: "active" | "unavailable";
  reason?: "sensor_error" | "not_connected" | "no_position";
  exposure_source?: ExposureSource;
  source_node_id?: string | null;
  source_distance_m?: number | null;
  /** O₂ < 19.5% 누적 초. */
  o2_deficient_s?: number;
  /** O₂ < 16.0% 누적 초. */
  o2_severe_s?: number;
  /** O₂ > 23.5% 누적 초 (화재 위험). */
  o2_enriched_s?: number;
  o2_min_pct?: number | null;
  alert_level?: WireAlertLevel;
}

export interface WorkerExposureMessage extends WSBaseMessage {
  type: "worker_exposure";
  /** workers.id. 웨어러블 미배정이면 null. */
  worker_id: number | null;
  worker_name: string;
  node_id: string;
  exposure_id: string;
  window_start: string;
  window_source?: "assignment" | "manual_reset" | "shift_rollover";
  /** 윈도우 경과 초. 측정 공백을 포함한다. */
  elapsed_s: number;
  /** 실제로 적산에 반영된 초 (elapsed_s - data_gap_s). */
  accumulated_s: number;
  /** 샘플이 없어 적산하지 못한 초. 이만큼 dose 는 **과소평가**되어 있다. */
  data_gap_s: number;
  trust_level: ExposureTrustLevel;
  timestamp: string;
  metrics: {
    co2_ppm?: ExposureDoseMetric;
    co_ppm?: ExposureDoseMetric;
    h2s_ppm?: ExposureDoseMetric;
    o2_pct?: ExposureO2Metric;
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// 비상 탈출 경로 (FR-801~808)
// schemas/evacuation-route.schema.json · docs/12_EVACUATION_ROUTE_SPEC.md §4.1
// ─────────────────────────────────────────────────────────────────────────────

/**
 * 경로 상태.
 *
 * no_safe_route 는 "경로 없음"이 아니다. level3 구역을 지나는 **최소 위험 경로**를
 * 여전히 제시한다. 대피 중에 빈 화면을 주는 것이 최악이라서다 (§3.5).
 */
export type RouteStatus = "safe" | "degraded" | "no_safe_route" | "unavailable";

export type RouteUnavailableReason =
  "stale_position" | "no_position" | "off_graph" | "topology_invalid" | "no_reachable_exit";

export type NavEdgeKind = "walk" | "scaffold_plank" | "ladder" | "hatch";

export interface RouteWaypoint {
  seq: number;
  /** seq 0 은 작업자의 실측 위치라 그래프 노드가 아니다 → null. */
  nav_node_id?: string | null;
  x_m: number;
  y_m: number;
  z_m: number;
  level_id: string;
  /** 마지막 waypoint 는 null. */
  edge_kind_to_next?: NavEdgeKind | null;
  label?: string;
}

export interface BlockedExit {
  exit_id: string;
  reason: "hazard_level3" | "disabled" | "unreachable";
}

export type RouteWarning =
  | "passes_hazard_level1"
  | "passes_hazard_level2"
  | "passes_hazard_level3"
  | "hazard_data_missing"
  | "low_position_quality"
  | "long_snap_distance";

export interface EvacuationRouteMessage extends WSBaseMessage {
  type: "evacuation_route";
  route_id: string;
  node_id: string;
  worker_id?: number | null;
  worker_name?: string;
  computed_at: string;
  route_status: RouteStatus;
  unavailable_reason?: RouteUnavailableReason;
  /**
   * 항상 "ship-visual" (실제 선박 치수, TRUE SCALE 균일 배율).
   * FILL 프리셋은 비균일이라 거리가 왜곡되어 경로 계산에 쓸 수 없다 (ADR-010).
   * 프론트는 추가 비율 매핑 없이 Z-up → Y-up 축 변환만 적용한다.
   */
  coordinate_system: "ship-visual";
  /**
   * 작업자가 있다고 **가정한** 비계 층. UWB 측위가 2D 라 실제 층은 알 수 없다.
   * 화면이 이 가정을 숨기면 안 된다 (§7 한계 #2).
   */
  assumed_level_id: string;
  target_exit_id?: string | null;
  entry_nav_node_id?: string | null;
  snap_distance_m?: number | null;
  total_length_m?: number | null;
  total_cost?: number | null;
  estimated_seconds?: number | null;
  hazard_multiplier_max?: number | null;
  switch_reason?:
    "initial" | "position_moved" | "hazard_changed" | "topology_changed" | "route_blocked" | null;
  waypoints: RouteWaypoint[];
  blocked_exits?: BlockedExit[];
  warnings?: RouteWarning[];
}

export type WSMessage =
  | SnapshotMessage
  | AlertMessage
  | LocationMessage
  | SensorReadingMessage
  | NodeStatusMessage
  | NodeConnectionMessage
  | WorkerExposureMessage
  | EvacuationRouteMessage;
