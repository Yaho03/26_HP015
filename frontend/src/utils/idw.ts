import type { AlertLevel } from "../types";

export interface SensorSample {
  x: number;
  y: number;
  value: number;
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

// 임계값은 alerts.ts 한 곳에서만 관리한다 (PRD FR-204, 이슈 #114).
// 예전에는 여기에도 같은 숫자가 복사돼 있어서, 히트맵 색과 카드 색이 서로
// 다른 기준으로 칠해질 수 있었다.
export { classifyMetric as classifyValue } from "./alerts";

export const LEVEL_RGB: Record<AlertLevel, [number, number, number]> = {
  // 판정 불가는 무채색이다. 히트맵에서 초록으로 칠하면 안전해 보인다.
  unknown: [0.42, 0.45, 0.50],
  normal: [0.06, 0.45, 0.27],
  level1_caution: [0.98, 0.80, 0.08],
  level2_warning: [0.98, 0.57, 0.24],
  level3_critical: [0.94, 0.27, 0.27],
};
