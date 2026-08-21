import { useMemo } from "react";
import { useDashboardStore } from "../store/dashboardStore";
import { NodeMetricsGrid } from "../components/NodeMetricsGrid";
import { RiskDetailPanel } from "../components/RiskDetailPanel";
import { RiskLogPanel } from "../components/RiskLogPanel";
import { SensorSummaryPanel } from "../components/SensorSummaryPanel";
import { TwinHeatmapPanel } from "../components/TwinHeatmapPanel";
import { WearableStrip } from "../components/WearableStrip";
import { IconWarning } from "../components/icons";
import { nodeAlertLevel } from "../utils/alerts";
import { splitNodes } from "../utils/consoleSplit";
import { useAssignments } from "../hooks/useAssignments";
import {
  displayPositionFor,
  FILL_PRESET,
  SENSOR_SCREEN_ORDER,
  SENSOR_SHIP_POSITIONS,
  shouldMapToShip,
} from "../utils/coordinates";
import type { SensorSample } from "../utils/idw";
import type { AlertLevel, MetricKey } from "../types";

// Spec 10_UI_FLOW §3.1: fixed sensor-01~04 + wearable-01 slots. Slots render in
// a "대기" state until their node reports (live wiring tracked by #106/#121).
const SENSOR_SLOTS = [...SENSOR_SCREEN_ORDER];
const WEARABLE_SLOT = "wearable-01";
const PLAN_METRIC: MetricKey = "co2_ppm";

export function MonitoringScreen({
  onOpenEventLog,
}: {
  onOpenEventLog?: (filter: { nodeId?: string; level?: string }) => void;
}) {
  const nodes = useDashboardStore((s) => s.sensor_nodes);
  const trends = useDashboardStore((s) => s.sensor_trend);
  const wearable = useDashboardStore((s) => s.wearable);
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
  const levels = useMemo(() => {
    const out: Record<string, AlertLevel> = {};
    for (const id of SENSOR_SLOTS) {
      out[id] = nodes[id] ? nodeAlertLevel(nodes[id]) : "unknown";
    }
    return out;
  }, [nodes]);
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

  // ② 와 ③ 의 분할. 규칙과 높이 표는 utils/consoleSplit 이 단일 소스이고
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
  const planWorkerPos = displayPositionFor(
    wearable?.position_raw,
    wearable?.source_coordinate_system,
    FILL_PRESET,
  );
  const planWorker = planWorkerPos
    ? {
        x: planWorkerPos.x_m,
        y: planWorkerPos.y_m,
        z: planWorkerPos.z_m,
        fall_detected: wearable?.fall_detected,
      }
    : null;

  const onlineCount = SENSOR_SLOTS.filter((id) => nodes[id]?.connection_status === "online").length;
  const simulationCount = SENSOR_SLOTS.filter((id) => nodes[id]?.source_mode === "simulation").length;
  const sourceLabel: "LIVE" | "SIM" | "대기" =
    simulationCount > 0 ? "SIM" : onlineCount > 0 ? "LIVE" : "대기";

  return (
    <div
      className="console"
      style={
        {
          "--panel2-share": `${riskShare}fr`,
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
            <strong>임계값을 불러오지 못해 등급을 판정할 수 없습니다.</strong>{" "}
            표시된 값은 정상 여부가 확인되지 않은 상태입니다. 서버 연결을 확인하세요.
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
            mapped={shouldMapToShip(wearable?.source_coordinate_system)}
          />

          <section className="panel-5" aria-label="노드별 센서 데이터">
            <NodeMetricsGrid />
            <WearableStrip
              node_id={WEARABLE_SLOT}
              wearable={wearable}
              worker={workerFor(WEARABLE_SLOT)}
            />
          </section>
        </div>

        <div className="console__right">
          <RiskDetailPanel
            nodeIds={riskIds}
            nodes={nodes}
            trends={trends}
            counts={counts}
            alerts={activeAlerts}
            levelOf={levelOf}
            workerFor={workerFor}
          />
          <SensorSummaryPanel
            nodeIds={summaryIds}
            nodes={nodes}
            trends={trends}
            wearable={wearable}
            levelOf={levelOf}
          />
          <RiskLogPanel onOpenEventLog={onOpenEventLog} />
        </div>
      </div>
    </div>
  );
}
