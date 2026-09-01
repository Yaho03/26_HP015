import { beforeEach, describe, expect, it } from "vitest";
import { gasRamp, idw, LEVEL_RGB } from "./idw";
import { setThresholdTable } from "./alerts";

const CO2 = [
  { metric: "co2_ppm", level: "level1_caution", direction: "above" as const, enter_threshold: 1000 },
  { metric: "co2_ppm", level: "level2_warning", direction: "above" as const, enter_threshold: 2000 },
  { metric: "co2_ppm", level: "level3_critical", direction: "above" as const, enter_threshold: 5000 },
];

function near(a: readonly number[], b: readonly number[]) {
  a.forEach((v, i) => expect(v).toBeCloseTo(b[i], 5));
}

describe("idw", () => {
  it("표본 위에서는 그 표본 값을 그대로 낸다", () => {
    expect(idw([{ x: 1, y: 1, value: 800 }], 1, 1)).toBe(800);
  });

  it("두 표본 사이 중점은 평균이다", () => {
    const v = idw(
      [
        { x: 0, y: 0, value: 0 },
        { x: 10, y: 0, value: 1000 },
      ],
      5,
      0,
    );
    expect(v).toBeCloseTo(500, 5);
  });

  it("표본이 없으면 0 이다", () => {
    expect(idw([], 0, 0)).toBe(0);
  });
});

describe("gasRamp", () => {
  beforeEach(() => setThresholdTable(CO2));

  it("임계값에 정확히 닿으면 그 등급 색이 나온다", () => {
    // 연속으로 섞어도 등급 경계는 화면에서 사라지면 안 된다.
    near(gasRamp("co2_ppm", 1000), LEVEL_RGB.level1_caution);
    near(gasRamp("co2_ppm", 2000), LEVEL_RGB.level2_warning);
    near(gasRamp("co2_ppm", 5000), LEVEL_RGB.level3_critical);
  });

  it("정상 구간 안에서는 초록 농담만 연속으로 변한다", () => {
    const low = gasRamp("co2_ppm", 600);
    const high = gasRamp("co2_ppm", 990);
    expect(low).not.toEqual(high);
    expect(low[1]).toBeGreaterThan(low[0]);
    expect(high[1]).toBeGreaterThan(high[0]);
    expect(high[1]).toBeGreaterThan(low[1]);
  });

  it("0 은 정상 색이다", () => {
    near(gasRamp("co2_ppm", 0), LEVEL_RGB.normal);
  });

  it("최고 등급을 넘어도 더 짙어지지 않는다", () => {
    // 여기서 색을 더 밀면 최고 등급 안에 "덜 위험한 빨강" 이 생긴다.
    near(gasRamp("co2_ppm", 9999), LEVEL_RGB.level3_critical);
  });

  it("임계값을 못 받았으면 무채색이다", () => {
    // 초록으로 칠하면 판정 못 한 격자가 안전해 보인다 (이슈 #165).
    setThresholdTable([]);
    near(gasRamp("co2_ppm", 600), LEVEL_RGB.unknown);
  });

  it("사다리가 없는 지표는 정상 색으로 둔다", () => {
    // 테이블은 받았는데 그 지표에 규칙이 없는 경우다 — 모르는 상태가 아니다.
    near(gasRamp("temperature_c", 25), LEVEL_RGB.normal);
  });
});

describe("gasRamp — 구간 앞부분은 제 등급 색을 지킨다", () => {
  beforeEach(() => setThresholdTable(CO2));

  it("정상 구간 한가운데는 여전히 정상 쪽에 가깝다", () => {
    // 선형으로 섞으면 571ppm 이 벌써 주의색에 절반쯤 물들어 정상인 격자가
    // 주의처럼 읽힌다. 정상 격자가 노랗게 보이는 것은 오독을 부른다.
    const mid = gasRamp("co2_ppm", 500);
    const dNormal = Math.abs(mid[0] - LEVEL_RGB.normal[0]);
    const dCaution = Math.abs(mid[0] - LEVEL_RGB.level1_caution[0]);
    expect(dNormal).toBeLessThan(dCaution);
  });

  it("임계값 직전까지 노란색으로 바뀌지 않는다", () => {
    const near = gasRamp("co2_ppm", 999);
    expect(near[1]).toBeGreaterThan(near[0]);
  });
});
