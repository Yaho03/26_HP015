import * as THREE from "three";
import type { RouteStatus, RouteWaypoint } from "../types/ws";
import { toThreePosition } from "./coordinates";

/**
 * 탈출 경로 3D 형상 계산 (FR-804).
 *
 * TwinScene 안에 있던 순수 계산을 꺼냈다. 렌더링과 섞여 있으면 검증하려면 WebGL
 * 컨텍스트가 필요한데, 이 저장소의 vitest 는 jsdom 없이 도므로 사실상 검증할 수
 * 없었다. 실제로 "3D 캔버스 육안 확인"은 PR #199 에서 미검증으로 남았다.
 *
 * 여기 있는 것은 전부 입력→출력이 결정적인 함수다. 사다리가 수직으로 서는지,
 * 길이 0 구간이 빠지는지, 점선이 어떻게 끊기는지를 화면 없이 확인할 수 있다.
 */

/** 바닥면과 겹쳐 z-fighting 이 생기지 않을 만큼만 띄운다. */
export const ROUTE_LIFT = 0.25;
export const ROUTE_RADIUS = 0.16;

/**
 * 원기둥·원뿔 지오메트리의 기준 축. three 의 기본이 +Y 이고, 구간 방향으로
 * 돌리는 회전을 여기서부터 구한다.
 */
export const ROUTE_UP = new THREE.Vector3(0, 1, 0);

/**
 * route_status → 안전 등급 램프 토큰 이름.
 *
 * **hex 를 여기에 적지 않는 것이 요점이다.** 예전에는 TwinScene 이 색을 직접
 * 적어 뒀는데, global.css 의 램프가 나중에 개정되면서 2D 평면도(=CSS 변수)와
 * 3D 트윈(=박아둔 hex)의 경로 색이 네 상태 모두 갈라졌다. 주석이 경고하던
 * 그대로였다.
 *
 * 이제 양쪽이 같은 토큰 이름을 가리킨다 — styles/evacuation.css 의
 * `.evac { --evac-safe: var(--normal) … }` 와 이 표가 같은 매핑이어야 하고,
 * routeGeometry.test.ts 가 그 일치를 CSS 원문과 대조해 잠근다.
 */
export const ROUTE_COLOR_VAR: Record<RouteStatus, string> = {
  safe: "--normal",
  degraded: "--l2",
  no_safe_route: "--l3",
  unavailable: "--unknown",
};

/**
 * CSS 를 읽을 수 없을 때만 쓰는 값 (서버 렌더링·테스트).
 *
 * 실제 화면에서는 항상 CSS 변수가 이긴다. 이 값이 낡아도 배포된 화면의 색은
 * 틀리지 않는다 — 그래서 여기에 램프 개정이 반영되지 않아도 2D/3D 가 갈라지지
 * 않는다.
 */
export const ROUTE_COLOR_FALLBACK: Record<RouteStatus, string> = {
  safe: "#3ecf8e",
  degraded: "#ff9040",
  no_safe_route: "#ff5470",
  unavailable: "#8f97b8",
};

/** waypoint 를 three 좌표(Y-up)로 옮기고 바닥에서 살짝 띄운다. */
export function routePoints(waypoints: RouteWaypoint[], lift = ROUTE_LIFT): THREE.Vector3[] {
  return waypoints.map((wp) => {
    const [x, y, z] = toThreePosition({ x_m: wp.x_m, y_m: wp.y_m, z_m: wp.z_m });
    return new THREE.Vector3(x, y + lift, z);
  });
}

/**
 * 진행 방향 화살표가 탈 곡선.
 *
 * 길이 0 구간을 빼고 만든다. LineCurve3 의 길이가 0 이면 getTangentAt 이
 * NaN 을 돌려주고, 화살표가 화면에서 사라지거나 원점으로 튄다. 사다리 구간은
 * 평면에서 한 점이지만 3D 에서는 z 가 변하므로 길이가 0 이 아니다 — 여기서
 * 걸러지는 것은 토폴로지에 중복 좌표가 들어간 경우다.
 */
export function routeCurve(points: THREE.Vector3[]): THREE.CurvePath<THREE.Vector3> | null {
  if (points.length < 2) return null;
  const path = new THREE.CurvePath<THREE.Vector3>();
  for (let i = 0; i < points.length - 1; i++) {
    if (points[i].distanceTo(points[i + 1]) < 1e-4) continue;
    path.add(new THREE.LineCurve3(points[i], points[i + 1]));
  }
  return path.curves.length > 0 ? path : null;
}

export interface SegmentPlacement {
  position: THREE.Vector3;
  quaternion: THREE.Quaternion;
  length: number;
}

/**
 * 한 구간을 채울 원기둥의 위치·자세·길이.
 *
 * cylinderGeometry 는 +Y 를 축으로 서 있으므로, +Y 를 구간 방향으로 돌리는
 * 회전을 구한다. 사다리 구간(x·y 고정, z 만 변화)은 three 좌표에서 방향이
 * (0,±1,0) 이라 회전이 항등이 되고 원기둥이 저절로 수직으로 선다.
 */
export function segmentPlacement(a: THREE.Vector3, b: THREE.Vector3): SegmentPlacement {
  const dir = new THREE.Vector3().subVectors(b, a);
  const length = dir.length();
  const quaternion = new THREE.Quaternion();
  if (length > 1e-6) quaternion.setFromUnitVectors(ROUTE_UP, dir.clone().normalize());
  const position = new THREE.Vector3().addVectors(a, b).multiplyScalar(0.5);
  return { position, quaternion, length };
}

/**
 * no_safe_route 를 점선으로 끊는다.
 *
 * 2D 평면도가 같은 상태를 stroke-dasharray 로 그린다. 3D 에서만 실선으로 두면
 * "최소 위험 경로"가 정상 경로와 같은 무게로 읽힌다.
 */
export function dashChunks(
  a: THREE.Vector3,
  b: THREE.Vector3,
  dash = 1.1,
  gap = 0.8,
): [THREE.Vector3, THREE.Vector3][] {
  const total = a.distanceTo(b);
  const chunks: [THREE.Vector3, THREE.Vector3][] = [];
  if (total < 1e-6) return chunks;
  for (let s = 0; s < total; s += dash + gap) {
    const e = Math.min(s + dash, total);
    chunks.push([a.clone().lerp(b, s / total), a.clone().lerp(b, e / total)]);
  }
  return chunks;
}
