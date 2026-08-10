import { useMemo } from "react";
import { TwinScene } from "../components/TwinScene";
import { useDashboardStore } from "../store/dashboardStore";
import type { AlertLevel, MetricKey } from "../types";
import type { SensorSample } from "../utils/idw";

const SENSOR_POSITIONS: Record<string, { x: number; y: number }> = {
  "sensor-01": { x: 0.5, y: 0.5 },
  "sensor-02": { x: 2.0, y: 0.5 },
  "sensor-03": { x: 0.5, y: 1.5 },
  "sensor-04": { x: 2.0, y: 1.5 },
};

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

export function TwinScreen() {
  const nodes = useDashboardStore((s) => s.sensor_nodes);
  const wearable = useDashboardStore((s) => s.wearable);
  const sceneNodes = Object.values(nodes)
    .filter((n) => n.node_id in SENSOR_POSITIONS)
    .map((n) => ({
      id: n.node_id,
      x: SENSOR_POSITIONS[n.node_id].x,
      y: SENSOR_POSITIONS[n.node_id].y,
      level: pickNodeLevel(n.readings),
    }));

  const wearableMarker = wearable?.position
    ? {
        x: wearable.position.x_m,
        y: wearable.position.y_m,
        z: wearable.position.z_m,
        fall_detected: wearable.fall_detected,
      }
    : null;

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
    <div className="screen twin-screen">
      <section className="panel twin-panel">
        <h2 className="panel-title">
          3D Digital Twin ({sceneNodes.length} sensors
          {wearableMarker ? " · wearable 추적 중" : ""}
          {heatmapData ? " · IDW 히트맵 활성" : ""})
        </h2>
        <TwinScene nodes={sceneNodes} wearable={wearableMarker} heatmap={heatmapData} />
        <p className="twin-help">
          마우스 드래그로 회전, 휠로 확대/축소. 센서 노드 색상=위험도, 청록 구체=웨어러블,
          바닥 점=CO₂ 농도 IDW 보간.
        </p>
      </section>
    </div>
  );
}
