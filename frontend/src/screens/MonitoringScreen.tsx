import { useMemo } from "react";
import { useDashboardStore } from "../store/dashboardStore";
import { NodeMetricsGrid } from "../components/NodeMetricsGrid";
import { RiskDetailPanel } from "../components/RiskDetailPanel";
import { RiskLogPanel } from "../components/RiskLogPanel";
import { SensorSummaryPanel } from "../components/SensorSummaryPanel";
import { AlertBanner } from "../components/AlertBanner";
import { SummaryBar } from "../components/SummaryBar";
import { TwinHeatmapPanel } from "../components/TwinHeatmapPanel";
import { WearableStrip } from "../components/WearableStrip";
import { IconWarning } from "../components/icons";
import { LEVEL_RANK, nodeAlertLevel } from "../utils/alerts";
import { splitNodes } from "../utils/consoleSplit";
import { mostUrgentProjection, type Projection } from "../utils/projection";
import { useStableLevels } from "../hooks/useStableLevels";
import { useAssignments } from "../hooks/useAssignments";
import {
  displayPositionFor,
  FILL_PRESET,
  PRIMARY_WEARABLE,
  SENSOR_SCREEN_ORDER,
  SENSOR_SHIP_POSITIONS,
  shouldMapToShip,
  WEARABLE_SCREEN_ORDER,
} from "../utils/coordinates";
import type { SensorSample } from "../utils/idw";
import type { AlertLevel, MetricKey } from "../types";

// Spec 10_UI_FLOW §3.1: fixed sensor-01~04 + wearable-01 slots. Slots render in
// a "대기" state until their node reports (live wiring tracked by #106/#121).
const SENSOR_SLOTS = [...SENSOR_SCREEN_ORDER];
// ⑤ 는 슬롯을 고정해 자리를 비워 둔다. 보고하지 않는 작업자가 목록에서 조용히
// 사라지면 "두 명이 들어갔는데 한 명만 보인다" 를 알아챌 방법이 없다.
const WEARABLE_SLOTS = [...WEARABLE_SCREEN_ORDER];
const PLAN_METRIC: MetricKey = "co2_ppm";

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
  const planSamples: SensorSample[] = planSensors
    .map((s) => ({ x: s.x, y: s.y, value: nodes[s.id]?.readings[PLAN_METRIC]?.value ?? 0 }))
    .filter((s) => s.value > 0);
  // 트윈 마커와 ③ 헤더 O₂ 는 아직 대표 한 명만 다룬다 (① 트윈 작업에서 확장).
  const primaryWearable = wearables[PRIMARY_WEARABLE] ?? null;
  const planWorkerPos = displayPositionFor(
    primaryWearable?.position_raw,
    primaryWearable?.source_coordinate_system,
    FILL_PRESET,
  );
  const planWorker = planWorkerPos
    ? {
        x: planWorkerPos.x_m,
        y: planWorkerPos.y_m,
        z: planWorkerPos.z_m,
        fall_detected: primaryWearable?.fall_detected,
      }
    : null;

  const onlineCount = SENSOR_SLOTS.filter((id) => nodes[id]?.connection_status === "online").length;
  const simulationCount = SENSOR_SLOTS.filter(
    (id) => nodes[id]?.source_mode === "simulation",
  ).length;
  const sourceLabel: "LIVE" | "SIM" | "대기" =
    simulationCount > 0 ? "SIM" : onlineCount > 0 ? "LIVE" : "대기";

  return (
    <div
      className="console"
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

      <div className="console__grid">
        <div className="console__left">
          <TwinHeatmapPanel
            nodes={planSensors}
            wearable={planWorker}
            samples={planSamples}
            metric={PLAN_METRIC}
            onlineCount={onlineCount}
            sourceLabel={sourceLabel}
            mapped={shouldMapToShip(primaryWearable?.source_coordinate_system)}
          />

          <section className="panel-5" aria-label="노드별 센서 데이터">
            <NodeMetricsGrid />
            {WEARABLE_SLOTS.map((slot) => (
              <WearableStrip
                key={slot}
                node_id={slot}
                wearable={wearables[slot] ?? null}
                worker={workerFor(slot)}
              />
            ))}
          </section>
        </div>

        <div className="console__right">
          {/* ② 경보가 위, 카운트가 아래. 경보를 읽는 동안 그 근거인 센서 카드가
              가려지면 안 되므로 ③ 을 덮지 않고 이 칸 안에서만 자란다. */}
          <section className="status-panel" aria-label="전체 상태">
            <AlertBanner
              alert={banner}
              workerName={banner ? (workerFor(banner.node_id)?.name ?? null) : null}
              projection={
                banner ? mostUrgentProjection(trends[banner.node_id]) : null
              }
            />
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
          />
          <RiskLogPanel onOpenEventLog={onOpenEventLog} />
        </div>
      </div>
    </div>
  );
}
