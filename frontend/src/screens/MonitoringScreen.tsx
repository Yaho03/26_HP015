import { useEffect, useMemo, useRef, useState } from "react";
import { useDashboardStore } from "../store/dashboardStore";
import { RiskDetailPanel } from "../components/RiskDetailPanel";
import { RiskLogPanel } from "../components/RiskLogPanel";
import { SensorSummaryPanel } from "../components/SensorSummaryPanel";
import { AlertBanner } from "../components/AlertBanner";
import { SummaryBar } from "../components/SummaryBar";
import { TwinHeatmapPanel } from "../components/TwinHeatmapPanel";
import { WearableStrip } from "../components/WearableStrip";
import { IconWarning } from "../components/icons";
import { classifyMetric, LEVEL_RANK, nodeAlertLevel } from "../utils/alerts";
import { metricFromAlertKey } from "../utils/alertLabels";
import { splitNodes } from "../utils/consoleSplit";
import { mostUrgentProjection, type Projection } from "../utils/projection";
import { useStableLevels } from "../hooks/useStableLevels";
import { freshnessAt, useFreshness } from "../hooks/useFreshness";
import { useAssignments } from "../hooks/useAssignments";
import { fetchRoute } from "../services/evacuationApi";
import {
  displayPositionFor,
  UNIFORM_PRESET,
  PRIMARY_WEARABLE,
  SENSOR_SCREEN_ORDER,
  SENSOR_SHIP_POSITIONS,
  shouldMapToShip,
  WEARABLE_SCREEN_ORDER,
} from "../utils/coordinates";
import type { SensorSample } from "../utils/idw";
import type { AlertLevel, AlertState, SensorNodeState } from "../types";
import type { RouteOverlay } from "../types/evacuation";
import { nodeLastSeenAt } from "../utils/nodes";

// Spec 10_UI_FLOW §3.1: fixed sensor-01~04 + wearable-01 slots. Slots render in
// a "대기" state until their node reports (live wiring tracked by #106/#121).
const SENSOR_SLOTS = [...SENSOR_SCREEN_ORDER];
// ⑤ 는 슬롯을 고정해 자리를 비워 둔다. 보고하지 않는 작업자가 목록에서 조용히
// 사라지면 "두 명이 들어갔는데 한 명만 보인다" 를 알아챌 방법이 없다.
const WEARABLE_SLOTS = [...WEARABLE_SCREEN_ORDER];
type DistributionMetric = "co2_ppm" | "co_ppm" | "h2s_ppm";
const PLAN_METRICS: readonly DistributionMetric[] = ["co2_ppm", "co_ppm", "h2s_ppm"];

function isDistributionMetric(metric: string): metric is DistributionMetric {
  return PLAN_METRICS.includes(metric as DistributionMetric);
}

function canUseDistributionMetric(
  node: SensorNodeState | undefined,
  metric: DistributionMetric,
): boolean {
  if (!node?.readings?.[metric]) return false;
  if (metric === "co_ppm") return node.calibration_status?.co_calibration_status === "done";
  if (metric === "h2s_ppm") return node.calibration_status?.h2s_calibration_status === "done";
  return true;
}

function selectDistributionMetric(
  nodes: Record<string, SensorNodeState>,
  activeAlerts: AlertState[],
): DistributionMetric | null {
  const alertCandidate = activeAlerts
    .map((alert) => ({
      alert,
      metric: metricFromAlertKey(alert.alert_key),
    }))
    .filter(
      (candidate): candidate is { alert: AlertState; metric: DistributionMetric } =>
        isDistributionMetric(candidate.metric) &&
        LEVEL_RANK[candidate.alert.level] >= LEVEL_RANK.level1_caution &&
        nodes[candidate.alert.node_id]?.connection_status === "online" &&
        canUseDistributionMetric(nodes[candidate.alert.node_id], candidate.metric),
    )
    .sort((a, b) => {
      const levelDelta = LEVEL_RANK[b.alert.level] - LEVEL_RANK[a.alert.level];
      if (levelDelta !== 0) return levelDelta;
      return b.alert.activated_at.localeCompare(a.alert.activated_at);
    })[0];
  if (alertCandidate) return alertCandidate.metric;

  // 첫 경보 이벤트가 아직 도착하지 않은 순간에도, 임계값을 넘은 현재값이 있으면
  // 원인 가스를 고른다. 온도·습도 같은 비가스 지표는 분포 후보에서 제외한다.
  let best: { metric: DistributionMetric; level: AlertLevel } | null = null;
  for (const id of SENSOR_SLOTS) {
    const node = nodes[id];
    if (!node || node.connection_status !== "online") continue;
    for (const metric of PLAN_METRICS) {
      if (!canUseDistributionMetric(node, metric)) continue;
      const reading = node.readings[metric];
      if (!reading) continue;
      const level = classifyMetric(metric, reading.value);
      if (
        LEVEL_RANK[level] < LEVEL_RANK.level1_caution ||
        (best && LEVEL_RANK[level] <= LEVEL_RANK[best.level])
      ) {
        continue;
      }
      best = { metric, level };
    }
  }
  return best?.metric ?? null;
}

export function MonitoringScreen({
  onOpenEventLog,
}: {
  onOpenEventLog?: (filter: { nodeId?: string; level?: string }) => void;
}) {
  const nodes = useDashboardStore((s) => s.sensor_nodes);
  const trends = useDashboardStore((s) => s.sensor_trend);
  const wearables = useDashboardStore((s) => s.wearables);
  // 셀렉터에서 배열을 새로 만들면 안 된다. useSyncExternalStore 가 매 스냅숏을
  // 다른 참조로 보고 무한 루프에 빠진다 — 스토어에 있는 객체를 그대로 구독하고
  // 파생은 렌더 안에서 한다.
  const alertMap = useDashboardStore((s) => s.active_alerts);
  const activeAlerts = useMemo(
    () => Object.values(alertMap).filter((a) => a.status === "active"),
    [alertMap],
  );
  const thresholdsLoaded = useDashboardStore((s) => s.thresholds.length > 0);
  const { workerFor } = useAssignments();
  const [focusWearableId, setFocusWearableId] = useState<string | null>(null);
  const [fullscreen, setFullscreen] = useState(false);
  const consoleRef = useRef<HTMLDivElement>(null);

  // 노드 정보가 아직 없으면 판정 불가다 (이슈 #165). normal 로 떨어뜨리면
  // 데이터 없는 자리가 안전한 자리로 보인다.
  const measured = useMemo(() => {
    const out: Record<string, AlertLevel> = {};
    for (const id of SENSOR_SLOTS) {
      out[id] = nodes[id] ? nodeAlertLevel(nodes[id]) : "unknown";
    }
    return out;
  }, [nodes]);

  // 임계값 경계에 걸친 값은 초 단위로 등급을 뒤집는다. 그대로 두면 노드가
  // ② ↔ ③ 을 오가며 칸 비율과 카드 자리가 계속 바뀐다. 여기서 한 번 누르면
  // 카운트·분할·높이·정렬이 전부 같은 값을 본다.
  // **상승은 즉시, 하강만 지연이다** — 이 훅은 위험이 아니라 안심을 늦춘다.
  const levels = useStableLevels(measured);
  const levelOf = (id: string): AlertLevel => levels[id] ?? "unknown";

  const distributionMetric = useMemo(
    () => selectDistributionMetric(nodes, activeAlerts),
    [activeAlerts, nodes],
  );
  // 분포가 대기 중일 때도 TwinHeatmapPanel이 받을 지표는 필요하므로, 렌더용
  // 기본값만 CO₂로 둔다. 이 값으로 분포를 활성화하지는 않는다.
  const planMetric: DistributionMetric = distributionMetric ?? "co2_ppm";

  const counts: Record<AlertLevel, number> = {
    unknown: 0,
    normal: 0,
    level1_caution: 0,
    level2_warning: 0,
    level3_critical: 0,
  };
  for (const id of SENSOR_SLOTS) {
    const node = nodes[id];
    if (node && node.connection_status === "online") counts[levelOf(id)] += 1;
  }

  // ② 스트립 입력. 온라인 노드 중 등급이 가장 높은 하나 — 동급이면 슬롯 순서상
  // 앞선 노드를 잡는다. 오프라인 노드는 멈춘 값이라 "최악" 의 근거가 될 수 없다.
  let worstNodeId: string | null = null;
  let worstLevel: AlertLevel = "normal";
  for (const id of SENSOR_SLOTS) {
    if (nodes[id]?.connection_status !== "online") continue;
    const level = levelOf(id);
    if (worstNodeId === null || LEVEL_RANK[level] > LEVEL_RANK[worstLevel]) {
      worstNodeId = id;
      worstLevel = level;
    }
  }

  // 전 노드에서 가장 심각한 도달 예측. 경보가 아니라 표시 전용이다
  // (06_ALERT_RULES §8.2) — levelOf() 나 counts 에 절대 반영하지 않는다.
  const projection = useMemo(() => {
    let best: Projection | null = null;
    for (const id of SENSOR_SLOTS) {
      if (nodes[id]?.connection_status !== "online") continue;
      const p = mostUrgentProjection(trends[id]);
      if (!p) continue;
      const rank = best ? LEVEL_RANK[p.level] - LEVEL_RANK[best.level] : 1;
      if (rank > 0 || (rank === 0 && best && p.minutes < best.minutes)) best = p;
    }
    return best;
  }, [nodes, trends]);

  // ② 배너에 띄울 경보 — 활성 경보 중 가장 높은 등급, 동급이면 가장 최근.
  const banner = useMemo(() => {
    let worst = null as (typeof activeAlerts)[number] | null;
    for (const a of activeAlerts) {
      if (!worst) {
        worst = a;
        continue;
      }
      const rank = LEVEL_RANK[a.level] - LEVEL_RANK[worst.level];
      if (rank > 0 || (rank === 0 && a.activated_at > worst.activated_at)) worst = a;
    }
    return worst;
  }, [activeAlerts]);

  // ① 탈출로. **경고(L2) 이상에서만 그린다** — 평상시 상시 표시하면 선이 배경이
  // 되어, 정작 대피해야 할 때 눈에 띄지 않는다. 경로 계산은 백엔드 책임이고
  // 여기서는 받은 것을 그릴지 말지만 정한다 (12_EVACUATION §2.4).
  const routes = useDashboardStore((s) => s.evacuation_route);
  const setEvacuationRoute = useDashboardStore((s) => s.setEvacuationRoute);
  const evacuationLevel = useMemo(() => {
    let level = worstLevel;
    for (const alert of activeAlerts) {
      if (LEVEL_RANK[alert.level] > LEVEL_RANK[level]) level = alert.level;
    }
    return level;
  }, [activeAlerts, worstLevel]);

  // 경로는 경보보다 먼저 발행될 수 있고 WebSocket 재접속 중 한 번 놓칠 수도 있다.
  // 메인 화면도 진입 시 REST 스냅숏을 받아, 상세 3D 트윈과 동일한 최신 경로를 쓴다.
  useEffect(() => {
    let cancelled = false;
    void fetchRoute(PRIMARY_WEARABLE)
      .then((route) => {
        if (!cancelled && route) setEvacuationRoute(route);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [evacuationLevel, setEvacuationRoute]);

  const escapeRoute: RouteOverlay | null = useMemo(() => {
    const evacuating = LEVEL_RANK[evacuationLevel] >= LEVEL_RANK.level2_warning;
    if (!evacuating) return null;
    const route = routes[PRIMARY_WEARABLE] ?? Object.values(routes)[0];
    if (!route) return null;
    return {
      route_status: route.route_status,
      waypoints: route.waypoints,
      target_exit_id: route.target_exit_id,
    };
  }, [routes, evacuationLevel]);
  const escapeRoutes = useMemo(() => {
    if (LEVEL_RANK[evacuationLevel] < LEVEL_RANK.level2_warning) return [];
    return Object.entries(routes)
      .filter(([, route]) => route.route_status !== "unavailable")
      .map(([id, route]) => ({
        id,
        route: {
          route_status: route.route_status,
          waypoints: route.waypoints,
          target_exit_id: route.target_exit_id,
        } satisfies RouteOverlay,
      }));
  }, [routes, evacuationLevel]);

  // ③ 카드에서 고른 노드. 다시 누르면 해제되어 기본 시점으로 돌아온다.
  const [focusNodeId, setFocusNodeId] = useState<string | null>(null);
  // 마우스를 올린 동안만 트윈이 먼저 위치를 보여준다. 클릭 선택은 별도로 남아
  // 포인터가 빠졌을 때 사용자가 고른 시점으로 정확히 돌아간다.
  const [previewNodeId, setPreviewNodeId] = useState<string | null>(null);
  const automaticRiskFocus =
    LEVEL_RANK[worstLevel] >= LEVEL_RANK.level2_warning ? worstNodeId : null;
  const twinFocusNodeId = previewNodeId ?? focusNodeId ?? automaticRiskFocus;

  // 사용자가 고른 대상은 15초 동안 유지한다. 관제 화면이 한 작업자에 고정된 채
  // 다른 상황을 놓치지 않도록 조작이 없으면 전체 현황으로 돌아간다.
  useEffect(() => {
    if (!focusNodeId && !focusWearableId) return;
    const timer = window.setTimeout(() => {
      setFocusNodeId(null);
      setFocusWearableId(null);
    }, 15_000);
    return () => window.clearTimeout(timer);
  }, [focusNodeId, focusWearableId]);

  useEffect(() => {
    const update = () => setFullscreen(document.fullscreenElement === consoleRef.current);
    document.addEventListener("fullscreenchange", update);
    return () => document.removeEventListener("fullscreenchange", update);
  }, []);

  // ③ 내부(위험 상세 ↔ 센서 요약)의 분할. 규칙과 높이 표는 utils/consoleSplit 이 단일 소스이고
  // consoleSplit.test.ts 가 붙잡고 있다 (승격 조건, 중복 금지, 정렬 순서).
  const {
    risk: riskIds,
    summary: summaryIds,
    share: [riskShare, summaryShare],
  } = splitNodes(SENSOR_SLOTS, nodes, levelOf);

  // ① 입력. 센서는 이미 ship-visual 좌표이고, 작업자만 실측값을 매핑한다.
  const planSensors = SENSOR_SLOTS.filter((id) => id in SENSOR_SHIP_POSITIONS).map((id) => ({
    id,
    ...SENSOR_SHIP_POSITIONS[id],
    level: levelOf(id),
  }));
  const planSamples: SensorSample[] = distributionMetric
    ? planSensors
        .map((s) => ({ x: s.x, y: s.y, value: nodes[s.id]?.readings[planMetric]?.value ?? 0 }))
        .filter((s) => s.value > 0)
    : [];
  // 트윈 마커와 ③ 헤더 O₂ 는 아직 대표 한 명만 다룬다.
  const primaryWearable = wearables[PRIMARY_WEARABLE] ?? null;
  // TRUE SCALE(UNIFORM). FILL 은 축마다 배율이 달라(x 24배 / y 6.5배) 경로
  // 형상이 왜곡되고, 왜곡된 그림에서 "가장 가까운 출구" 를 눈으로 고르면 틀린
  // 답이 나온다 (ADR-010, 12_EVACUATION §2.4). 탈출로를 그리려면 이 프리셋이어야 한다.
  const planWorkers = WEARABLE_SLOTS.flatMap((id) => {
    const wearable = wearables[id];
    const position = displayPositionFor(
      wearable?.position_raw,
      wearable?.source_coordinate_system,
      UNIFORM_PRESET,
    );
    return position
      ? [{ id, x: position.x_m, y: position.y_m, z: position.z_m, fall_detected: wearable?.fall_detected }]
      : [];
  });

  const onlineCount = SENSOR_SLOTS.filter((id) => nodes[id]?.connection_status === "online").length;
  const simulationCount = SENSOR_SLOTS.filter(
    (id) => nodes[id]?.source_mode === "simulation",
  ).length;
  const sourceLabel: "LIVE" | "SIM" | "대기" =
    simulationCount > 0 ? "SIM" : onlineCount > 0 ? "LIVE" : "대기";
  const newestSeenAt = SENSOR_SLOTS.map((id) => nodeLastSeenAt(nodes[id] ?? null))
    .filter((value): value is string => !!value)
    .sort()
    .at(-1);
  // 자식 카드의 신선도 타이머와 별도로 분포 입력 자체를 매초 재평가한다.
  const freshnessClock = useFreshness(newestSeenAt);
  const newestSeenMs = newestSeenAt ? Date.parse(newestSeenAt) : 0;
  const freshnessNow =
    freshnessClock.secondsAgo !== null && Number.isFinite(newestSeenMs)
      ? newestSeenMs + freshnessClock.secondsAgo * 1000
      : 0;
  const freshSamples = distributionMetric
    ? planSensors
        .map((sensor) => {
          const node = nodes[sensor.id];
          const reading = node?.readings[planMetric];
          if (
            !node ||
            node.connection_status !== "online" ||
            !reading ||
            freshnessAt(nodeLastSeenAt(node), freshnessNow).isStale
          ) return null;
          return { x: sensor.x, y: sensor.y, value: reading.value };
        })
        .filter((sample): sample is SensorSample => sample !== null && sample.value > 0)
    : [];
  const staleSampleCount = Math.max(0, planSamples.length - freshSamples.length);

  return (
    <div
      ref={consoleRef}
      className={`console console--${worstLevel}${simulationCount > 0 ? " console--sim" : ""}`}
      data-risk-count={riskIds.length}
      style={
        {
          // 승격된 노드가 없으면 ③ 위험상세는 "주의 이상 노드 없음" 한 줄뿐이다.
          // 그때까지 15fr(≈57px)을 붙잡고 있으면 그 여백이 ④ 로그에서 그대로
          // 빠져나가 로그가 한 행밖에 안 보인다. 내용 높이로 접고 남는 세로를
          // ③ 요약과 ④ 에 넘긴다. n≥1 부터는 RISK_SPLIT 표를 그대로 따른다.
          "--panel2-share": riskIds.length === 0 ? "auto" : `${riskShare}fr`,
          "--panel3-share": `${summaryShare}fr`,
        } as React.CSSProperties
      }
    >
      {!thresholdsLoaded && (
        // 이슈 #165 — 등급을 못 매기는 동안 화면이 조용하면 안 된다.
        // role="alert" 로 스크린리더에도 즉시 전달한다.
        <div className="threshold-gap-banner" role="alert">
          <IconWarning size={15} />
          <span>
            <strong>임계값을 불러오지 못해 등급을 판정할 수 없습니다.</strong> 표시된 값은 정상
            여부가 확인되지 않은 상태입니다. 서버 연결을 확인하세요.
          </span>
        </div>
      )}
      {simulationCount > 0 && (
        <div className="simulation-watermark" role="status">
          SIMULATION · 실제 측정값 아님 · {simulationCount}개 노드
        </div>
      )}
      <button
        type="button"
        className="console__fullscreen"
        aria-pressed={fullscreen}
        onClick={() => {
          if (document.fullscreenElement) void document.exitFullscreen();
          else void consoleRef.current?.requestFullscreen();
        }}
      >
        {fullscreen ? "전체화면 종료" : "전체화면"}
      </button>

      <div className="console__grid">
        <div className="console__left">
          <TwinHeatmapPanel
            nodes={planSensors}
            wearable={null}
            wearables={planWorkers}
            samples={freshSamples}
            metric={planMetric}
            distributionEnabled={distributionMetric !== null}
            showMetricControls={false}
            onlineCount={freshSamples.length}
            staleCount={staleSampleCount}
            sourceLabel={sourceLabel}
            mapped={shouldMapToShip(primaryWearable?.source_coordinate_system)}
            escapeRoute={escapeRoutes.length > 0 ? null : escapeRoute}
            escapeRoutes={escapeRoutes}
            focusNodeId={twinFocusNodeId}
            focusWearableId={focusWearableId}
          />

          {/* ⑤ 는 작업자 칸이다. 센서 노드 표를 여기 같이 두면 ③ 이 이미 보여주는
              것을 한 번 더 그리면서 작업자 블록이 들어갈 세로를 전부 먹는다.
              온도·습도·가스저항은 ③ 카드의 "6종 전체" 를 펼쳐서 본다. */}
          <section className="panel-5" aria-label="작업자">
            {WEARABLE_SLOTS.map((slot) => (
              <WearableStrip
                key={slot}
                node_id={slot}
                wearable={wearables[slot] ?? null}
                worker={workerFor(slot)}
                selected={focusWearableId === slot}
                onSelect={() => {
                  setFocusNodeId(null);
                  setFocusWearableId((current) => (current === slot ? null : slot));
                }}
              />
            ))}
          </section>
        </div>

        <div className="console__right">
          {/* ② 는 현재 상태만 유지한다. 경보 팝업은 중요도가 가장 낮은 ④ 안에서만
              떠서 트윈과 센서 근거를 가리지 않는다. */}
          <section className="status-panel" aria-label="전체 상태">
            <SummaryBar
              counts={counts}
              worstNodeId={worstNodeId}
              worstLevel={worstLevel}
              projection={projection}
            />
          </section>
          <RiskDetailPanel
            nodeIds={riskIds}
            nodes={nodes}
            trends={trends}
            alerts={activeAlerts}
            levelOf={levelOf}
            workerFor={workerFor}
          />
          <SensorSummaryPanel
            nodeIds={summaryIds}
            nodes={nodes}
            trends={trends}
            wearable={primaryWearable}
            levelOf={levelOf}
            focusNodeId={focusNodeId}
            onFocusNode={(id: string) => {
              setFocusWearableId(null);
              setFocusNodeId((cur) => (cur === id ? null : id));
            }}
            onPreviewNode={setPreviewNodeId}
          />
          <div className="risk-log-slot">
            <RiskLogPanel onOpenEventLog={onOpenEventLog} />
            <AlertBanner
              alert={banner}
              workerName={banner ? (workerFor(banner.node_id)?.name ?? null) : null}
              projection={banner ? mostUrgentProjection(trends[banner.node_id]) : null}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
