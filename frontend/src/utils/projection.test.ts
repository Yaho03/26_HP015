import { describe, expect, it } from "vitest";
import type { TrendPoint } from "../store/dashboardStore";
import {
  mostUrgentProjection,
  PROJECTION_HORIZON_S,
  rSquared,
  trendProjection,
} from "./projection";

/** t0 에서 시작해 분당 perMinute 만큼 오르는 직선. trend.test.ts 와 같은 헬퍼다. */
function ramp(from: number, perMinute: number, minutes: number, t0 = 0): TrendPoint[] {
  const out: TrendPoint[] = [];
  for (let i = 0; i <= minutes * 2; i++) {
    const t = t0 + i * 30_000;
    out.push({ t, v: from + perMinute * (i / 2) });
  }
  return out;
}

describe("rSquared", () => {
  it("완전한 직선은 1 이다", () => {
    expect(rSquared(ramp(600, 100, 10))).toBeCloseTo(1, 6);
  });

  it("흩어진 값은 1 보다 뚜렷하게 작다", () => {
    const noisy = ramp(600, 100, 10).map((p, i) => ({
      t: p.t,
      // 부호가 번갈아 크게 튀면 직선이 설명하는 몫이 줄어든다.
      v: p.v + (i % 2 === 0 ? 400 : -400),
    }));
    const r2 = rSquared(noisy);
    expect(r2).not.toBeNull();
    expect(r2!).toBeLessThan(0.8);
  });

  it("평평하면 null 이다 — R²=1 로 답하면 '완벽한 예측' 으로 읽힌다", () => {
    expect(rSquared(ramp(700, 0, 10))).toBeNull();
  });

  it("점이 부족하면 null 이다", () => {
    expect(rSquared([{ t: 0, v: 600 }])).toBeNull();
    expect(rSquared([])).toBeNull();
  });
});

describe("trendProjection", () => {
  it("상승 중이면 도달 등급·시간·출처를 낸다", () => {
    // CO₂ 600 → 1600ppm 을 10분에 걸쳐 오른 구간. 현재값은 EWMA 라 마지막 값
    // 쪽에 실려 이미 level1_caution(1000) 을 넘었으므로, 다음 관문은
    // level2_warning(2000) 이다.
    const p = trendProjection(ramp(600, 100, 10), "co2_ppm");
    expect(p).not.toBeNull();
    expect(p!.level).toBe("level2_warning");
    expect(p!.source).toBe("trend");
    expect(p!.metric).toBe("co2_ppm");
    expect(p!.minutes).toBeGreaterThan(0);
  });

  it("하강 중이면 null 이다", () => {
    expect(trendProjection(ramp(3000, -250, 10), "co2_ppm")).toBeNull();
  });

  it("추세가 없으면 null 이다", () => {
    expect(trendProjection(undefined, "co2_ppm")).toBeNull();
    expect(trendProjection([], "co2_ppm")).toBeNull();
  });

  it("임계값 사다리가 없는 지표는 null 이다", () => {
    // 온도는 trend.ts ENTER_THRESHOLDS 에 없다 — 여기서 임의로 만들어내지 않는다.
    expect(trendProjection(ramp(20, 5, 10), "temperature_c")).toBeNull();
  });

  it("곡선의 마지막 점이 도달 시각과 일치한다", () => {
    // 곡선 시작값(EWMA)과 도달 시각(minutes)이 어긋나면 점선이 임계선에 닿지
    // 않은 채 끝나거나 지나쳐서 끝난다 — 화면이 거짓말을 한다.
    const p = trendProjection(ramp(600, 100, 10), "co2_ppm")!;
    const last = p.curve[p.curve.length - 1];
    expect(last.offsetS).toBeCloseTo(Math.round(p.minutes * 60), 0);
    // 그 지점의 값은 level2_warning 진입 임계값(2000)이어야 한다.
    expect(last.value).toBeCloseTo(2000, 0);
  });

  it("곡선은 horizon 을 넘지 않는다", () => {
    // 아주 완만한 상승이면 도달까지 오래 걸리지만 그려주는 구간은 5분까지다.
    const p = trendProjection(ramp(600, 20, 30), "co2_ppm");
    expect(p).not.toBeNull();
    for (const point of p!.curve) {
      expect(point.offsetS).toBeLessThanOrEqual(PROJECTION_HORIZON_S);
    }
  });

  it("선형 외삽에는 불확실성 구간이 없다", () => {
    // lower/upper 는 LSTM 예측에만 있다. 여기서 임의로 만들어내면 화면이
    // 근거 없는 신뢰구간을 그린다.
    const p = trendProjection(ramp(600, 100, 10), "co2_ppm")!;
    for (const point of p.curve) {
      expect(point.lower).toBeUndefined();
      expect(point.upper).toBeUndefined();
    }
  });

  it("깨끗한 직선의 신뢰도는 높다", () => {
    const p = trendProjection(ramp(600, 100, 10), "co2_ppm")!;
    expect(p.confidence).not.toBeNull();
    expect(p.confidence!).toBeGreaterThan(0.95);
  });
});

describe("mostUrgentProjection", () => {
  it("임박한 시간보다 높은 등급을 먼저 고른다", () => {
    // CO₂ 는 곧 L2(2000) 에 닿고, H₂S 는 조금 늦게 L3(10) 에 닿는다.
    // 시간만 보면 CO₂ 가 이기지만 등급이 낮아서 밀린다.
    const p = mostUrgentProjection({
      co2_ppm: ramp(1600, 100, 10),
      h2s_ppm: ramp(5.2, 0.3, 10),
    });
    expect(p).not.toBeNull();
    expect(p!.level).toBe("level3_critical");
    expect(p!.metric).toBe("h2s_ppm");
  });

  it("등급이 같으면 임박한 쪽을 고른다", () => {
    const p = mostUrgentProjection({
      co2_ppm: ramp(600, 20, 10), // 현재 ~790 → level1_caution(1000) 까지 느리게
      co_ppm: ramp(10, 1, 10), // 현재 ~19.5 → level1_caution(25) 까지 빠르게
    });
    expect(p).not.toBeNull();
    expect(p!.level).toBe("level1_caution");
    expect(p!.metric).toBe("co_ppm");
  });

  it("상승 중인 지표가 없으면 null 이다", () => {
    expect(mostUrgentProjection({ co2_ppm: ramp(3000, -250, 10) })).toBeNull();
    expect(mostUrgentProjection({})).toBeNull();
    expect(mostUrgentProjection(undefined)).toBeNull();
  });
});
