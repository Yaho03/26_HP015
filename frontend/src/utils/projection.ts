// "이 추세가 유지되면 n분 뒤 어느 등급에 닿는가" — 출처 추상화 (Screen 1 ②③).
//
// 지금 출처는 utils/trend.ts 의 선형 외삽 하나뿐이다. LSTM forecaster 가
// READY_FOR_RESEARCH_DISPLAY 를 내면 co2_ppm 만 그쪽으로 바뀌고 나머지 지표는
// 계속 선형 외삽으로 남는다. 즉 한 화면에 두 출처가 동시에 존재하게 되므로,
// 렌더 경로를 하나로 두고 `source` 로만 구분한다. 화면은 배지 문구만 갈린다.
//
// 세 가지를 지킨다.
//
//   1. **경보를 발령하지 않는다.** 06_ALERT_RULES §8.2 가 "추세 경고는 독립적인
//      경보를 발령하지 않고, 대시보드에 시각적 표시만 제공한다"고 못박는다.
//      여기서 나온 값은 배지와 점선 스파크라인 전용이다.
//   2. **AlertLevel 을 만들어내지 않는다.** `level` 은 "이 추세가 유지되면 닿을
//      등급"이지 지금 등급이 아니다. nodeAlertLevel() 결과를 덮어쓰지 않는다.
//   3. **confidence 는 확률이 아니다.** 선형 적합도(R²)다. "78% 확률로 위험"이
//      아니라 "관측점이 직선에 78% 들어맞는다"는 뜻이고, 화면 문구도 그렇게 쓴다.

import { ewma, projectThresholdCrossing, TREND_WINDOW_MS } from "./trend";
import { LEVEL_RANK } from "./alerts";
import type { AlertLevel, MetricKey } from "../types";
import type { TrendMetric, TrendPoint } from "../store/dashboardStore";

/**
 * 외삽 곡선을 그리는 구간. LSTM 계약의 forecast_horizon_seconds(300) 와 맞춘다 —
 * 두 출처가 같은 가로 폭을 그려야 카드끼리 비교가 된다.
 */
export const PROJECTION_HORIZON_S = 300;

/** 곡선 표본 간격. 300초 / 60초 = 5점. */
export const PROJECTION_STEP_S = 60;

/** EWMA 평활 계수. trend.projectThresholdCrossing 과 같은 값을 써야 곡선 시작점과
 *  도달 시각이 어긋나지 않는다 (projection.test.ts 가 이 일치를 붙잡는다). */
const EWMA_ALPHA = 0.4;

export interface ProjectionPoint {
  /** 마지막 관측 시점 기준 경과 초. */
  offsetS: number;
  value: number;
  /** 불확실성 구간. 선형 외삽에는 없고 LSTM 예측에만 있다. */
  lower?: number;
  upper?: number;
}

export interface Projection {
  metric: MetricKey;
  /** 다음 등급 임계값에 닿기까지 남은 분. */
  minutes: number;
  /** 그때 닿을 등급. **현재 등급이 아니다.** */
  level: AlertLevel;
  /** 선형 적합도 R² (0~1). 확률이 아니다. 산출 불가면 null. */
  confidence: number | null;
  source: "trend" | "lstm";
  /** 스파크라인 점선 구간. 비어 있을 수 있다. */
  curve: ProjectionPoint[];
}

function latestTimestamp(points: TrendPoint[]): number {
  return points.reduce((max, p) => (p.t > max ? p.t : max), Number.NEGATIVE_INFINITY);
}

function withinWindow(points: TrendPoint[], reference: number): TrendPoint[] {
  return points.filter((p) => p.t >= reference - TREND_WINDOW_MS);
}

/**
 * 선형 회귀 결정계수 R².
 *
 * 1 에 가까울수록 관측점이 직선에 잘 들어맞는다 — 즉 외삽을 믿을 만하다.
 * 0 에 가까우면 값이 흩어져 있어서 기울기가 아무것도 설명하지 못한다.
 *
 * **이것은 "위험이 발생할 확률"이 아니다.** 값이 매끄럽게 상승하면 R² 는 1 에
 * 가깝지만 그렇다고 예측이 맞는다는 보장은 없다. 반대로 R² 가 낮으면 그 외삽은
 * 확실히 못 믿는다 — 한쪽 방향으로만 쓸 수 있는 지표다.
 */
export function rSquared(points: TrendPoint[], now?: number): number | null {
  if (points.length === 0) return null;
  const reference = now ?? latestTimestamp(points);
  const win = withinWindow(points, reference);
  if (win.length < 3) return null; // 두 점은 항상 R²=1 이라 의미가 없다

  const n = win.length;
  const meanT = win.reduce((s, p) => s + p.t, 0) / n;
  const meanV = win.reduce((s, p) => s + p.v, 0) / n;

  let sTV = 0;
  let sTT = 0;
  let sVV = 0;
  for (const p of win) {
    const dt = p.t - meanT;
    const dv = p.v - meanV;
    sTV += dt * dv;
    sTT += dt * dt;
    sVV += dv * dv;
  }
  // 시간 폭이 0 이면 회귀 자체가 성립하지 않는다.
  if (sTT === 0) return null;
  // 값이 완전히 평평하면 설명할 분산이 없다. 이때 R²=1 로 답하면 "완벽한 예측"
  // 으로 읽히는데, 실제로는 아무 일도 일어나지 않는 구간이다.
  if (sVV === 0) return null;

  const r2 = (sTV * sTV) / (sTT * sVV);
  return Math.max(0, Math.min(1, r2));
}

/**
 * 선형 외삽 기반 도달 예측.
 *
 * 하강·정체 중이거나, 이미 최고 등급이거나, 60분보다 먼 미래면 null —
 * 판정은 전부 trend.projectThresholdCrossing 에 맡기고 여기서는 곡선과
 * 신뢰도만 얹는다. 임계값 사다리를 여기에 다시 적지 않는다.
 */
export function trendProjection(
  points: TrendPoint[] | undefined,
  metric: MetricKey,
  now?: number,
): Projection | null {
  if (!points || points.length === 0) return null;

  const crossing = projectThresholdCrossing(points, metric, now);
  if (!crossing) return null;

  const reference = now ?? latestTimestamp(points);
  const win = withinWindow(points, reference);
  const base = ewma(win, EWMA_ALPHA);
  if (base === null) return null;

  // 기울기를 초당으로 환산해 표본을 찍는다. 도달 시각(minutes)을 넘어서까지
  // 그리지 않는다 — 임계값을 지난 뒤의 외삽은 근거가 없다.
  const perSecond = crossing.slopePerMinute / 60;
  const endS = Math.min(PROJECTION_HORIZON_S, Math.round(crossing.minutes * 60));

  const curve: ProjectionPoint[] = [];
  for (let offsetS = PROJECTION_STEP_S; offsetS <= endS; offsetS += PROJECTION_STEP_S) {
    curve.push({ offsetS, value: base + perSecond * offsetS });
  }
  // 도달 지점이 표본 간격에 걸리지 않으면 마지막 점을 따로 찍는다. 점선이
  // 임계선에 닿지 않은 채 끝나면 "아직 멀었다"로 읽힌다.
  const last = curve[curve.length - 1];
  if (endS > 0 && (!last || last.offsetS < endS)) {
    curve.push({ offsetS: endS, value: base + perSecond * endS });
  }

  return {
    metric,
    minutes: crossing.minutes,
    level: crossing.level,
    confidence: rSquared(points, now),
    source: "trend",
    curve,
  };
}

/**
 * 여러 지표 중 화면에 띄울 예측 하나를 고른다.
 *
 * **더 높은 등급이 먼저다.** 3분 뒤 L1 주의와 9분 뒤 L3 위험이 같이 있으면
 * L3 를 보여준다 — 시간이 가깝다는 이유로 덜 심각한 예고가 더 심각한 예고를
 * 가리면 안 된다. 등급이 같을 때만 임박한 쪽을 고른다.
 */
export function mostUrgentProjection(
  trends: Partial<Record<TrendMetric, TrendPoint[]>> | undefined,
  now?: number,
): Projection | null {
  if (!trends) return null;

  let best: Projection | null = null;
  for (const key of Object.keys(trends) as TrendMetric[]) {
    const p = trendProjection(trends[key], key, now);
    if (!p) continue;
    if (!best) {
      best = p;
      continue;
    }
    const rank = LEVEL_RANK[p.level] - LEVEL_RANK[best.level];
    if (rank > 0 || (rank === 0 && p.minutes < best.minutes)) best = p;
  }
  return best;
}
