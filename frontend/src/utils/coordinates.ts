// 좌표계 변환 단일 소스.
//
// 세 좌표계가 있고 서로 섞으면 안 된다 (docs/05_DIGITAL_TWIN_SPEC §3).
//
//   1. demo-local   실측 좌표. 축소 실험 장비 2.5 x 2.0 x 1.5 m. Z-up.
//   2. ship-visual  표시 좌표. 선박형 트윈 60 x 20 x 14 m. Z-up.
//   3. Three.js     렌더 좌표. Y-up.
//
// 1 → 2 는 비율 매핑(프리셋), 2 → 3 은 축 변환이다. 둘은 별개이고 순서가 있다.

import type { Position3D } from "../types";

/** 축소 실험 장비 공간 (05_DIGITAL_TWIN_SPEC §2). */
export const DEMO_SPACE = { length_m: 2.5, width_m: 2.0, height_m: 1.5 } as const;

/** 선박형 트윈 공간 (05_DIGITAL_TWIN_SPEC §3.1.2). */
export const SHIP_SPACE = { length_m: 60, width_m: 20, height_m: 14 } as const;

// 선체는 상자가 아니라 높이에 따라 폭이 변한다. 바닥 평면의 반폭은 TwinScene 의
// FHW=6.5 이고, 폭 20m 는 높이 5.5~9.0m 의 수직 측벽에서만 나온다. 작업자는 바닥을
// 걷고 히트맵도 바닥 격자이므로, 매핑 대상은 선체 폭이 아니라 바닥 평면 폭이다.
export const SHIP_FLOOR_HALF_WIDTH_M = 6.5;
export const SHIP_FLOOR_WIDTH_M = SHIP_FLOOR_HALF_WIDTH_M * 2;

/** demo-local 사각형을 ship-visual 바닥의 어느 사각형으로 보낼지. */
export interface MappingTarget {
  min_x_m: number;
  width_m: number;
  min_y_m: number;
  depth_m: number;
}

export type MappingPresetId = "fill" | "uniform";

export interface MappingPreset {
  id: MappingPresetId;
  /** 화면에 표시할 짧은 설명. */
  label: string;
  target: MappingTarget;
}

/**
 * 바닥 전체를 채운다. 축마다 배율이 달라(x 24배 / y 6.5배) 형상이 4.6:1 로
 * 늘어난다. 좁은 패널에서 화물창 전체를 한눈에 봐야 할 때 쓴다.
 */
export const FILL_PRESET: MappingPreset = {
  id: "fill",
  label: "FILL / 바닥 전체",
  target: {
    min_x_m: 0,
    width_m: SHIP_SPACE.length_m,
    min_y_m: -SHIP_FLOOR_HALF_WIDTH_M,
    depth_m: SHIP_FLOOR_WIDTH_M,
  },
};

/**
 * 형상비를 보존한다. 두 축에 같은 배율을 쓰므로 정사각 보행이 정사각으로 보인다.
 * 폭이 먼저 차서 배율이 결정되고(= 6.5배), 길이 방향은 남는 만큼 가운데 정렬한다.
 */
export const UNIFORM_SCALE =
  Math.min(SHIP_SPACE.length_m / DEMO_SPACE.length_m, SHIP_FLOOR_WIDTH_M / DEMO_SPACE.width_m);

const uniformWidth = DEMO_SPACE.length_m * UNIFORM_SCALE;
const uniformDepth = DEMO_SPACE.width_m * UNIFORM_SCALE;

export const UNIFORM_PRESET: MappingPreset = {
  id: "uniform",
  label: "TRUE SCALE / 비율 보존",
  target: {
    min_x_m: (SHIP_SPACE.length_m - uniformWidth) / 2,
    width_m: uniformWidth,
    min_y_m: -uniformDepth / 2,
    depth_m: uniformDepth,
  },
};

export const MAPPING_PRESETS: Record<MappingPresetId, MappingPreset> = {
  fill: FILL_PRESET,
  uniform: UNIFORM_PRESET,
};

function clamp01(value: number): number {
  return Math.max(0, Math.min(1, value));
}

/**
 * demo-local 실측 좌표 → ship-visual 표시 좌표.
 *
 * 이 함수는 **demo-local 입력만** 받는다. 이미 ship-visual 인 값에 다시 적용하면
 * 좌표가 두 번 확대된다. 호출 전에 좌표계를 확인할 것 (shouldMapToShip 참고).
 */
export function mapDemoToShip(position: Position3D, preset: MappingPreset): Position3D {
  const { target } = preset;
  return {
    x_m: target.min_x_m + clamp01(position.x_m / DEMO_SPACE.length_m) * target.width_m,
    y_m: target.min_y_m + clamp01(position.y_m / DEMO_SPACE.width_m) * target.depth_m,
    // 측위는 2D 고정이라 z_m 은 항상 0 이다 (04_DATA_CONTRACT §4.4). 높이를 늘리지 않는다.
    z_m: position.z_m,
  };
}

/**
 * 이 좌표계를 ship-visual 로 변환해야 하는가.
 * 이미 ship-visual 인 값(실제 선박 좌표를 직접 수신하는 경우)은 그대로 쓴다.
 */
export function shouldMapToShip(source: string | undefined): boolean {
  return source !== "ship-visual";
}

/**
 * 실측 좌표에서 표시 좌표를 파생한다. 표시 좌표를 저장하지 않고 렌더 시점에
 * 만드는 이유는 화면마다 프리셋이 다르기 때문이다.
 */
export function displayPositionFor(
  raw: Position3D | null | undefined,
  source: string | undefined,
  preset: MappingPreset,
): Position3D | null {
  if (!raw) return null;
  return shouldMapToShip(source) ? mapDemoToShip(raw, preset) : raw;
}

/**
 * 고정 센서의 표시 위치 (05_DIGITAL_TWIN_SPEC §3.1.2).
 * 이미 ship-visual 좌표이므로 비율 매핑을 적용하지 않는다.
 */
export const SENSOR_SHIP_POSITIONS: Record<string, { x: number; y: number }> = {
  "sensor-01": { x: 10.0, y: -5.0 },
  "sensor-02": { x: 50.0, y: -5.0 },
  "sensor-03": { x: 10.0, y: 5.0 },
  "sensor-04": { x: 50.0, y: 5.0 },
};

/**
 * ship-visual (Z-up) → Three.js (Y-up).
 *
 * docs/05_DIGITAL_TWIN_SPEC §3.2:
 *   three_x = physical_x
 *   three_y = physical_z
 *   three_z = -physical_y
 *
 * y 부호를 반전해야 오른손 좌표계가 유지된다. 반전을 빼면 행렬식이 -1 이 되어
 * 장면 전체가 거울상으로 그려지고 port/starboard 가 뒤바뀐다.
 */
export function toThreePosition(position: Position3D): [number, number, number] {
  return [position.x_m, position.z_m, -position.y_m];
}

/**
 * 길이 방향 테이퍼 계수. 화물창은 직육면체가 아니라 양끝으로 갈수록 좁아진다.
 * 중앙에서 1.0, 양끝에서 0.60. TwinScene 의 선체 로프팅과 같은 식을 쓴다.
 */
export function shipBeamFactor(x_m: number): number {
  const t = Math.abs((2 * x_m) / SHIP_SPACE.length_m - 1);
  return 1 - 0.4 * Math.pow(t, 2.2);
}

/** 길이 방향 위치 x 에서의 바닥 평면 반폭. */
export function shipFloorHalfWidthAt(x_m: number): number {
  return SHIP_FLOOR_HALF_WIDTH_M * shipBeamFactor(x_m);
}

/** 2D 평면 좌표(ship-visual x, y)에 대한 toThreePosition. 높이는 호출부가 정한다. */
export function toThreeGroundPosition(
  x_m: number,
  y_m: number,
  height_m: number,
): [number, number, number] {
  return [x_m, height_m, -y_m];
}
