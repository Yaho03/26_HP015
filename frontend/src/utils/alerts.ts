import type { AlertLevel, MetricKey, SensorNodeState } from "../types";

// PRD FR-204 MUST: 임계값은 코드에 하드코딩하지 않는다 (이슈 #114).
// 정본은 backend/migrations/005_thresholds.sql 이고, 프론트는 부팅 시
// GET /api/thresholds 로 받아 이 테이블을 채운다. 여기에 숫자를 다시 적으면
// 서버에서 임계값을 바꿔도 화면이 따라가지 않는다.

/** GET /api/thresholds 응답 중 판정에 필요한 필드만. */
export interface ServerThreshold {
  metric: string;
  level: string;
  direction: "above" | "below";
  enter_threshold: number;
}

interface Entry {
  level: AlertLevel;
  direction: "above" | "below";
  enter: number;
}

/** metric → 위험한 순서(심각→경미)로 정렬된 구간. */
let TABLE: Record<string, Entry[]> = {};

const SEVERITY: Record<string, number> = {
  level3_critical: 3,
  level2_warning: 2,
  level1_caution: 1,
};

/** 서버 임계값을 적재한다. 스토어가 부팅 시·저장 후 호출한다. */
export function setThresholdTable(rows: ServerThreshold[]): void {
  const next: Record<string, Entry[]> = {};
  for (const r of rows) {
    if (!(r.level in SEVERITY)) continue;
    (next[r.metric] ??= []).push({
      level: r.level as AlertLevel,
      direction: r.direction,
      enter: r.enter_threshold,
    });
  }
  for (const entries of Object.values(next)) {
    entries.sort((a, b) => SEVERITY[b.level] - SEVERITY[a.level]);
  }
  TABLE = next;
}

/** 아직 서버 임계값을 못 받았으면 false. 이 상태에서는 판정하지 않는다. */
export function isThresholdTableLoaded(): boolean {
  return Object.keys(TABLE).length > 0;
}

function classifyBy(key: string, value: number): AlertLevel {
  for (const { level, direction, enter } of TABLE[key] ?? []) {
    if (direction === "below" ? value < enter : value >= enter) return level;
  }
  return "normal";
}

export interface ThresholdLine {
  value: number;
  level: AlertLevel;
}

export function thresholdLinesFor(metric: MetricKey): ThresholdLine[] {
  return (TABLE[metric] ?? []).map(({ enter, level }) => ({ value: enter, level }));
}

export function classifyMetric(metric: MetricKey, value: number): AlertLevel {
  return classifyBy(metric, value);
}

// O₂ 는 서버에서 o2_low/o2_high 두 방향으로 나뉘어 있다 (06_ALERT_RULES).
export function classifyO2Low(value: number): AlertLevel {
  return classifyBy("o2_low", value);
}

export function classifyO2High(value: number): AlertLevel {
  return classifyBy("o2_high", value);
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

export const LEVEL_RANK: Record<AlertLevel, number> = {
  normal: 0,
  level1_caution: 1,
  level2_warning: 2,
  level3_critical: 3,
};

/** Higher of two levels. */
export function maxLevel(a: AlertLevel, b: AlertLevel): AlertLevel {
  return LEVEL_RANK[a] >= LEVEL_RANK[b] ? a : b;
}

/**
 * Overall alert level for a sensor node. Uses the backend-provided
 * `alert_level` when present (10_UI_FLOW §3.2), otherwise derives it from the
 * current readings so the card is meaningful before that field is wired.
 */
export function nodeAlertLevel(node: SensorNodeState): AlertLevel {
  if (node.alert_level) return node.alert_level;
  let level: AlertLevel = "normal";
  for (const key of Object.keys(node.readings) as MetricKey[]) {
    const reading = node.readings[key];
    if (!reading) continue;
    const m =
      key === "o2_pct"
        ? maxLevel(classifyO2Low(reading.value), classifyO2High(reading.value))
        : classifyMetric(key, reading.value);
    level = maxLevel(level, m);
  }
  return level;
}
