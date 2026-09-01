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

import { isThresholdTableLoaded, thresholdLinesFor } from "./alerts";
import type { MetricKey } from "../types";

export const LEVEL_RGB: Record<AlertLevel, [number, number, number]> = {
  // 판정 불가는 무채색이다. 히트맵에서 초록으로 칠하면 안전해 보인다.
  unknown: [0.42, 0.45, 0.5],
  normal: [0.06, 0.45, 0.27],
  level1_caution: [0.98, 0.8, 0.08],
  level2_warning: [0.98, 0.57, 0.24],
  level3_critical: [0.94, 0.27, 0.27],
};

/**
 * 농도 → 연속 색.
 *
 * 등급 색 네 가지로만 칠하면 600ppm 과 990ppm 이 똑같은 초록이 된다. 분포도의
 * 일이 "어디가 더 짙은가" 를 보여주는 것인데, 이산 색은 그걸 임계값을 넘는
 * 순간까지 숨긴다. 그래서 구간 안에서는 연속으로 섞는다.
 *
 * **색 고정점은 서버 임계값이다.** 임계값에 정확히 닿으면 그 등급의 색이 그대로
 * 나오므로, 연속으로 바꿔도 등급 경계는 화면에서 사라지지 않는다. 임계값을 여기
 * 적지 않고 alerts.ts 의 서버 테이블에서 받는 이유는 FR-204 다 — 여기에 숫자를
 * 복사하면 서버에서 임계값을 바꿔도 히트맵만 옛 기준으로 칠해진다.
 *
 * 등급 판정 자체는 여전히 classifyValue 가 한다. 이 함수는 표시 전용이고,
 * 여기서 나온 색으로 경보를 판정하지 않는다.
 */
export function gasRamp(metric: MetricKey, value: number): [number, number, number] {
  // 임계값을 못 받았으면 판정 근거가 없다 (이슈 #165). 무채색으로 두어야
  // 초록으로 칠해진 "안전해 보이는" 격자가 생기지 않는다.
  if (!isThresholdTableLoaded()) return LEVEL_RGB.unknown;

  // thresholdLinesFor 는 심각 → 경미 순이다. 오름차순으로 뒤집어 사다리를 만든다.
  const ladder = [...thresholdLinesFor(metric)].reverse();
  if (ladder.length === 0) return LEVEL_RGB.normal;

  // 고정점: 0(정상) → 각 등급 진입 임계값(그 등급 색).
  const stops: { at: number; rgb: [number, number, number] }[] = [
    { at: 0, rgb: LEVEL_RGB.normal },
    ...ladder.map((line) => ({ at: line.value, rgb: LEVEL_RGB[line.level] })),
  ];

  const last = stops[stops.length - 1];
  // 최고 등급을 넘어선 값은 더 짙어지지 않는다. 여기서 색을 더 밀면 최고 등급
  // 안에서 "덜 위험한 빨강" 이 생긴다.
  if (value >= last.at) return last.rgb;

  // 정상 범위는 농도가 높아져도 주의색(노랑)을 미리 섞지 않는다. 같은 정상
  // 등급 안에서는 초록의 밝기만 올려 공간적인 농도 차이를 표현한다.
  const firstThreshold = stops[1];
  if (firstThreshold && value < firstThreshold.at) {
    const raw = Math.max(0, Math.min(1, value / firstThreshold.at));
    const brightness = 1 + raw * 0.45;
    return LEVEL_RGB.normal.map((channel) => Math.min(1, channel * brightness)) as [
      number,
      number,
      number,
    ];
  }

  for (let i = 1; i < stops.length; i++) {
    const lo = stops[i - 1];
    const hi = stops[i];
    if (value >= hi.at) continue;
    const span = hi.at - lo.at;
    const raw = span > 0 ? Math.max(0, Math.min(1, (value - lo.at) / span)) : 0;
    // 선형으로 섞으면 구간 한가운데(예: 정상 구간의 571ppm)가 벌써 다음 등급
    // 색에 절반쯤 물들어, 정상인 격자가 주의처럼 읽힌다. 제곱으로 눌러 두면
    // 구간 앞부분은 제 등급 색을 지키고 임계값에 가까워질 때만 빠르게 넘어간다.
    // 고정점(t=0, t=1)은 그대로라 등급 경계는 여전히 정확하다.
    const t = raw * raw;
    return [
      lo.rgb[0] + (hi.rgb[0] - lo.rgb[0]) * t,
      lo.rgb[1] + (hi.rgb[1] - lo.rgb[1]) * t,
      lo.rgb[2] + (hi.rgb[2] - lo.rgb[2]) * t,
    ];
  }
  return stops[0].rgb;
}
