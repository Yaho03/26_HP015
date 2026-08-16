import { beforeEach, describe, expect, it } from "vitest";
import {
  classifyMetric,
  classifyO2High,
  classifyO2Low,
  isThresholdTableLoaded,
  setThresholdTable,
  thresholdLinesFor,
  type ServerThreshold,
} from "./alerts";

/** 서버 GET /api/thresholds 응답 형태. */
function server(rows: [string, string, "above" | "below", number][]): ServerThreshold[] {
  return rows.map(([metric, level, direction, enter_threshold]) => ({
    metric,
    level,
    direction,
    enter_threshold,
  }));
}

const DEFAULTS = server([
  ["co2_ppm", "level1_caution", "above", 1000],
  ["co2_ppm", "level2_warning", "above", 2000],
  ["co2_ppm", "level3_critical", "above", 5000],
  ["o2_low", "level1_caution", "below", 19.5],
  ["o2_low", "level2_warning", "below", 18.0],
  ["o2_low", "level3_critical", "below", 16.0],
  ["o2_high", "level1_caution", "above", 23.5],
  ["o2_high", "level2_warning", "above", 25.0],
  ["o2_high", "level3_critical", "above", 28.0],
]);

beforeEach(() => setThresholdTable(DEFAULTS));

describe("classifyMetric — 서버 임계값을 따른다", () => {
  it("구간별로 등급을 매긴다", () => {
    expect(classifyMetric("co2_ppm", 999)).toBe("normal");
    expect(classifyMetric("co2_ppm", 1000)).toBe("level1_caution");
    expect(classifyMetric("co2_ppm", 2000)).toBe("level2_warning");
    expect(classifyMetric("co2_ppm", 5000)).toBe("level3_critical");
  });

  it("경계값은 포함이다 (>= enter)", () => {
    expect(classifyMetric("co2_ppm", 1000)).toBe("level1_caution");
    expect(classifyMetric("co2_ppm", 999.9)).toBe("normal");
  });

  it("가장 높은 등급을 우선한다", () => {
    // 9000 은 세 구간을 전부 넘는다
    expect(classifyMetric("co2_ppm", 9000)).toBe("level3_critical");
  });

  it("★ 서버 임계값이 바뀌면 판정도 바뀐다 (FR-204)", () => {
    expect(classifyMetric("co2_ppm", 1500)).toBe("level1_caution");
    setThresholdTable(server([["co2_ppm", "level2_warning", "above", 1200]]));
    expect(classifyMetric("co2_ppm", 1500)).toBe("level2_warning");
  });

  it("임계값이 없는 지표는 normal", () => {
    expect(classifyMetric("humidity_pct", 99)).toBe("normal");
  });
});

describe("O₂ — 저농도/고농도는 방향이 반대다", () => {
  it("저농도는 낮을수록 위험하다", () => {
    expect(classifyO2Low(20.9)).toBe("normal");
    expect(classifyO2Low(19.4)).toBe("level1_caution");
    expect(classifyO2Low(17.9)).toBe("level2_warning");
    expect(classifyO2Low(15.9)).toBe("level3_critical");
  });

  it("고농도는 높을수록 위험하다", () => {
    expect(classifyO2High(20.9)).toBe("normal");
    expect(classifyO2High(23.6)).toBe("level1_caution");
    expect(classifyO2High(25.1)).toBe("level2_warning");
    expect(classifyO2High(28.1)).toBe("level3_critical");
  });

  it("정상 범위는 양쪽 다 normal", () => {
    expect(classifyO2Low(20.9)).toBe("normal");
    expect(classifyO2High(20.9)).toBe("normal");
  });
});

describe("thresholdLinesFor — 차트 기준선", () => {
  it("서버 값을 그대로 낸다", () => {
    const lines = thresholdLinesFor("co2_ppm");
    expect(lines.map((l) => l.value).sort((a, b) => a - b)).toEqual([1000, 2000, 5000]);
  });

  it("임계값이 없는 지표는 빈 배열", () => {
    expect(thresholdLinesFor("humidity_pct")).toEqual([]);
  });
});

describe("로딩 전 상태 — 하드코딩 폴백이 없다", () => {
  it("테이블이 비면 판정하지 않는다", () => {
    setThresholdTable([]);
    expect(isThresholdTableLoaded()).toBe(false);
    // 하드코딩이 남아 있었다면 여기서 level3_critical 이 나온다.
    expect(classifyMetric("co2_ppm", 9999)).toBe("normal");
    expect(thresholdLinesFor("co2_ppm")).toEqual([]);
  });

  it("로드되면 loaded 가 true", () => {
    setThresholdTable(DEFAULTS);
    expect(isThresholdTableLoaded()).toBe(true);
  });
});
