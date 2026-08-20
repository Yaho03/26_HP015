import { useMemo } from "react";
import { TwinScene } from "../components/TwinScene";
import { useDashboardStore } from "../store/dashboardStore";
import type { AlertLevel, MetricKey } from "../types";
import type { SensorSample } from "../utils/idw";
import {
  displayPositionFor,
  SENSOR_SHIP_POSITIONS as SENSOR_POSITIONS,
  shouldMapToShip,
  UNIFORM_PRESET,
  type MappingPreset,
} from "../utils/coordinates";

const METRIC_PRIORITY: MetricKey[] = ["co2_ppm", "co_ppm", "h2s_ppm", "temperature_c"];
const HEATMAP_METRIC: MetricKey = "co2_ppm";

function pickNodeLevel(readings: Partial<Record<MetricKey, { value: number }>>): AlertLevel {
  let highest: AlertLevel = "normal";
  const numeric: Record<AlertLevel, number> = {
    normal: 0,
    level1_caution: 1,
    level2_warning: 2,
    level3_critical: 3,
  };
  for (const m of METRIC_PRIORITY) {
    const r = readings[m];
    if (!r) continue;
    let level: AlertLevel = "normal";
    if (m === "co2_ppm") {
      if (r.value >= 5000) level = "level3_critical";
      else if (r.value >= 2000) level = "level2_warning";
      else if (r.value >= 1000) level = "level1_caution";
    } else if (m === "co_ppm") {
      if (r.value >= 200) level = "level3_critical";
      else if (r.value >= 50) level = "level2_warning";
      else if (r.value >= 25) level = "level1_caution";
    } else if (m === "h2s_ppm") {
      if (r.value >= 10) level = "level3_critical";
      else if (r.value >= 5) level = "level2_warning";
      else if (r.value >= 1) level = "level1_caution";
    } else if (m === "temperature_c") {
      if (r.value >= 40) level = "level3_critical";
      else if (r.value >= 38) level = "level2_warning";
      else if (r.value >= 35) level = "level1_caution";
    }
    if (numeric[level] > numeric[highest]) highest = level;
  }
  return highest;
}

export function TwinPanel({
  preset = UNIFORM_PRESET,
  compact = false,
}: {
  preset?: MappingPreset;
  /** 모니터링 화면에 곁들이는 축소 표시. 제목·도움말을 접고 캔버스를 낮춘다. */
  compact?: boolean;
}) {
  const nodes = useDashboardStore((s) => s.sensor_nodes);
  const wearable = useDashboardStore((s) => s.wearable);
  const connectionStatus = useDashboardStore((s) => s.connection_status);
  const sceneNodes = Object.values(nodes)
    .filter((n) => n.node_id in SENSOR_POSITIONS)
    .map((n) => ({
      id: n.node_id,
      x: SENSOR_POSITIONS[n.node_id].x,
      y: SENSOR_POSITIONS[n.node_id].y,
      level: pickNodeLevel(n.readings),
    }));

  // 실측 좌표(position_raw)만 입력으로 쓴다. 이미 ship-visual 인 값에는 매핑을
  // 적용하지 않아 중복 변환이 생기지 않는다.
  const displayPosition = displayPositionFor(
    wearable?.position_raw,
    wearable?.source_coordinate_system,
    preset,
  );

  const wearableMarker = displayPosition
    ? {
        x: displayPosition.x_m,
        y: displayPosition.y_m,
        z: displayPosition.z_m,
        fall_detected: wearable?.fall_detected ?? false,
      }
    : null;

  const sourceModes = new Set(
    Object.values(nodes)
      .map((node) => node.source_mode)
      .filter((mode): mode is "live" | "simulation" => Boolean(mode)),
  );
  if (wearable?.source_mode) sourceModes.add(wearable.source_mode);
  const sourceLabel = sourceModes.size === 1
    ? sourceModes.has("simulation") ? "SIM" : "LIVE"
    : sourceModes.size > 1 ? "MIXED" : connectionStatus.websocket_connected ? "LIVE" : "대기";
  const sourceCoordinate = wearable?.source_coordinate_system ?? "demo-local";
  const isMapped = shouldMapToShip(wearable?.source_coordinate_system);

  const heatmapSamples: SensorSample[] = useMemo(() => {
    return Object.values(nodes)
      .filter((n) => n.node_id in SENSOR_POSITIONS)
      .map((n) => {
        const reading = n.readings[HEATMAP_METRIC];
        const pos = SENSOR_POSITIONS[n.node_id];
        return {
          x: pos.x,
          y: pos.y,
          value: reading ? reading.value : 0,
        };
      })
      .filter((s) => s.value > 0);
  }, [nodes]);

  const heatmapData = heatmapSamples.length > 0
    ? { samples: heatmapSamples, metric: HEATMAP_METRIC }
    : null;

  return (
      <section className={"panel twin-panel" + (compact ? " twin-panel--compact" : "")}>
        {!compact && (
          <div className="twin-heading">
            <div>
              <p className="twin-kicker">OPERATE / SHIP VISUAL MODEL</p>
              <h2 className="panel-title">
                3D Digital Twin <span className="twin-count">{sceneNodes.length} sensors</span>
              </h2>
            </div>
            <div className="twin-state-line" aria-label="트윈 데이터 상태">
              <span className="twin-state-label">DATA</span>
              <span className="twin-state-badge twin-state-badge--data">{sourceLabel}</span>
              {wearableMarker && <span className="twin-state-badge">WEARABLE TRACKING</span>}
              {heatmapData && <span className="twin-state-badge">IDW ACTIVE</span>}
            </div>
          </div>
        )}
        <div className="twin-coordinate-strip" aria-label="트윈 좌표 및 비율 매핑 상태">
          <span className="twin-coordinate-item">
            <span className="twin-coordinate-label">SOURCE</span>
            <strong>{sourceCoordinate}</strong>
          </span>
          <span className="twin-coordinate-arrow" aria-hidden="true">→</span>
          <span className="twin-coordinate-item twin-coordinate-item--target">
            <span className="twin-coordinate-label">DISPLAY</span>
            <strong>ship-visual</strong>
          </span>
          <span className="twin-mapping-badge">
            {isMapped ? preset.label : "1:1 MODEL"}
          </span>
        </div>
        <TwinScene nodes={sceneNodes} wearable={wearableMarker} heatmap={heatmapData} />
        {!compact && (
          <p className="twin-help">
            마우스 드래그로 회전, 휠로 확대/축소. 센서 노드 색상=위험도, 청록 구체=웨어러블,
            바닥 점=CO₂ 농도 IDW 보간. 표시 좌표는 실측값을 비율 매핑한 추정 위치다.
          </p>
        )}
      </section>
  );
}

export function TwinScreen() {
  return (
    <div className="screen twin-screen">
      {/* 상세 화면은 형상비를 보존한다. 정사각 보행이 정사각으로 보여야 한다. */}
      <TwinPanel preset={UNIFORM_PRESET} />
    </div>
  );
}
