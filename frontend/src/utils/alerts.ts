import type { AlertLevel, MetricKey } from "../types";

const CO2_LEVELS: { min: number; level: AlertLevel }[] = [
  { min: 5000, level: "level3_critical" },
  { min: 2000, level: "level2_warning" },
  { min: 1000, level: "level1_caution" },
];

const CO_LEVELS: { min: number; level: AlertLevel }[] = [
  { min: 200, level: "level3_critical" },
  { min: 50, level: "level2_warning" },
  { min: 25, level: "level1_caution" },
];

const H2S_LEVELS: { min: number; level: AlertLevel }[] = [
  { min: 10, level: "level3_critical" },
  { min: 5, level: "level2_warning" },
  { min: 1, level: "level1_caution" },
];

const TEMP_LEVELS: { min: number; level: AlertLevel }[] = [
  { min: 40, level: "level3_critical" },
  { min: 38, level: "level2_warning" },
  { min: 35, level: "level1_caution" },
];

const THRESHOLDS: Partial<Record<MetricKey, { min: number; level: AlertLevel }[]>> = {
  co2_ppm: CO2_LEVELS,
  co_ppm: CO_LEVELS,
  h2s_ppm: H2S_LEVELS,
  temperature_c: TEMP_LEVELS,
};

export interface ThresholdLine {
  value: number;
  level: AlertLevel;
}

export function thresholdLinesFor(metric: MetricKey): ThresholdLine[] {
  const levels = THRESHOLDS[metric];
  if (!levels) return [];
  return levels.map(({ min, level }) => ({ value: min, level }));
}

export function classifyMetric(metric: MetricKey, value: number): AlertLevel {
  const levels = THRESHOLDS[metric];
  if (!levels) return "normal";
  for (const { min, level } of levels) {
    if (value >= min) return level;
  }
  return "normal";
}

export function classifyO2Low(value: number): AlertLevel {
  if (value < 16.0) return "level3_critical";
  if (value < 18.0) return "level2_warning";
  if (value < 19.5) return "level1_caution";
  return "normal";
}

export function classifyO2High(value: number): AlertLevel {
  if (value > 28.0) return "level3_critical";
  if (value > 25.0) return "level2_warning";
  if (value > 23.5) return "level1_caution";
  return "normal";
}

const LEVEL_LABEL: Record<AlertLevel, string> = {
  normal: "정상",
  level1_caution: "L1 주의",
  level2_warning: "L2 경고",
  level3_critical: "L3 위험",
};

export function levelLabel(level: AlertLevel): string {
  return LEVEL_LABEL[level];
}
