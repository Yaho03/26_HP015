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
export const UNIFORM_SCALE = Math.min(
  SHIP_SPACE.length_m / DEMO_SPACE.length_m,
  SHIP_FLOOR_WIDTH_M / DEMO_SPACE.width_m,
);

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
 *
 * ── x = 15 / 45 을 고른 근거 (길이 60m 의 사분점) ──────────────────
 * IDW 보간에서 "가장 가까운 센서까지의 거리"가 최악인 지점을 최소화하는 배치다.
 *   x=15/45 : 중앙(30,0)까지 15.35m, 끝단 모서리까지 약 15.0m → 최댓값 ≈ 15.4m
 *   x=10/50 : 중앙까지 20.6m,       끝단까지 10.0m          → 최댓값 ≈ 20.6m
 * 이전 배치는 끝단만 촘촘하고 정작 작업자가 오래 머무는 중앙이 가장 부실했다.
 *
 * ── y = ±3.25 을 고른 근거 (바닥 반폭 6.5m 의 절반) ────────────────
 * 선체는 상자가 아니라 길이 방향으로 테이퍼진다 (shipFloorHalfWidthAt).
 *   x=15 지점의 바닥 반폭 5.93m → y=±3.25 는 반폭의 55%. 벽에서 충분히 떨어졌다.
 *   이전 x=10, y=±5 는 그 지점 반폭 5.43m 의 92% — 사실상 벽에 붙어 있었다.
 * 벽면에 붙은 센서는 공간 평균 농도를 대표하지 못한다.
 *
 * 이 변경은 **표시 전용**이다. 백엔드 UWB 측위(config.uwb_anchors)는 축소 데모
 * 공간의 demo-local 좌표를 쓰고, 펌웨어에는 ship-visual 좌표가 없다. 즉 경보
 * 판정 경로를 건드리지 않는다.
 */
export const SENSOR_SHIP_POSITIONS: Record<string, { x: number; y: number }> = {
  "sensor-01": { x: 15.0, y: -3.25 }, // 전방 port
  "sensor-02": { x: 45.0, y: -3.25 }, // 후방 port
  "sensor-03": { x: 15.0, y: 3.25 }, // 전방 starboard
  "sensor-04": { x: 45.0, y: 3.25 }, // 후방 starboard
};

/**
 * ① 디지털 트윈 칸이 쓰는 사선 탑뷰("plan" 카메라)의 배치 비율.
 * 카메라는 바닥 중앙을 타깃으로 [TL*0.5, fit*HEIGHT, -fit*DEPTH] 에 선다.
 * atan(0.82 / 0.58) ≈ 54.7° — 수평 대비 약 55° 의 사선 탑뷰다.
 *
 * TwinScene 과 아래 화면축 계산이 같은 값을 봐야 하므로 여기서 단일 정의한다.
 */
export const PLAN_CAM = { heightRatio: 0.82, depthRatio: 0.58 } as const;

export type ScreenQuadrant = "top-left" | "top-right" | "bottom-left" | "bottom-right";

/**
 * ship-visual 바닥 좌표 → plan 카메라 화면에서의 중앙 기준 오프셋.
 *
 * Three.js Matrix4.lookAt 기저는 z_local = normalize(eye - target),
 * x_local = normalize(up × z_local), y_local = z_local × x_local 이다.
 * eye - target = (0, +h, -d) 이므로
 *   x_local = (0,1,0) × (0, h, -d) = (-d, 0, 0) → 화면 오른쪽 = world −X
 *   y_local = (0, d, h)            → 바닥면(y=0)에서 화면 위쪽 = world +three_z
 * 그리고 three_z = −y_ship 이다 (§3.2 축 변환).
 *
 * 결과적으로 **화면 오른쪽 = x_ship 감소, 화면 위쪽 = y_ship 감소** 다.
 * 카메라가 선체 starboard(+y) 쪽 절개면 밖에서 선수(x=0) 쪽을 오른쪽에 두고
 * 들여다보기 때문이다. 지도처럼 "x 가 오른쪽"으로 착각하기 쉬운 지점이라
 * SENSOR_SCREEN_ORDER 를 눈으로 정하지 말고 이 함수로 검증할 것.
 */
export function planScreenOffset(x_m: number, y_m: number): { sx: number; sy: number } {
  return { sx: -(x_m - SHIP_SPACE.length_m / 2), sy: -y_m };
}

/** plan 카메라 화면에서 이 바닥 좌표가 속하는 사분면. */
export function planScreenQuadrant(x_m: number, y_m: number): ScreenQuadrant {
  const { sx, sy } = planScreenOffset(x_m, y_m);
  return `${sy >= 0 ? "top" : "bottom"}-${sx >= 0 ? "right" : "left"}` as ScreenQuadrant;
}

/** 2×2 격자를 읽는 순서. planScreenQuadrant 의 값 순서와 1:1 로 맞춘다. */
export const SCREEN_QUADRANT_ORDER: readonly ScreenQuadrant[] = [
  "top-left",
  "top-right",
  "bottom-left",
  "bottom-right",
] as const;

/**
 * ① 사선 탑뷰 화면에서의 사분면 순서 (좌상 → 우상 → 좌하 → 우하).
 * ⑤ 노드별 센서 데이터 2×2 격자를 이 순서로 그리면 "①에서 좌상단이 뜨거우면
 * ⑤의 좌상단 칸을 본다"가 성립한다.
 *
 * 자연스러운 sensor-01..04 순서가 **아니다.** 위 planScreenOffset 주석대로
 * 화면 오른쪽이 x_ship 감소 방향이라, 전방(x=15) 노드가 화면 오른쪽에 온다.
 * 값을 손으로 고치지 말고 coordinates.test.ts 의 투영 테스트로 확인할 것.
 */
export const SENSOR_SCREEN_ORDER = [
  "sensor-02", // 좌상 — 후방 port
  "sensor-01", // 우상 — 전방 port
  "sensor-04", // 좌하 — 후방 starboard
  "sensor-03", // 우하 — 전방 starboard
] as const;

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
