import type { AlertLevel, MetricKey } from "../types";

export interface SensorSample {
  x: number;
  y: number;
  value: number;
}

export interface GridPoint {
  x: number;
  y: number;
  value: number;
  level: AlertLevel;
}

const POWER = 2;
const EPSILON = 1e-6;

export function idw(samples: SensorSample[], x: number, y: number): number {
  if (samples.length === 0) return 0;
  let num = 0;
  let den = 0;
  for (const s of samples) {
    const dx = s.x - x;
    const dy = s.y - y;
    const d2 = dx * dx + dy * dy;
    if (d2 < EPSILON) return s.value;
    const w = 1 / Math.pow(d2, POWER / 2);
    num += w * s.value;
    den += w;
  }
  return den > 0 ? num / den : 0;
}

export function buildGrid(
  samples: SensorSample[],
  bounds: { minX: number; maxX: number; minY: number; maxY: number },
  resolution: number,
): GridPoint[] {
  const { minX, maxX, minY, maxY } = bounds;
  const stepX = (maxX - minX) / resolution;
  const stepY = (maxY - minY) / resolution;
  const grid: GridPoint[] = [];
  for (let i = 0; i <= resolution; i++) {
    for (let j = 0; j <= resolution; j++) {
      const x = minX + stepX * i;
      const y = minY + stepY * j;
      grid.push({ x, y, value: idw(samples, x, y), level: "normal" });
    }
  }
  return grid;
}

const LEVEL_THRESHOLDS: { metric: MetricKey; min: number; level: AlertLevel }[] = [
  { metric: "co2_ppm", min: 5000, level: "level3_critical" },
  { metric: "co2_ppm", min: 2000, level: "level2_warning" },
  { metric: "co2_ppm", min: 1000, level: "level1_caution" },
];

export function classifyValue(metric: MetricKey, value: number): AlertLevel {
  for (const { metric: m, min, level } of LEVEL_THRESHOLDS) {
    if (m === metric && value >= min) return level;
  }
  if (metric === "co2_ppm") {
    if (value >= 5000) return "level3_critical";
    if (value >= 2000) return "level2_warning";
    if (value >= 1000) return "level1_caution";
  }
  if (metric === "co_ppm") {
    if (value >= 200) return "level3_critical";
    if (value >= 50) return "level2_warning";
    if (value >= 25) return "level1_caution";
  }
  if (metric === "h2s_ppm") {
    if (value >= 10) return "level3_critical";
    if (value >= 5) return "level2_warning";
    if (value >= 1) return "level1_caution";
  }
  return "normal";
}

export const LEVEL_RGB: Record<AlertLevel, [number, number, number]> = {
  normal: [0.06, 0.45, 0.27],
  level1_caution: [0.98, 0.80, 0.08],
  level2_warning: [0.98, 0.57, 0.24],
  level3_critical: [0.94, 0.27, 0.27],
};
