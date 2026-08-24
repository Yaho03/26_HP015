import { describe, expect, it } from "vitest";
import { doseProjection, DOSE_HORIZON_MIN, formatDoseEta } from "./doseProjection";
import type { ExposureDoseMetric } from "../types/ws";

function metric(over: Partial<ExposureDoseMetric> = {}): ExposureDoseMetric {
  return {
    status: "active",
    dose_ppm_min: 4_200,
    dose_limit_ppm_min: 10_000,
    dose_fraction: 0.42,
    twa_15min_ppm: 200,
    ...over,
  };
}

const HOUR_S = 3_600;

describe("doseProjection", () => {
  it("남은 양을 현재 속도로 나눈다", () => {
    // 남은 5,800 ppm·min ÷ 200 ppm/분 = 29분.
    const p = doseProjection(metric(), HOUR_S);
    expect(p).not.toBeNull();
    expect(p!.minutes).toBeCloseTo(29, 5);
    expect(p!.ratePpm).toBe(200);
  });

  it("twa 가 없으면 윈도우 평균 속도로 물러선다", () => {
    // 1시간에 4,200 쌓였으니 70 ppm/분. 남은 5,800 ÷ 70 ≈ 82.9분.
    const p = doseProjection(metric({ twa_15min_ppm: null }), HOUR_S);
    expect(p).not.toBeNull();
    expect(p!.ratePpm).toBeCloseTo(70, 5);
    expect(p!.minutes).toBeCloseTo(82.857, 2);
  });

  it("산출 불가 지표는 null 이다", () => {
    // 여기서 "여유" 로 그리면 측정 못 한 것을 안전하다고 말하는 것이다.
    expect(doseProjection(metric({ status: "unavailable" }), HOUR_S)).toBeNull();
    expect(doseProjection(undefined, HOUR_S)).toBeNull();
  });

  it("필요한 필드가 없으면 null 이다", () => {
    expect(doseProjection(metric({ dose_ppm_min: null }), HOUR_S)).toBeNull();
    expect(doseProjection(metric({ dose_limit_ppm_min: null }), HOUR_S)).toBeNull();
    expect(doseProjection(metric({ dose_limit_ppm_min: 0 }), HOUR_S)).toBeNull();
  });

  it("적산이 멈춰 있으면 도달하지 않는다", () => {
    expect(doseProjection(metric({ twa_15min_ppm: 0 }), HOUR_S)).toBeNull();
    expect(doseProjection(metric({ twa_15min_ppm: -5 }), HOUR_S)).toBeNull();
  });

  it("이미 한도를 넘었으면 null 이다", () => {
    // "몇 분 뒤" 가 아니라 이미 벌어진 일이다 — 화면이 다르게 말해야 한다.
    expect(doseProjection(metric({ dose_ppm_min: 12_000 }), HOUR_S)).toBeNull();
    expect(doseProjection(metric({ dose_ppm_min: 10_000 }), HOUR_S)).toBeNull();
  });

  it("8시간보다 멀면 null 이다", () => {
    // 노출 기준 자체가 8시간 기준이라 그 너머 외삽은 근거가 없다.
    const slow = doseProjection(metric({ dose_ppm_min: 0, twa_15min_ppm: 0.5 }), HOUR_S);
    expect(slow).toBeNull();
    // 경계 바로 안쪽은 나온다.
    const rate = 10_000 / (DOSE_HORIZON_MIN - 1);
    expect(doseProjection(metric({ dose_ppm_min: 0, twa_15min_ppm: rate }), HOUR_S)).not.toBeNull();
  });

  it("twa 폴백에서 적산 시간이 0이면 null 이다", () => {
    expect(doseProjection(metric({ twa_15min_ppm: null }), 0)).toBeNull();
  });
});

describe("formatDoseEta", () => {
  it("1시간 미만은 분으로", () => {
    expect(formatDoseEta(27)).toBe("27분 뒤 한도 도달");
  });
  it("1시간 이상은 시간으로", () => {
    expect(formatDoseEta(90)).toBe("1시간 30분 뒤 한도 도달");
    expect(formatDoseEta(120)).toBe("2시간 뒤 한도 도달");
  });
});
