import { useState } from "react";
import { useDashboardStore } from "../store/dashboardStore";
import { SummaryBar } from "../components/SummaryBar";
import { SensorCard } from "../components/SensorCard";
import { WearableCard } from "../components/WearableCard";
import { SpacePlan } from "../components/SpacePlan";
import { IconClock, IconWarning, IconXCircle } from "../components/icons";
import { nodeAlertLevel } from "../utils/alerts";
import {
  displayPositionFor,
  FILL_PRESET,
  SENSOR_SHIP_POSITIONS,
} from "../utils/coordinates";
import type { SensorSample } from "../utils/idw";
import type { AlertLevel, MetricKey } from "../types";

// Spec 10_UI_FLOW §3.1: fixed sensor-01~04 + wearable-01 slots. Slots render in
// a "대기" state until their node reports (live wiring tracked by #106/#121).
const SENSOR_SLOTS = ["sensor-01", "sensor-02", "sensor-03", "sensor-04"];
const WEARABLE_SLOT = "wearable-01";
const PLAN_METRIC: MetricKey = "co2_ppm";

export function MonitoringScreen() {
  const [demoLoading, setDemoLoading] = useState(false);
  const [riskSimulation, setRiskSimulation] = useState(false);
  const nodes = useDashboardStore((s) => s.sensor_nodes);
  const co2Trend = useDashboardStore((s) => s.co2_trend);
  const wearable = useDashboardStore((s) => s.wearable);
  const activeAlerts = useDashboardStore((s) =>
    Object.values(s.active_alerts).filter((alert) => alert.status === "active").length,
  );
  const websocketConnected = useDashboardStore((s) => s.connection_status.websocket_connected);
  const thresholdsLoaded = useDashboardStore((s) => s.thresholds.length > 0);

  const counts: Record<AlertLevel, number> = {
    unknown: 0,
    normal: 0,
    level1_caution: 0,
    level2_warning: 0,
    level3_critical: 0,
  };
  for (const id of SENSOR_SLOTS) {
    const node = nodes[id];
    if (node && node.connection_status === "online") counts[nodeAlertLevel(node)] += 1;
  }

  // 평면도 입력. 센서는 이미 ship-visual 좌표이고, 작업자만 실측값을 매핑한다.
  const planSensors = SENSOR_SLOTS.filter((id) => id in SENSOR_SHIP_POSITIONS).map((id) => ({
    id,
    ...SENSOR_SHIP_POSITIONS[id],
    // 노드 정보가 아직 없으면 판정 불가다 (이슈 #165). normal 로 떨어뜨리면
    // 평면도에서 데이터 없는 자리가 안전한 자리로 보인다.
    level: nodes[id] ? nodeAlertLevel(nodes[id]) : ("unknown" as AlertLevel),
  }));
  const planSamples: SensorSample[] = planSensors
    .map((s) => ({ x: s.x, y: s.y, value: nodes[s.id]?.readings[PLAN_METRIC]?.value ?? 0 }))
    .filter((s) => s.value > 0);
  const planWorker = displayPositionFor(
    wearable?.position_raw,
    wearable?.source_coordinate_system,
    FILL_PRESET,
  );

  const onlineCount = SENSOR_SLOTS.filter((id) => nodes[id]?.connection_status === "online").length;
  const simulationCount = SENSOR_SLOTS.filter((id) => nodes[id]?.source_mode === "simulation").length;
  const offlineCount = SENSOR_SLOTS.length - onlineCount;
  const sourceLabel = simulationCount > 0 ? "SIM" : onlineCount > 0 ? "LIVE" : "대기";

  return (
    <div className="monitor">
      <div className="monitor-heading">
        <div>
          <p className="monitor-kicker">OPERATE / SENSOR NETWORK</p>
          <h2 className="monitor-title">밀폐공간 실시간 상태</h2>
        </div>
        <div className="monitor-meta" aria-label="모니터링 요약">
          <span className="monitor-meta-item">
            <span className="monitor-meta-label">NODES</span>
            <strong>{onlineCount}/{SENSOR_SLOTS.length}</strong>
          </span>
          <span className="monitor-meta-item">
            <span className="monitor-meta-label">SOURCE</span>
            <strong className={sourceLabel === "SIM" ? "is-sim-text" : ""}>{sourceLabel}</strong>
          </span>
          <span className="monitor-meta-item">
            <span className="monitor-meta-label">ALERTS</span>
            <strong className={activeAlerts > 0 ? "is-alert-text" : ""}>{activeAlerts}</strong>
          </span>
          <span className={"monitor-stream" + (websocketConnected ? " monitor-stream--connected" : "")}>
            <span className="monitor-stream-dot" aria-hidden="true" />
            {websocketConnected ? "STREAM CONNECTED" : "STREAM DISCONNECTED"}
          </span>
        </div>
      </div>
      <div className="monitor-actions" aria-label="화면 상태 테스트">
        <span className="monitor-actions__label">INTERACTION TEST</span>
        <button
          type="button"
          className={"monitor-action" + (demoLoading ? " monitor-action--active" : "")}
          onClick={() => setDemoLoading((loading) => !loading)}
          aria-pressed={demoLoading}
        >
          <IconClock size={14} />
          {demoLoading ? "로딩 상태 끄기" : "로딩 상태 켜기"}
        </button>
        <button
          type="button"
          className={"monitor-action monitor-action--danger" + (riskSimulation ? " monitor-action--active" : "")}
          onClick={() => setRiskSimulation((active) => !active)}
          aria-pressed={riskSimulation}
        >
          <IconWarning size={14} />
          {riskSimulation ? "테스트 경보 해제" : "위험 상황 발생"}
        </button>
      </div>

      {demoLoading ? (
        <MonitoringSkeleton />
      ) : (
        <>
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

          <SummaryBar counts={counts} />

          <section>
            <div className="section-head">
              <span>센서 상세</span>
              {offlineCount > 0 && <span className="section-note">{offlineCount} pending / offline</span>}
            </div>
            <div className="sensor-grid">
              {SENSOR_SLOTS.map((id) => (
                <SensorCard key={id} node_id={id} node={nodes[id] ?? null} trend={co2Trend[id]} />
              ))}
            </div>
          </section>

          {/* 평면도와 웨어러블을 가로로 나눈다. 세로로 쌓으면 1440x900 에서 스크롤이 생긴다. */}
          <div className="monitor-bottom">
            <section className="monitor-bottom__twin">
              <h2 className="section-head">공간 개요 · CO₂ 분포</h2>
              {/* 원거리 글랜스 가독성을 위해 원근 없는 바닥 평면도를 쓴다.
                  3D 트윈은 상세 화면(Screen 2) 소관이다. */}
              <SpacePlan
                sensors={planSensors}
                samples={planSamples}
                metric={PLAN_METRIC}
                worker={planWorker}
                preset={FILL_PRESET}
              />
            </section>
            <section className="monitor-bottom__wearable">
              <h2 className="section-head">웨어러블</h2>
              <WearableCard node_id={WEARABLE_SLOT} wearable={wearable} />
            </section>
          </div>
        </>
      )}

      {riskSimulation && (
        <aside className="safety-demo-alert" role="alert" aria-live="assertive">
          <div className="safety-demo-alert__icon" aria-hidden="true"><IconXCircle size={22} /></div>
          <div>
            <p className="safety-demo-alert__eyebrow">SIMULATED INCIDENT / L3</p>
            <h2>위험 상황이 감지되었습니다</h2>
            <p>테스트 경보입니다. 해제할 때까지 우측 상단에 유지됩니다.</p>
          </div>
        </aside>
      )}
    </div>
  );
}

function MonitoringSkeleton() {
  return (
    <div className="monitor-skeleton" aria-live="polite" aria-label="모니터링 데이터 로딩 중">
      <div className="monitor-skeleton__summary">
        {Array.from({ length: 4 }, (_, index) => (
          <div className="skeleton-block" key={index} />
        ))}
      </div>
      <div className="section-head">
        <span className="skeleton-line skeleton-line--label" />
        <span className="skeleton-line skeleton-line--short" />
      </div>
      <div className="monitor-skeleton__sensors">
        {Array.from({ length: 4 }, (_, index) => (
          <div className="monitor-skeleton__sensor" key={index}>
            <span className="skeleton-line skeleton-line--head" />
            <span className="skeleton-circle" />
            <span className="skeleton-line" />
            <span className="skeleton-line skeleton-line--short" />
            <span className="skeleton-line skeleton-line--tiny" />
          </div>
        ))}
      </div>
      <div className="monitor-skeleton__bottom">
        <div className="skeleton-block skeleton-block--wide" />
        <div className="skeleton-block" />
      </div>
      <p className="monitor-skeleton__caption">실시간 센서 스트림을 불러오는 중입니다</p>
    </div>
  );
}
