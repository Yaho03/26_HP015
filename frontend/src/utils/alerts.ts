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
  // 테이블 자체가 없으면 판정할 근거가 없다 (이슈 #165). 여기서 normal 을
  // 돌려주면 임계값을 못 받은 동안 모든 값이 정상으로 보인다.
  // 테이블은 있는데 그 지표에 규칙만 없는 경우는 normal 이 맞다 — 판정한 결과
  // 걸릴 구간이 없는 것이므로 모르는 상태가 아니다.
  if (!isThresholdTableLoaded()) return "unknown";
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

/**
 * 다음 등급 진입까지 얼마나 왔는가 — ② / ⑤ 의 "임계값 대비 근접도 바".
 *
 * 임계값은 서버에서 받은 것만 쓴다 (FR-201). 테이블이 없으면 null 을 돌려주고,
 * 호출부는 바를 채우지 않는다. 여기서 임의의 만점 눈금을 만들어 채우면
 * 임계값을 못 받은 동안에도 바가 "여유 있음"으로 보인다 (이슈 #165).
 */
export interface ThresholdApproach {
  /** 다음에 진입할 등급. 이미 최고 등급 구간이면 그 등급. */
  level: AlertLevel;
  /** 그 등급의 진입 임계값. */
  enter: number;
  direction: "above" | "below";
  /** 0~1. 1 이면 임계값에 닿았거나 넘었다. */
  ratio: number;
}

export function thresholdApproach(metric: string, value: number): ThresholdApproach | null {
  const entries = TABLE[metric];
  if (!entries || entries.length === 0) return null;

  // entries 는 심각 → 경미 순이다. 아직 넘지 않은 것 중 가장 가까운 것이 다음 관문.
  const pending = entries.filter(({ direction, enter }) =>
    direction === "below" ? value >= enter : value < enter,
  );

  if (pending.length === 0) {
    // 전부 넘었다 — 최고 등급 구간이다. 바는 가득 찬다.
    const worst = entries[0];
    return { level: worst.level, enter: worst.enter, direction: worst.direction, ratio: 1 };
  }

  const next = pending[pending.length - 1];
  // above: 값이 커질수록 위험하므로 value / enter.
  // below: 값이 작아질수록 위험하므로 enter / value (O₂ 저농도).
  // 둘 다 임계값에 닿으면 1 이 된다.
  const raw =
    next.direction === "below"
      ? value > 0
        ? next.enter / value
        : 1
      : next.enter > 0
        ? value / next.enter
        : 0;

  return {
    level: next.level,
    enter: next.enter,
    direction: next.direction,
    ratio: Math.max(0, Math.min(1, raw)),
  };
}

// O₂ 는 서버에서 o2_low/o2_high 두 방향으로 나뉘어 있다 (06_ALERT_RULES).
export function classifyO2Low(value: number): AlertLevel {
  return classifyBy("o2_low", value);
}

export function classifyO2High(value: number): AlertLevel {
  return classifyBy("o2_high", value);
}

const LEVEL_LABEL: Record<AlertLevel, string> = {
  unknown: "판정 불가",
  normal: "정상",
  level1_caution: "L1 주의",
  level2_warning: "L2 경고",
  level3_critical: "L3 위험",
};

export function levelLabel(level: AlertLevel): string {
  return LEVEL_LABEL[level];
}

// unknown 은 normal 위, 실제 경보 아래다. 한 지표라도 판정 못 하면 노드를
// 정상이라 말할 수 없지만, 모르는 지표 하나가 확인된 위험을 가려서도 안 된다.
export const LEVEL_RANK: Record<AlertLevel, number> = {
  normal: 0,
  unknown: 1,
  level1_caution: 2,
  level2_warning: 3,
  level3_critical: 4,
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
  // 서버 판정이 없고 임계값도 없으면 근거가 전혀 없다 (이슈 #165).
  // 측정값이 하나도 없는 노드까지 정상으로 떨어지지 않게 여기서 먼저 막는다.
  if (!isThresholdTableLoaded()) return "unknown";
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
