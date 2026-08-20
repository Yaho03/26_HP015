import { describe, expect, it } from "vitest";
import { mockExposure } from "../mocks/exposure";
import {
  EXPOSURE_DISCLAIMER,
  doseLevel,
  formatDuration,
  formatFraction,
  hasActiveDose,
  worstDoseFraction,
  worstExposureLevel,
} from "./exposure";

const NOW = Date.parse("2026-08-21T03:00:00.000Z");

describe("doseLevel", () => {
  // 이슈 #165 와 같은 규칙. 판정 못 한 것을 normal 로 떨어뜨리면 실제 위험이
  // 초록으로 보인다.
  it("산출 불가는 normal 이 아니라 unknown 이다", () => {
    expect(doseLevel({ status: "unavailable", reason: "uncalibrated" })).toBe("unknown");
    expect(doseLevel(undefined)).toBe("unknown");
  });

  it("서버가 alert_level 을 안 주면 unknown 이다", () => {
    expect(doseLevel({ status: "active", dose_fraction: 0.9 })).toBe("unknown");
  });

  // dose_fraction 에서 등급을 역산하지 않는다 — 그건 임계값 하드코딩이다 (FR-201).
  it("등급은 dose_fraction 이 아니라 서버 alert_level 을 따른다", () => {
    expect(doseLevel({ status: "active", dose_fraction: 1.4, alert_level: "normal" })).toBe(
      "normal",
    );
  });
});

describe("worstDoseFraction", () => {
  it("활성 지표가 없으면 0 이 아니라 null 이다", () => {
    // 0 을 돌려주면 호출부가 "0% 노출"로 그린다. 그게 §6.4 가 금지하는 표시다.
    const msg = mockExposure("limit_unverified", NOW);
    expect(worstDoseFraction(msg)).toBeNull();
    expect(hasActiveDose(msg)).toBe(false);
  });

  it("활성 지표 중 최댓값을 고른다", () => {
    expect(worstDoseFraction(mockExposure("exceeded", NOW))).toBeCloseTo(1.15, 5);
  });

  it("unavailable 지표는 후보에서 빠진다", () => {
    // 미교정 상태는 CO₂ 만 활성이다.
    expect(worstDoseFraction(mockExposure("uncalibrated", NOW))).toBeCloseTo(0.31, 5);
  });

  it("메시지가 없으면 null 이다", () => {
    expect(worstDoseFraction(null)).toBeNull();
  });
});

describe("worstExposureLevel", () => {
  it("가장 높은 등급을 고른다", () => {
    expect(worstExposureLevel(mockExposure("exceeded", NOW))).toBe("level3_critical");
  });

  // LEVEL_RANK 에서 unknown 은 normal 보다 위다. 시드를 unknown 으로 두면 전부
  // 정상인 메시지도 영영 unknown 으로 나온다 — 실제로 밟았던 버그다.
  it("모든 지표가 정상이면 normal 이다", () => {
    expect(worstExposureLevel(mockExposure("normal", NOW))).toBe("normal");
  });

  it("한 지표라도 판정 불가면 unknown 으로 내려간다", () => {
    // 미교정 상태는 CO₂·O₂ 가 정상이고 CO·H₂S 가 unavailable 이다.
    expect(worstExposureLevel(mockExposure("uncalibrated", NOW))).toBe("unknown");
  });

  it("확인된 위험은 판정 불가에 가려지지 않는다", () => {
    expect(worstExposureLevel(mockExposure("warning", NOW))).toBe("level2_warning");
  });

  it("지표가 하나도 없으면 unknown 이다", () => {
    const empty = { ...mockExposure("normal", NOW), metrics: {} };
    expect(worstExposureLevel(empty)).toBe("unknown");
    expect(worstExposureLevel(null)).toBe("unknown");
  });
});

describe("formatFraction", () => {
  // 누적값은 100% 에서 멈추지 않는다. 상한을 두면 110% 와 300% 가 같아 보인다.
  it("1.0 을 넘겨도 자르지 않는다", () => {
    expect(formatFraction(1.15)).toBe("115%");
    expect(formatFraction(3)).toBe("300%");
  });

  it("0 은 0% 다", () => {
    expect(formatFraction(0)).toBe("0%");
  });
});

describe("formatDuration", () => {
  it("초·분·시간 단위로 끊어 읽는다", () => {
    expect(formatDuration(45)).toBe("45초");
    expect(formatDuration(320)).toBe("5분");
    expect(formatDuration(3600)).toBe("1시간");
    expect(formatDuration(7500)).toBe("2시간 5분");
  });

  it("음수는 0 으로 눌러 표시한다", () => {
    expect(formatDuration(-5)).toBe("0초");
  });
});

describe("EXPOSURE_DISCLAIMER", () => {
  // 11_EXPOSURE_DOSE_SPEC §1.1 이 요구하는 네 가지. 하나라도 빠지면 축약이
  // 아니라 왜곡이라 테스트로 묶어 둔다.
  it("§1.1 필수 요소를 모두 담는다", () => {
    expect(EXPOSURE_DISCLAIMER).toContain("법정 작업환경측정");
    expect(EXPOSURE_DISCLAIMER).toContain("추정값");
    expect(EXPOSURE_DISCLAIMER).toContain("법정 기준");
    expect(EXPOSURE_DISCLAIMER).toContain("현장 관리자");
  });

  it("생리학적 축적을 주장하지 않는다 (§7 한계 #7)", () => {
    expect(EXPOSURE_DISCLAIMER).not.toContain("체내");
    expect(EXPOSURE_DISCLAIMER).not.toContain("축적");
  });
});

describe("mockExposure", () => {
  it("A1 이 요구한 네 상태를 만들어낸다", () => {
    expect(mockExposure("normal", NOW).metrics.co2_ppm?.dose_fraction).toBeCloseTo(0.2, 5);

    const warning = mockExposure("warning", NOW);
    expect(warning.metrics.co2_ppm?.dose_fraction).toBeCloseTo(0.85, 5);
    expect(warning.trust_level).toBe("medium");
    expect(warning.metrics.co2_ppm?.source_distance_m).toBeCloseTo(2.4, 5);

    const exceeded = mockExposure("exceeded", NOW);
    expect(exceeded.metrics.co2_ppm?.dose_fraction).toBeCloseTo(1.15, 5);
    expect(exceeded.metrics.h2s_ppm?.stel_exceeded).toBe(true);

    const uncal = mockExposure("uncalibrated", NOW);
    expect(uncal.metrics.co_ppm).toEqual({ status: "unavailable", reason: "uncalibrated" });
    expect(uncal.metrics.h2s_ppm).toEqual({ status: "unavailable", reason: "uncalibrated" });
  });

  // 손으로 적은 세 숫자는 반드시 어긋나고, 화면에서는 계산 버그처럼 보인다.
  it("dose / limit / TWA 가 서로 일관된다", () => {
    const m = mockExposure("warning", NOW).metrics.co2_ppm;
    expect(m?.dose_ppm_min).toBeCloseTo((m?.dose_limit_ppm_min ?? 0) * 0.85, 3);
    expect(m?.twa_8h_ppm).toBeCloseTo((m?.dose_ppm_min ?? 0) / 480, 3);
  });

  it("accumulated_s = elapsed_s - data_gap_s (§2.2)", () => {
    for (const state of ["normal", "warning", "exceeded", "uncalibrated"] as const) {
      const m = mockExposure(state, NOW);
      expect(m.accumulated_s).toBe(m.elapsed_s - m.data_gap_s);
    }
  });
});
