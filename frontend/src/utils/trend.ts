// 추세 기반 선제 표시 (06_ALERT_RULES §8.2, SHOULD).
//
// 최근 측정값의 선형 회귀 기울기를 외삽해 "이 추세가 유지되면 약 n분 뒤 다음 등급에
// 닿는다"를 계산한다.
//
// 두 가지를 지킨다.
//
//   1. **경보를 발령하지 않는다.** §8.2 가 "추세 경고는 독립적인 경보를 발령하지 않고,
//      대시보드에 시각적 표시만 제공한다"고 못박는다. 여기서 나온 값은 배지일 뿐이고
//      alert_level 을 바꾸지 않는다.
//   2. **LSTM 이 아니다.** §8.3 의 LSTM 예측은 01_PRD OUT OF SCOPE 다. 여기서는
//      학습 모델 없이 기울기만 외삽한다.

import type { AlertLevel, MetricKey } from "../types";
import type { TrendPoint } from "../store/dashboardStore";

/** 회귀에 넣을 최근 구간. §8.2 의 이동평균 창(30초)보다 길게 잡아 잡음을 눌러준다. */
export const TREND_WINDOW_MS = 10 * 60 * 1000;

/** 이보다 적으면 기울기를 신뢰하지 않는다. */
export const MIN_TREND_POINTS = 4;

/**
 * 외삽 신뢰 한계. 이보다 먼 미래는 표시하지 않는다.
 * 분당 0.5ppm 같은 미세한 기울기로 "13시간 뒤 도달"을 띄우면 오해를 부른다.
 */
export const MAX_PROJECTION_MINUTES = 60;

/** 등급 상승 순서와 CO₂/CO/H₂S 진입 임계값 (backend/migrations/005_thresholds.sql). */
const ENTER_THRESHOLDS: Partial<Record<MetricKey, [AlertLevel, number][]>> = {
  co2_ppm: [
    ["level1_caution", 1000],
    ["level2_warning", 2000],
    ["level3_critical", 5000],
  ],
  co_ppm: [
    ["level1_caution", 25],
    ["level2_warning", 50],
    ["level3_critical", 200],
  ],
  h2s_ppm: [
    ["level1_caution", 1],
    ["level2_warning", 5],
    ["level3_critical", 10],
  ],
};

function withinWindow(points: TrendPoint[], now: number): TrendPoint[] {
  const cutoff = now - TREND_WINDOW_MS;
  return points.filter((p) => p.t >= cutoff);
}

function latestTimestamp(points: TrendPoint[]): number {
  return points.reduce((max, p) => (p.t > max ? p.t : max), Number.NEGATIVE_INFINITY);
}

/**
 * 최소자승 선형 회귀 기울기 (ppm/분). 점이 부족하거나 시간 폭이 0이면 null.
 * `now` 를 주면 그 시점 기준 창을 적용한다 (기본: 마지막 샘플 시각).
 */
export function slopePerMinute(points: TrendPoint[], now?: number): number | null {
  if (points.length === 0) return null;
  const reference = now ?? latestTimestamp(points);
  const win = withinWindow(points, reference);
  if (win.length < 2) return null;

  const n = win.length;
  const meanT = win.reduce((s, p) => s + p.t, 0) / n;
  const meanV = win.reduce((s, p) => s + p.v, 0) / n;

  let num = 0;
  let den = 0;
  for (const p of win) {
    const dt = p.t - meanT;
    num += dt * (p.v - meanV);
    den += dt * dt;
  }
  if (den === 0) return null;
  return (num / den) * 60_000; // ppm/ms → ppm/분
}

/** 지수 가중 이동평균. 최근 값에 더 무게를 준다. */
export function ewma(points: TrendPoint[], alpha: number): number | null {
  if (points.length === 0) return null;
  return points.reduce((acc, p, i) => (i === 0 ? p.v : alpha * p.v + (1 - alpha) * acc), 0);
}

export interface ThresholdProjection {
  /** 이 추세가 유지되면 닿게 될 등급. */
  level: AlertLevel;
  /** 도달까지 남은 분. */
  minutes: number;
  /** 참고용 기울기 (ppm/분). */
  slopePerMinute: number;
}

/**
 * 다음 등급 임계값에 닿기까지 남은 시간을 추정한다.
 * 하강·정체 중이거나, 이미 최고 등급이거나, 너무 먼 미래면 null.
 */
export function projectThresholdCrossing(
  points: TrendPoint[],
  metric: MetricKey,
  now?: number,
): ThresholdProjection | null {
  const ladder = ENTER_THRESHOLDS[metric];
  if (!ladder) return null;

  const reference = now ?? latestTimestamp(points);
  const win = withinWindow(points, reference);
  if (win.length < MIN_TREND_POINTS) return null;

  const slope = slopePerMinute(points, reference);
  if (slope === null || slope <= 0) return null;

  // 평활값을 현재 값으로 쓴다. 마지막 한 점의 튐에 예측이 끌려가지 않도록.
  const current = ewma(win, 0.4);
  if (current === null) return null;

  const next = ladder.find(([, threshold]) => current < threshold);
  if (!next) return null; // 이미 최고 등급 구간

  const [level, threshold] = next;
  const minutes = (threshold - current) / slope;
  if (!Number.isFinite(minutes) || minutes <= 0) return null;
  if (minutes > MAX_PROJECTION_MINUTES) return null;

  return { level, minutes, slopePerMinute: slope };
}
