import { describe, expect, it } from "vitest";
import * as THREE from "three";
import {
  DEMO_SPACE,
  displayPositionFor,
  FILL_PRESET,
  mapDemoToShip,
  PLAN_CAM,
  planScreenQuadrant,
  SCREEN_QUADRANT_ORDER,
  SENSOR_SCREEN_ORDER,
  SENSOR_SHIP_POSITIONS,
  SHIP_FLOOR_HALF_WIDTH_M,
  SHIP_SPACE,
  shipFloorHalfWidthAt,
  shouldMapToShip,
  toThreeGroundPosition,
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

describe("SENSOR_SHIP_POSITIONS — 사분점 배치", () => {
  const CENTER_X = SHIP_SPACE.length_m / 2;
  const ids = Object.keys(SENSOR_SHIP_POSITIONS);

  it("네 노드가 길이 방향 사분점에 있다", () => {
    expect(new Set(ids.map((id) => SENSOR_SHIP_POSITIONS[id].x))).toEqual(new Set([15, 45]));
  });

  it("최악 지점까지의 거리가 이전 배치(10/50)보다 작다", () => {
    // 배치 근거의 핵심. 중앙은 작업자가 가장 오래 머무는 자리이므로 여기가 부실하면
    // IDW 히트맵이 정작 중요한 곳에서 가장 부정확해진다.
    const worstAt = (x: number) =>
      Math.max(
        Math.hypot(CENTER_X - x, 3.25), // 바닥 중앙
        Math.hypot(x, 3.25), // 선수 끝단
      );
    expect(worstAt(15)).toBeLessThan(worstAt(10));
    expect(worstAt(15)).toBeLessThan(16);
  });

  it("벽에 붙지 않는다 — 해당 x 의 바닥 반폭 대비 60% 미만", () => {
    for (const id of ids) {
      const { x, y } = SENSOR_SHIP_POSITIONS[id];
      expect(Math.abs(y) / shipFloorHalfWidthAt(x)).toBeLessThan(0.6);
    }
  });

  it("port(-y) 두 개 / starboard(+y) 두 개로 갈린다", () => {
    expect(ids.filter((id) => SENSOR_SHIP_POSITIONS[id].y < 0)).toHaveLength(2);
    expect(ids.filter((id) => SENSOR_SHIP_POSITIONS[id].y > 0)).toHaveLength(2);
  });
});

describe("SENSOR_SCREEN_ORDER — ① 사선 탑뷰와 ⑤ 2×2 격자의 대응", () => {
  /**
   * planScreenOffset 을 다시 쓰지 않고 실제 Three.js 카메라로 투영해서 확인한다.
   * 같은 식을 두 번 쓰면 식이 틀렸을 때 테스트도 같이 틀린다.
   */
  function projectToNdc(x_m: number, y_m: number): { x: number; y: number } {
    const fit = 40; // 임의의 fit 거리. 사분면 판정은 거리에 무관해야 한다.
    const camera = new THREE.PerspectiveCamera(60, 16 / 9, 0.1, 500);
    camera.position.set(
      SHIP_SPACE.length_m * 0.5,
      fit * PLAN_CAM.heightRatio,
      -fit * PLAN_CAM.depthRatio,
    );
    camera.lookAt(SHIP_SPACE.length_m * 0.5, 0, 0);
    camera.updateMatrixWorld();
    const [tx, ty, tz] = toThreeGroundPosition(x_m, y_m, 0);
    const ndc = new THREE.Vector3(tx, ty, tz).project(camera);
    return { x: ndc.x, y: ndc.y };
  }

  it("plan 카메라는 수평 대비 약 55° 의 사선 탑뷰다", () => {
    const angle = (Math.atan2(PLAN_CAM.heightRatio, PLAN_CAM.depthRatio) * 180) / Math.PI;
    expect(angle).toBeGreaterThan(50);
    expect(angle).toBeLessThan(60);
  });

  it("planScreenQuadrant 가 실제 카메라 투영과 일치한다", () => {
    for (const id of Object.keys(SENSOR_SHIP_POSITIONS)) {
      const { x, y } = SENSOR_SHIP_POSITIONS[id];
      const ndc = projectToNdc(x, y);
      const projected = `${ndc.y >= 0 ? "top" : "bottom"}-${ndc.x >= 0 ? "right" : "left"}`;
      expect(planScreenQuadrant(x, y)).toBe(projected);
    }
  });

  it("좌표를 바꾸면 깨진다 — 화면 사분면 순서가 SENSOR_SCREEN_ORDER 와 같다", () => {
    // 이 테스트가 이 상수의 존재 이유다. SENSOR_SHIP_POSITIONS 나 PLAN_CAM 을
    // 손대면 여기서 잡히고, 그때 상수를 손으로 고치는 게 아니라 실패 메시지가
    // 알려주는 새 순서로 갱신해야 한다.
    const byQuadrant = SCREEN_QUADRANT_ORDER.map((quadrant) =>
      Object.keys(SENSOR_SHIP_POSITIONS).find((id) => {
        const { x, y } = SENSOR_SHIP_POSITIONS[id];
        const ndc = projectToNdc(x, y);
        return `${ndc.y >= 0 ? "top" : "bottom"}-${ndc.x >= 0 ? "right" : "left"}` === quadrant;
      }),
    );
    expect(byQuadrant).toEqual([...SENSOR_SCREEN_ORDER]);
  });

  it("네 노드가 서로 다른 사분면을 하나씩 차지한다", () => {
    expect(new Set(SENSOR_SCREEN_ORDER).size).toBe(4);
    expect(new Set(SENSOR_SCREEN_ORDER)).toEqual(new Set(Object.keys(SENSOR_SHIP_POSITIONS)));
  });
});
