import { beforeEach, describe, expect, it } from "vitest";
import {
  classifyMetric,
  classifyO2High,
  classifyO2Low,
  isThresholdTableLoaded,
  maxLevel,
  nodeAlertLevel,
  setThresholdTable,
  thresholdApproach,
  thresholdLinesFor,
  type ServerThreshold,
} from "./alerts";
import type { MetricKey, SensorNodeState } from "../types";

/** 서버 GET /api/thresholds 응답 형태. */
function server(rows: [string, string, "above" | "below", number][]): ServerThreshold[] {
  return rows.map(([metric, level, direction, enter_threshold]) => ({
    metric,
    level,
    direction,
    enter_threshold,
  }));
}

/** 판정에 필요한 필드만 채운 노드. */
function nodeWith(values: Partial<Record<MetricKey, number>>): SensorNodeState {
  const readings: SensorNodeState["readings"] = {};
  for (const [metric, value] of Object.entries(values) as [MetricKey, number][]) {
    readings[metric] = { metric, value, sampled_at: "2026-01-01T00:00:00Z" };
  }
  return {
    node_id: "sensor-01",
    readings,
    battery_pct: null,
    wifi_rssi_dbm: null,
    connection_status: "online",
    last_seen_at: null,
  };
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
    expect(classifyMetric("co2_ppm", 9999)).not.toBe("level3_critical");
    expect(thresholdLinesFor("co2_ppm")).toEqual([]);
  });

  it("로드되면 loaded 가 true", () => {
    setThresholdTable(DEFAULTS);
    expect(isThresholdTableLoaded()).toBe(true);
  });
});

// 이슈 #165 — 임계값을 못 받은 동안 "정상"으로 표시하면 안 된다.
// 모르는 상태를 안전하다고 말하는 것은 안전 화면에서 가장 위험한 거짓말이다.
describe("임계값 미로딩 — 정상이 아니라 판정 불가다", () => {
  beforeEach(() => setThresholdTable([]));

  it("어떤 값이 와도 normal 이 아니다", () => {
    expect(classifyMetric("co2_ppm", 9999)).toBe("unknown");
    expect(classifyMetric("co2_ppm", 0)).toBe("unknown");
  });

  it("O₂ 는 양방향 모두 판정 불가다", () => {
    expect(classifyO2Low(10)).toBe("unknown");
    expect(classifyO2High(30)).toBe("unknown");
  });

  it("노드 종합 등급도 판정 불가다", () => {
    expect(nodeAlertLevel(nodeWith({ co2_ppm: 9999 }))).toBe("unknown");
  });

  it("백엔드가 등급을 내려줬으면 그것을 쓴다", () => {
    // 서버 판정은 서버 임계값으로 이미 끝났다. 프론트 테이블과 무관하다.
    const node = { ...nodeWith({ co2_ppm: 9999 }), alert_level: "level2_warning" as const };
    expect(nodeAlertLevel(node)).toBe("level2_warning");
  });
});

describe("임계값 로딩 후 — 규칙 없는 지표는 여전히 normal", () => {
  it("테이블은 받았지만 그 지표에 규칙이 없으면 normal", () => {
    setThresholdTable(DEFAULTS);
    // 미로딩(unknown)과 구분되어야 한다. 규칙이 없다 = 판정할 게 없다 = 정상.
    expect(classifyMetric("humidity_pct", 99)).toBe("normal");
    expect(nodeAlertLevel(nodeWith({ humidity_pct: 99 }))).toBe("normal");
  });
});

describe("maxLevel — unknown 은 normal 보다 위다", () => {
  it("판정 불가가 정상을 이긴다", () => {
    // 한 지표라도 판정 못 하면 노드 전체를 정상이라 말할 수 없다.
    expect(maxLevel("unknown", "normal")).toBe("unknown");
    expect(maxLevel("normal", "unknown")).toBe("unknown");
  });

  it("실제 경보는 판정 불가를 이긴다", () => {
    // 모르는 지표 하나 때문에 확인된 위험이 가려지면 안 된다.
    expect(maxLevel("unknown", "level1_caution")).toBe("level1_caution");
    expect(maxLevel("level3_critical", "unknown")).toBe("level3_critical");
  });
});

describe("thresholdApproach — 임계값 대비 근접도", () => {
  it("다음 등급의 진입 임계값을 기준으로 채운다", () => {
    const a = thresholdApproach("co2_ppm", 500);
    expect(a).not.toBeNull();
    expect(a!.level).toBe("level1_caution");
    expect(a!.enter).toBe(1000);
    expect(a!.ratio).toBeCloseTo(0.5, 5);
  });

  it("한 등급을 넘으면 그 다음 관문으로 기준이 바뀐다", () => {
    const a = thresholdApproach("co2_ppm", 1500);
    expect(a!.level).toBe("level2_warning");
    expect(a!.enter).toBe(2000);
    expect(a!.ratio).toBeCloseTo(0.75, 5);
  });

  it("최고 등급 구간이면 가득 찬다", () => {
    const a = thresholdApproach("co2_ppm", 9000);
    expect(a!.level).toBe("level3_critical");
    expect(a!.ratio).toBe(1);
  });

  it("below 방향(O₂ 저농도)은 값이 내려갈수록 찬다", () => {
    const far = thresholdApproach("o2_low", 20.9);
    const near = thresholdApproach("o2_low", 19.8);
    expect(far!.level).toBe("level1_caution");
    expect(far!.enter).toBe(19.5);
    expect(near!.ratio).toBeGreaterThan(far!.ratio);
    expect(thresholdApproach("o2_low", 19.5)!.ratio).toBe(1);
  });

  it("임계값을 못 받았으면 null — 바를 그리지 않는다", () => {
    // 여기서 임의의 만점 눈금을 만들면, 판정 불가 상태의 바가 "여유 있음"으로
    // 보인다 (이슈 #165).
    setThresholdTable([]);
    expect(thresholdApproach("co2_ppm", 500)).toBeNull();
  });

  it("규칙이 없는 지표(온도·습도)도 null", () => {
    expect(thresholdApproach("temperature_c", 24.5)).toBeNull();
  });
});
