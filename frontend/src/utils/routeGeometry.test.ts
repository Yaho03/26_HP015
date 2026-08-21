/// <reference types="node" />
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import * as THREE from "three";
import type { RouteStatus, RouteWaypoint } from "../types/ws";
import {
  dashChunks,
  ROUTE_COLOR_FALLBACK,
  ROUTE_COLOR_VAR,
  ROUTE_LIFT,
  routeCurve,
  routePoints,
  segmentPlacement,
} from "./routeGeometry";

/**
 * 3D 탈출 경로 형상 검증.
 *
 * PR #199 에서 "3D 캔버스 육안 확인"이 미검증으로 남았던 항목이다. 브라우저를
 * 띄울 수 없는 환경에서도 형상이 맞는지는 확인할 수 있어야 한다 — 사다리가
 * 수직으로 서는가, 길이 0 구간이 화살표를 망가뜨리지 않는가, 경로를 산출하지
 * 못했을 때 아무것도 그리지 않는가.
 */

function wp(x_m: number, y_m: number, z_m: number, label?: string): RouteWaypoint {
  return { x_m, y_m, z_m, label } as RouteWaypoint;
}

describe("routePoints", () => {
  it("maps ship-visual Z-up onto three.js Y-up and lifts off the floor", () => {
    const [p] = routePoints([wp(30, 4, 0)]);
    // toThreePosition: [x_m, z_m, -y_m] — 선체 +y(starboard)가 three 의 -z 다.
    expect(p.x).toBeCloseTo(30, 6);
    expect(p.y).toBeCloseTo(0 + ROUTE_LIFT, 6);
    expect(p.z).toBeCloseTo(-4, 6);
  });

  it("keeps the ladder top at its real height instead of flattening it", () => {
    // 출구는 사다리 상단이라 바닥에서 14m 위에 있다. 이걸 0 으로 접으면 3D 에서
    // 경로가 바닥을 기어가고, 작업자가 올라가야 한다는 사실이 사라진다.
    const [, top] = routePoints([wp(58, 0, 0), wp(58, 0, 14)]);
    expect(top.y).toBeCloseTo(14 + ROUTE_LIFT, 6);
  });
});

describe("segmentPlacement", () => {
  it("stands a ladder segment vertically", () => {
    // 사다리는 x·y 가 고정이고 z 만 변한다 → three 에서 방향이 +Y.
    const points = routePoints([wp(58, 0, 0), wp(58, 0, 14)]);
    const placed = segmentPlacement(points[0], points[1]);

    expect(placed.length).toBeCloseTo(14, 6);

    // cylinderGeometry 의 축(+Y)을 이 자세로 돌린 결과가 그대로 +Y 여야 한다.
    const axis = new THREE.Vector3(0, 1, 0).applyQuaternion(placed.quaternion);
    expect(axis.x).toBeCloseTo(0, 6);
    expect(Math.abs(axis.y)).toBeCloseTo(1, 6);
    expect(axis.z).toBeCloseTo(0, 6);
  });

  it("aligns a horizontal walkway segment along the hold length", () => {
    const points = routePoints([wp(10, 0, 0), wp(40, 0, 0)]);
    const placed = segmentPlacement(points[0], points[1]);

    expect(placed.length).toBeCloseTo(30, 6);
    expect(placed.position.x).toBeCloseTo(25, 6);

    const axis = new THREE.Vector3(0, 1, 0).applyQuaternion(placed.quaternion);
    expect(axis.x).toBeCloseTo(1, 6);
    expect(axis.y).toBeCloseTo(0, 6);
  });

  it("reports zero length for a duplicated waypoint so the caller can skip it", () => {
    const points = routePoints([wp(10, 0, 0), wp(10, 0, 0)]);
    expect(segmentPlacement(points[0], points[1]).length).toBeCloseTo(0, 9);
  });
});

describe("routeCurve", () => {
  it("returns null when there is nothing to draw", () => {
    // unavailable 이 정확히 이 상태다 — 산출 실패지 "빈 경로"가 아니다.
    expect(routeCurve([])).toBeNull();
    expect(routeCurve(routePoints([wp(10, 0, 0)]))).toBeNull();
  });

  it("drops zero-length segments so arrow tangents never go NaN", () => {
    // LineCurve3 의 길이가 0 이면 getTangentAt 이 NaN 을 낸다. 화살표가 원점으로
    // 튀거나 사라진다.
    const points = routePoints([wp(10, 0, 0), wp(10, 0, 0), wp(40, 0, 0)]);
    const curve = routeCurve(points);

    expect(curve).not.toBeNull();
    expect(curve!.curves).toHaveLength(1);

    for (const t of [0, 0.25, 0.5, 0.75, 1]) {
      const tangent = curve!.getTangentAt(t);
      expect(Number.isFinite(tangent.x)).toBe(true);
      expect(Number.isFinite(tangent.y)).toBe(true);
      expect(Number.isFinite(tangent.z)).toBe(true);
    }
  });

  it("keeps the ladder leg as its own segment", () => {
    // 평면도에서는 한 점으로 접히지만 3D 에서는 접히면 안 된다 (§7 한계 #2).
    const points = routePoints([wp(10, 0, 0), wp(58, 0, 0), wp(58, 0, 14)]);
    const curve = routeCurve(points);
    expect(curve!.curves).toHaveLength(2);
    expect(curve!.getLength()).toBeCloseTo(48 + 14, 4);
  });
});

describe("dashChunks", () => {
  const a = new THREE.Vector3(0, 0, 0);
  const b = new THREE.Vector3(10, 0, 0);

  it("breaks a segment into gapped pieces", () => {
    const chunks = dashChunks(a, b, 1.1, 0.8);
    expect(chunks.length).toBeGreaterThan(1);
    // 첫 조각은 시작점에서, 마지막 조각은 끝점을 넘지 않는다.
    expect(chunks[0][0].distanceTo(a)).toBeCloseTo(0, 6);
    expect(chunks[chunks.length - 1][1].x).toBeLessThanOrEqual(b.x + 1e-6);
  });

  it("never covers the whole segment — a dashed route must read as broken", () => {
    const chunks = dashChunks(a, b, 1.1, 0.8);
    const drawn = chunks.reduce((sum, [p, q]) => sum + p.distanceTo(q), 0);
    expect(drawn).toBeLessThan(a.distanceTo(b));
  });

  it("returns nothing for a zero-length segment instead of looping forever", () => {
    expect(dashChunks(a, a.clone())).toEqual([]);
  });
});

describe("route colour tokens", () => {
  // vitest 는 CSS import 를 빈 문자열로 스텁하므로 (`?raw` 도 마찬가지) 파일을
  // 직접 읽는다. 값을 테스트에 옮겨 적으면 그 사본이 또 갈라질 뿐이다 —
  // 잠그려는 대상을 원문 그대로 봐야 한다.
  const evacCss = readFileSync(
    fileURLToPath(new URL("../styles/evacuation.css", import.meta.url)),
    "utf-8",
  );

  /** `.evac { --evac-safe: var(--normal); … }` 에서 매핑을 읽어온다. */
  function evacVarTarget(name: string): string | null {
    const m = evacCss.match(new RegExp(`--evac-${name}\\s*:\\s*var\\(\\s*(--[\\w-]+)\\s*\\)`));
    return m ? m[1] : null;
  }

  const PAIRS: [RouteStatus, string][] = [
    ["safe", "safe"],
    ["degraded", "degraded"],
    ["no_safe_route", "blocked"],
    ["unavailable", "unavailable"],
  ];

  it.each(PAIRS)("3D %s uses the same ramp token as the 2D plan", (status, evacName) => {
    // 이 테스트가 잠그는 것: 3D 트윈이 hex 를 따로 들고 있다가 램프 개정을
    // 놓치는 사고. 실제로 한 번 일어났고 네 상태가 전부 갈라졌다.
    expect(ROUTE_COLOR_VAR[status]).toBe(evacVarTarget(evacName));
  });

  it("has a usable fallback for every status", () => {
    for (const status of Object.keys(ROUTE_COLOR_VAR) as RouteStatus[]) {
      expect(ROUTE_COLOR_FALLBACK[status]).toMatch(/^#[0-9a-f]{6}$/);
    }
  });
});
