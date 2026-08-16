import { describe, expect, it } from "vitest";
import {
  DEMO_SPACE,
  displayPositionFor,
  FILL_PRESET,
  mapDemoToShip,
  SHIP_FLOOR_HALF_WIDTH_M,
  SHIP_SPACE,
  shipFloorHalfWidthAt,
  shouldMapToShip,
  toThreePosition,
  UNIFORM_PRESET,
  UNIFORM_SCALE,
} from "./coordinates";

describe("toThreePosition — Z-up → Y-up", () => {
  it("05_DIGITAL_TWIN_SPEC 3.2 의 축 매핑을 따른다", () => {
    // three_x = physical_x / three_y = physical_z / three_z = -physical_y
    expect(toThreePosition({ x_m: 10, y_m: 5, z_m: 2 })).toEqual([10, 2, -5]);
  });

  it("y 부호를 반전해 오른손 좌표계를 유지한다", () => {
    // 반전을 빼면 행렬식이 -1 이 되어 장면이 거울상으로 뒤집힌다.
    const port = toThreePosition({ x_m: 10, y_m: -5, z_m: 0 });
    const starboard = toThreePosition({ x_m: 10, y_m: 5, z_m: 0 });
    expect(port[2]).toBe(5);
    expect(starboard[2]).toBe(-5);
    expect(port[2]).toBe(-starboard[2]);
  });
});

describe("mapDemoToShip", () => {
  it("FILL 은 바닥 평면을 가득 채운다", () => {
    const origin = mapDemoToShip({ x_m: 0, y_m: 0, z_m: 0 }, FILL_PRESET);
    const far = mapDemoToShip(
      { x_m: DEMO_SPACE.length_m, y_m: DEMO_SPACE.width_m, z_m: 0 },
      FILL_PRESET,
    );
    expect(origin.x_m).toBeCloseTo(0);
    expect(origin.y_m).toBeCloseTo(-SHIP_FLOOR_HALF_WIDTH_M);
    expect(far.x_m).toBeCloseTo(SHIP_SPACE.length_m);
    expect(far.y_m).toBeCloseTo(SHIP_FLOOR_HALF_WIDTH_M);
  });

  it("문서 3.1 의 예시값을 재현한다 — raw(1.2, 0.8) → (28.8, -1.3)", () => {
    const p = mapDemoToShip({ x_m: 1.2, y_m: 0.8, z_m: 0 }, FILL_PRESET);
    expect(p.x_m).toBeCloseTo(28.8, 5);
    expect(p.y_m).toBeCloseTo(-1.3, 5);
  });

  it("UNIFORM 은 두 축에 같은 배율을 써서 형상비를 보존한다", () => {
    const a = mapDemoToShip({ x_m: 0, y_m: 0, z_m: 0 }, UNIFORM_PRESET);
    const b = mapDemoToShip({ x_m: 1, y_m: 1, z_m: 0 }, UNIFORM_PRESET);
    expect(b.x_m - a.x_m).toBeCloseTo(b.y_m - a.y_m, 5);
    expect(b.x_m - a.x_m).toBeCloseTo(UNIFORM_SCALE, 5);
  });

  it("균일 배율은 폭에 먼저 막힌다", () => {
    expect(UNIFORM_SCALE).toBeCloseTo(6.5, 5);
  });

  it("z 는 늘리지 않는다 — 측위가 2D 고정이라 항상 0 이다", () => {
    expect(mapDemoToShip({ x_m: 1, y_m: 1, z_m: 0 }, FILL_PRESET).z_m).toBe(0);
  });

  it("공간 밖 좌표는 경계로 잘린다", () => {
    const p = mapDemoToShip({ x_m: 99, y_m: -99, z_m: 0 }, FILL_PRESET);
    expect(p.x_m).toBeCloseTo(SHIP_SPACE.length_m);
    expect(p.y_m).toBeCloseTo(-SHIP_FLOOR_HALF_WIDTH_M);
  });
});

describe("중복 변환 방지", () => {
  it("이미 ship-visual 이면 변환하지 않는다", () => {
    expect(shouldMapToShip("ship-visual")).toBe(false);
    const raw = { x_m: 10, y_m: -5, z_m: 0 };
    expect(displayPositionFor(raw, "ship-visual", FILL_PRESET)).toEqual(raw);
  });

  it("demo-local 은 변환한다", () => {
    expect(shouldMapToShip("demo-local")).toBe(true);
    const out = displayPositionFor({ x_m: 1.2, y_m: 0.8, z_m: 0 }, "demo-local", FILL_PRESET);
    expect(out!.x_m).toBeCloseTo(28.8, 5);
  });

  it("좌표계를 모르면 변환한다 — 구버전 백엔드는 demo-local 만 보냈다", () => {
    expect(shouldMapToShip(undefined)).toBe(true);
  });

  it("위치가 없으면 null", () => {
    expect(displayPositionFor(null, "demo-local", FILL_PRESET)).toBeNull();
    expect(displayPositionFor(undefined, "demo-local", FILL_PRESET)).toBeNull();
  });
});

describe("shipFloorHalfWidthAt", () => {
  it("중앙에서 가장 넓고 양끝에서 좁아진다", () => {
    const mid = shipFloorHalfWidthAt(SHIP_SPACE.length_m / 2);
    expect(mid).toBeCloseTo(SHIP_FLOOR_HALF_WIDTH_M, 5);
    expect(shipFloorHalfWidthAt(0)).toBeLessThan(mid);
    expect(shipFloorHalfWidthAt(SHIP_SPACE.length_m)).toBeLessThan(mid);
  });

  it("양끝은 중앙의 60% 다", () => {
    expect(shipFloorHalfWidthAt(0)).toBeCloseTo(SHIP_FLOOR_HALF_WIDTH_M * 0.6, 5);
  });

  it("좌우 대칭이다", () => {
    expect(shipFloorHalfWidthAt(10)).toBeCloseTo(shipFloorHalfWidthAt(50), 5);
  });
});
