import { describe, expect, it } from "vitest";
import type { TrendPoint } from "../store/dashboardStore";
import {
  ewma,
  MIN_TREND_POINTS,
  projectThresholdCrossing,
  slopePerMinute,
  TREND_WINDOW_MS,
} from "./trend";

const MIN = 60_000;

/** t0 에서 시작해 분당 perMinute 만큼 오르는 직선. */
function ramp(from: number, perMinute: number, minutes: number, t0 = 0): TrendPoint[] {
  const out: TrendPoint[] = [];
  for (let i = 0; i <= minutes * 2; i++) {
    const t = t0 + i * 30_000;
    out.push({ t, v: from + perMinute * (i / 2) });
  }
  return out;
}

describe("slopePerMinute", () => {
  it("상승 기울기를 ppm/분 으로 낸다", () => {
    expect(slopePerMinute(ramp(600, 100, 10))).toBeCloseTo(100, 5);
  });

  it("하강 기울기는 음수다", () => {
    expect(slopePerMinute(ramp(3000, -250, 10))).toBeCloseTo(-250, 5);
  });

  it("평평하면 0 이다", () => {
    expect(slopePerMinute(ramp(700, 0, 10))).toBeCloseTo(0, 5);
  });

  it("점이 부족하면 null 을 낸다", () => {
    expect(slopePerMinute([{ t: 0, v: 600 }])).toBeNull();
    expect(slopePerMinute([])).toBeNull();
  });

  it("창 밖의 오래된 점은 기울기에 넣지 않는다", () => {
    // 앞쪽 30분은 급락, 최근 5분은 완만한 상승. 창이 동작하면 결과는 양수여야 한다.
    const now = 60 * MIN;
    const old: TrendPoint[] = ramp(9000, -300, 25, now - 60 * MIN);
    const recent: TrendPoint[] = ramp(600, 40, 5, now - 5 * MIN);
    expect(slopePerMinute([...old, ...recent], now)).toBeGreaterThan(0);
  });
});

describe("ewma", () => {
  it("마지막 값 쪽으로 치우친 평활값을 낸다", () => {
    const points = ramp(600, 100, 10);
    const last = points[points.length - 1].v;
    const smoothed = ewma(points, 0.3)!;
    expect(smoothed).toBeLessThan(last);
    expect(smoothed).toBeGreaterThan(points[0].v);
  });

  it("빈 배열이면 null", () => {
    expect(ewma([], 0.3)).toBeNull();
  });
});

describe("projectThresholdCrossing", () => {
  it("상승 중이면 다음 임계값 도달까지 남은 분을 낸다", () => {
    // 현재 600ppm 근처, 분당 100ppm 상승 → L1(1000) 까지 4분 남짓
    const r = projectThresholdCrossing(ramp(200, 100, 4), "co2_ppm", 4 * MIN);
    expect(r).not.toBeNull();
    expect(r!.level).toBe("level1_caution");
    expect(r!.minutes).toBeGreaterThan(0);
    expect(r!.minutes).toBeLessThan(8);
  });

  it("이미 L1 구간이면 그 다음 단계인 L2 를 예측한다", () => {
    // 현재 1200ppm(=L1 구간), 분당 200ppm 상승 → 다음은 L2(2000)
    const r = projectThresholdCrossing(ramp(400, 200, 4), "co2_ppm", 4 * MIN);
    expect(r!.level).toBe("level2_warning");
  });

  it("하강 중이면 예측하지 않는다", () => {
    expect(projectThresholdCrossing(ramp(1500, -100, 10), "co2_ppm", 10 * MIN)).toBeNull();
  });

  it("평평하면 예측하지 않는다", () => {
    expect(projectThresholdCrossing(ramp(700, 0, 10), "co2_ppm", 10 * MIN)).toBeNull();
  });

  it("이미 최고 등급이면 더 예측할 단계가 없다", () => {
    const r = projectThresholdCrossing(ramp(6000, 100, 10), "co2_ppm", 10 * MIN);
    expect(r).toBeNull();
  });

  it("점이 부족하면 예측하지 않는다", () => {
    const few = ramp(600, 100, 10).slice(0, MIN_TREND_POINTS - 1);
    expect(projectThresholdCrossing(few, "co2_ppm", 10 * MIN)).toBeNull();
  });

  it("너무 먼 미래는 내지 않는다 — 외삽 신뢰 구간을 넘는다", () => {
    // 분당 0.5ppm 이면 L1 까지 800분. 이런 값을 화면에 띄우면 오히려 오해를 부른다.
    expect(projectThresholdCrossing(ramp(600, 0.5, 30), "co2_ppm", 30 * MIN)).toBeNull();
  });

  it("임계값이 없는 지표는 예측하지 않는다", () => {
    expect(projectThresholdCrossing(ramp(20, 1, 10), "temperature_c", 10 * MIN)).toBeNull();
  });

  it("창 길이는 06_ALERT_RULES 8.2 의 이동평균 기준보다 길다", () => {
    expect(TREND_WINDOW_MS).toBeGreaterThanOrEqual(30_000);
  });
});
