import type { ReactNode } from "react";
import { useEvacuationStatus } from "../hooks/useEvacuationStatus";
import type { NavTopology } from "../types/evacuation";
import type {
  EvacuationRouteMessage,
  RouteStatus,
  RouteUnavailableReason,
  RouteWarning,
} from "../types/ws";
import { EvacuationPlan } from "./EvacuationPlan";
import "../styles/evacuation.css";

/**
 * 비상 탈출 경로 패널 (docs/12_EVACUATION_ROUTE_SPEC.md §4.4).
 *
 * 목표 출구·거리·예상 시간·경고·차단 출구를 한 곳에 모으고 2D 평면도를 함께
 * 싣는다. 3D 튜브만으로는 "몇 미터인지, 몇 초 걸리는지"를 읽을 수 없다.
 */

const STATUS_LABEL: Record<RouteStatus, string> = {
  safe: "정상 경로",
  degraded: "위험구역 통과",
  no_safe_route: "안전 경로 없음",
  unavailable: "산출 불가",
};

/** 색만으로 상태를 전달하지 않는다 — 형태가 다른 마크를 함께 쓴다. */
const STATUS_MARK: Record<RouteStatus, string> = {
  safe: "●",
  degraded: "▲",
  no_safe_route: "■",
  unavailable: "—",
};

const UNAVAILABLE_LABEL: Record<RouteUnavailableReason, string> = {
  stale_position: "작업자 위치가 10초 이상 갱신되지 않았다",
  no_position: "작업자 위치를 받지 못했다",
  off_graph: "작업자가 등록된 통행 구조에서 너무 멀다",
  topology_invalid: "통행 구조 데이터가 검증을 통과하지 못했다",
  no_reachable_exit: "시작 지점에서 도달 가능한 출구가 없다",
};

const WARNING_LABEL: Record<RouteWarning, string> = {
  passes_hazard_level1: "L1 구역 통과",
  passes_hazard_level2: "L2 구역 통과",
  passes_hazard_level3: "L3 구역 통과",
  hazard_data_missing: "가스 분포 정보 없음 — 위험 가중 미적용",
  low_position_quality: "위치 정확도 낮음",
  long_snap_distance: "통로에서 떨어진 위치",
};

const BLOCKED_LABEL: Record<string, string> = {
  hazard_level3: "L3 위험구역",
  disabled: "관리자 폐쇄",
  unreachable: "도달 불가",
};

/** 값 없음(null)과 0 을 구분한다. 못 구한 것을 0 으로 그리면 안 된다. */
function num(value: number | null | undefined, digits = 0): string | null {
  return value === null || value === undefined ? null : value.toFixed(digits);
}

function duration(seconds: number | null | undefined): string | null {
  if (seconds === null || seconds === undefined) return null;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return m > 0 ? `${m}분 ${s}초` : `${s}초`;
}

function Fact({ label, value, unit }: { label: string; value: string | null; unit?: string }) {
  return (
    <div className="evac__fact">
      <dt>{label}</dt>
      <dd className={value === null ? "is-empty" : undefined}>
        {value ?? "—"}
        {value !== null && unit && <small>{unit}</small>}
      </dd>
    </div>
  );
}

interface EvacuationPanelProps {
  route: EvacuationRouteMessage | null;
  topology: NavTopology;
  /** 목 데이터로 그리는 중임을 화면이 숨기지 않는다. */
  mock?: boolean;
  children?: ReactNode;
}

/**
 * 통행 구조가 없어 기능 자체가 꺼진 상태 (FR-806).
 *
 * "안전 경로 없음"과 반드시 구분되어야 한다. 전자는 설정이 틀린 것이고 후자는
 * 실제 대피 상황이다. 둘을 같은 배너로 보여주면 관제사가 설정 오류를 위험 상황으로
 * 읽거나 그 반대가 된다.
 */
function FeatureDisabledBanner({ reason }: { reason: string | null }) {
  return (
    <div className="evac__banner evac__banner--muted" role="status">
      <strong>탈출 경로 기능 비활성 — 통행 구조 미설정</strong>
      <span>
        {reason ?? "사유가 보고되지 않았다."} 센서 수집과 가스 경보는 정상 동작한다.
      </span>
    </div>
  );
}

export function EvacuationPanel({ route, topology, mock = false, children }: EvacuationPanelProps) {
  const health = useEvacuationStatus();
  // health 가 null 이면 "알 수 없음"이다. 꺼짐으로 단정하지 않는다.
  const featureDisabled = health !== null && !health.enabled;

  // 목 모드에서는 화면을 가리지 않는다. 백엔드 없이 UI 를 확인하는 것이 목 모드의
  // 존재 이유인데, 기능이 꺼졌다고 내용을 지우면 시연 리허설이 막힌다.
  // 대신 아래에서 배너를 내용 위에 얹는다.
  if (!route || (featureDisabled && !mock)) {
    return (
      <section className="panel evac" aria-label="비상 탈출 경로">
        <div className="evac__head">
          <h2 className="evac__title">Emergency Egress / 비상 탈출 경로</h2>
        </div>
        {featureDisabled ? (
          <FeatureDisabledBanner reason={health.reason} />
        ) : (
          <div className="evac__banner evac__banner--muted" role="status">
            <strong>경로 정보 없음</strong>
            <span>웨어러블이 배정되지 않았거나 경로 서비스가 아직 응답하지 않았다.</span>
          </div>
        )}
        {children}
      </section>
    );
  }

  const status = route.route_status;
  const exit = topology.exits.find((e) => e.exit_id === route.target_exit_id);
  const warnings = route.warnings ?? [];
  const blocked = route.blocked_exits ?? [];
  const exitLabelById = new Map(topology.exits.map((e) => [e.exit_id, e.label]));

  return (
    <section className="panel evac" aria-label="비상 탈출 경로">
      <div className="evac__head">
        <h2 className="evac__title">Emergency Egress / 비상 탈출 경로</h2>
        <span className={`evac__status evac__status--${status}`}>
          <span className="evac__status-mark" aria-hidden="true">
            {STATUS_MARK[status]}
          </span>
          {STATUS_LABEL[status]}
        </span>
      </div>

      {children}

      {featureDisabled && <FeatureDisabledBanner reason={health.reason} />}

      {/* 안전 경로가 없어도 화면을 비우지 않는다. 최소 위험 경로를 계속 제시한다. */}
      {status === "no_safe_route" && (
        <div className="evac__banner" role="alert">
          <strong>안전 경로 없음 — 최소 위험 경로를 표시한다</strong>
          <span>사용 가능한 모든 출구가 L3 위험구역 뒤에 있다. 감독자 판단이 필요하다.</span>
        </div>
      )}

      {status === "unavailable" && (
        <div className="evac__banner evac__banner--muted" role="status">
          <strong>경로를 산출할 수 없다</strong>
          <span>
            {route.unavailable_reason
              ? UNAVAILABLE_LABEL[route.unavailable_reason]
              : "사유가 보고되지 않았다."}{" "}
            경로를 제시하지 못하는 동안에도 대피는 계속되어야 한다.
          </span>
        </div>
      )}

      <dl className="evac__facts">
        <Fact label="목표 출구" value={exit?.label ?? route.target_exit_id ?? null} />
        <Fact label="거리" value={num(route.total_length_m, 1)} unit="m" />
        <Fact label="예상 시간" value={duration(route.estimated_seconds)} />
        <Fact label="위험 가중" value={num(route.hazard_multiplier_max, 1)} unit="×" />
      </dl>

      <div className="evac__badges">
        {/* §7 한계 #2 — UWB 가 2D 라 작업자의 비계 층은 측정된 적이 없다.
            이 가정을 화면이 숨기면 관제사가 경로 시작점을 사실로 오해한다. */}
        <span className="evac__badge evac__badge--assumption">
          최하층 기준 · {route.assumed_level_id} 가정
        </span>
        {topology.is_provisional && (
          <span className="evac__badge evac__badge--provisional">통행 구조 가정값 (실측 미반영)</span>
        )}
        {warnings.map((w) => (
          <span key={w} className="evac__badge evac__badge--warn">
            {WARNING_LABEL[w]}
          </span>
        ))}
        {route.snap_distance_m !== null && route.snap_distance_m !== undefined && (
          <span className="evac__badge">통로까지 {route.snap_distance_m.toFixed(1)}m</span>
        )}
      </div>

      <EvacuationPlan
        topology={topology}
        waypoints={route.waypoints}
        route_status={status}
        target_exit_id={route.target_exit_id}
        blocked_exits={blocked}
      />

      {blocked.length > 0 && (
        <ul className="evac__blocked" aria-label="차단된 출구">
          {blocked.map((b) => (
            <li key={b.exit_id}>
              <span className="evac__blocked-mark" aria-hidden="true">
                ✕
              </span>
              <span>{exitLabelById.get(b.exit_id) ?? b.exit_id}</span>
              <span className="evac__blocked-reason">
                {BLOCKED_LABEL[b.reason] ?? b.reason}
              </span>
            </li>
          ))}
        </ul>
      )}

      {/* §1.1 면책 축약형 — 상시 표시한다. */}
      <p className="evac__disclaimer">
        산출된 경로는 참고 정보이며 현장 판단과 정식 대피 절차를 대체하지 않는다. 사전 등록된
        통행 구조에만 근거하며 임시 통로·구조물 변경·연기·시야·화재는 반영되지 않는다.
        {mock && " 현재 화면은 목 데이터다."}
      </p>
    </section>
  );
}
