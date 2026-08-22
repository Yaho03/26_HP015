import { useMemo } from "react";
import type { NavTopology } from "../types/evacuation";
import type { BlockedExit, RouteStatus, RouteWaypoint } from "../types/ws";
import { SHIP_FLOOR_HALF_WIDTH_M, SHIP_SPACE, shipFloorHalfWidthAt } from "../utils/coordinates";
import "../styles/evacuation.css";

/**
 * 2D 탈출 경로 평면도.
 *
 * FR-401 리팩터링에서 SpacePlan.tsx 가 제거되고 모니터링 화면 ①은 3D 트윈을
 * 사선 탑뷰로 크롭해 쓰게 됐다. 그 칸은 **FILL 프리셋**이라 축마다 배율이 달라
 * (x 24배 / y 6.5배) 경로 형상이 왜곡된다 — §2.4 가 그 화면에 경로를 그리는 것을
 * 금지하는 이유다.
 *
 * 그래서 경로 전용 평면도를 따로 둔다. 이 컴포넌트는 ship-visual 좌표를 **그대로**
 * 쓴다. 경로 메시지가 이미 ship-visual(TRUE SCALE 균일 배율)로 오므로 추가 비율
 * 매핑이 없다 (ADR-010). 좌표 변환을 여기서 새로 만들지 않는 것이 요점이다.
 */

const PLAN_PAD_X = 3;
const PLAN_PAD_Y = 2.4;
const OUTLINE_STEPS = 48;

const VIEW_W = SHIP_SPACE.length_m + PLAN_PAD_X * 2;
/** 바닥 반폭 양쪽 + 여백. 아래쪽은 출구 라벨이 들어가므로 조금 더 준다. */
const VIEW_H = SHIP_FLOOR_HALF_WIDTH_M * 2 + PLAN_PAD_Y * 2 + 2.2;

/** ship-visual y → SVG y. +y(starboard)가 화면 위로 가도록 뒤집는다. */
function sy(y_m: number): number {
  return -y_m;
}

/**
 * 테이퍼를 따라간 바닥 외곽선. 화물창은 직육면체가 아니다.
 *
 * 선체 형상은 상수이므로 모듈 로드 때 한 번만 만든다 — 렌더마다 48구간을 다시
 * 도는 것은 낭비다.
 */
function floorOutline(): string {
  const top: string[] = [];
  const bottom: string[] = [];
  for (let i = 0; i <= OUTLINE_STEPS; i++) {
    const x = (SHIP_SPACE.length_m * i) / OUTLINE_STEPS;
    const half = shipFloorHalfWidthAt(x);
    top.push(`${x.toFixed(2)},${sy(half).toFixed(2)}`);
    bottom.push(`${x.toFixed(2)},${sy(-half).toFixed(2)}`);
  }
  return `M${top.join(" L")} L${bottom.reverse().join(" L")} Z`;
}

const FLOOR_OUTLINE = floorOutline();

interface Pt {
  x: number;
  y: number;
}

/**
 * waypoint 를 평면 점열로 투영한다.
 *
 * 사다리 구간은 x·y 가 같고 z 만 변하므로 평면에서는 **길이 0 인 선분**이 된다.
 * 그대로 두면 polyline 에 중복점이 남아 선 끝이 뭉툭해지므로 접어서 없애고,
 * 수직 이동은 출구 아이콘이 대신 표현한다 (3D 트윈에서는 실제로 세로로 선다).
 */
function projectRoute(waypoints: RouteWaypoint[]): Pt[] {
  const out: Pt[] = [];
  for (const wp of waypoints) {
    const pt = { x: wp.x_m, y: wp.y_m };
    const prev = out[out.length - 1];
    if (prev && Math.abs(prev.x - pt.x) < 1e-6 && Math.abs(prev.y - pt.y) < 1e-6) continue;
    out.push(pt);
  }
  return out;
}

/** 진행 방향 표시. 선분 중점에 놓는 갈매기표. */
function chevrons(points: Pt[]): { x: number; y: number; angle: number }[] {
  const marks: { x: number; y: number; angle: number }[] = [];
  for (let i = 0; i < points.length - 1; i++) {
    const a = points[i];
    const b = points[i + 1];
    const dx = b.x - a.x;
    const dy = sy(b.y) - sy(a.y);
    const len = Math.hypot(dx, dy);
    // 짧은 선분에 화살표를 얹으면 선이 화살표에 먹힌다.
    if (len < 4) continue;
    marks.push({
      x: (a.x + b.x) / 2,
      y: (sy(a.y) + sy(b.y)) / 2,
      angle: (Math.atan2(dy, dx) * 180) / Math.PI,
    });
  }
  return marks;
}

interface EvacuationPlanProps {
  topology: NavTopology;
  waypoints: RouteWaypoint[];
  route_status: RouteStatus;
  target_exit_id?: string | null;
  blocked_exits?: BlockedExit[];
}

export function EvacuationPlan({
  topology,
  waypoints,
  route_status,
  target_exit_id,
  blocked_exits = [],
}: EvacuationPlanProps) {
  const nodeById = useMemo(
    () => new Map(topology.nav_nodes.map((n) => [n.nav_node_id, n])),
    [topology.nav_nodes],
  );
  const points = useMemo(() => projectRoute(waypoints), [waypoints]);
  const marks = useMemo(() => chevrons(points), [points]);
  const blockedIds = useMemo(
    () => new Map(blocked_exits.map((b) => [b.exit_id, b.reason])),
    [blocked_exits],
  );

  // unavailable 은 경로 자체를 산출하지 못한 상태다. 이때만 선을 그리지 않는다.
  const showRoute = route_status !== "unavailable" && points.length >= 2;
  const worker = points[0] ?? null;

  return (
    <div className="evac-plan">
      <svg
        className="evac-plan__svg"
        viewBox={`${-PLAN_PAD_X} ${-SHIP_FLOOR_HALF_WIDTH_M - PLAN_PAD_Y} ${VIEW_W} ${VIEW_H}`}
        role="img"
        aria-label={`탈출 경로 평면도 — 상태 ${route_status}`}
      >
        <path className="evac-plan__hull" d={FLOOR_OUTLINE} />

        {/* nav graph. 경로가 없는 구간도 보여야 "왜 저리로 돌아가나"가 읽힌다. */}
        {topology.nav_edges.map((edge) => {
          const a = nodeById.get(edge.from_node_id);
          const b = nodeById.get(edge.to_node_id);
          if (!a || !b) return null;
          const cls =
            "evac-plan__edge" +
            (edge.kind === "ladder" ? " evac-plan__edge--ladder" : "") +
            (edge.is_usable ? "" : " evac-plan__edge--unusable");
          return (
            <line
              key={edge.edge_id}
              className={cls}
              x1={a.x_m}
              y1={sy(a.y_m)}
              x2={b.x_m}
              y2={sy(b.y_m)}
            />
          );
        })}

        {topology.nav_nodes
          // 사다리 하단은 출구와 같은 x/y에 놓인다. 이름까지 함께 그리면
          // 출구 라벨·차단 X와 포개져 정작 대피 지점 이름을 읽을 수 없다.
          .filter((n) => n.kind !== "exit" && n.kind !== "ladder_bottom")
          .map((n) => (
            <g key={n.nav_node_id}>
              <circle className="evac-plan__node" cx={n.x_m} cy={sy(n.y_m)} r={0.32} />
              <text className="evac-plan__node-label" x={n.x_m} y={sy(n.y_m) - 1.65} textAnchor="middle">
                {n.label}
              </text>
            </g>
          ))}

        {/* 경로. nav graph 위에 그려야 가려지지 않는다. */}
        {showRoute && (
          <>
            <polyline
              className={`evac-plan__route evac-plan__route--${route_status}`}
              points={points.map((p) => `${p.x},${sy(p.y)}`).join(" ")}
            />
            {marks.map((m, i) => (
              <path
                key={i}
                className={`evac-plan__route evac-plan__route--${route_status}`}
                d="M -0.9 -0.75 L 0.15 0 L -0.9 0.75"
                transform={`translate(${m.x} ${m.y}) rotate(${m.angle})`}
              />
            ))}
          </>
        )}

        {/* 출구. 차단된 곳은 X 로 덮는다 — 색만으로 구분하지 않는다. */}
        {topology.exits.map((exit) => {
          const blocked = blockedIds.has(exit.exit_id) || !exit.is_usable;
          const isTarget = exit.exit_id === target_exit_id;
          const cls =
            "evac-plan__exit " +
            (blocked
              ? "evac-plan__exit--blocked"
              : isTarget
                ? "evac-plan__exit--target"
                : "evac-plan__exit--open");
          const cx = exit.x_m;
          const cy = sy(exit.y_m);
          // 긴 출구명이 도면 밖으로 잘리지 않도록 선수/선미 쪽으로 붙인다.
          const labelOnLeft = cx < SHIP_SPACE.length_m / 2;
          const labelX = labelOnLeft ? Math.max(0, cx - 1.15) : Math.min(SHIP_SPACE.length_m, cx + 1.15);
          return (
            <g key={exit.exit_id}>
              <circle className={cls} cx={cx} cy={cy} r={1.15} />
              {isTarget && !blocked && <circle className={cls} cx={cx} cy={cy} r={1.75} />}
              {blocked && (
                <>
                  <line className="evac-plan__exit-cross" x1={cx - 1.0} y1={cy - 1.0} x2={cx + 1.0} y2={cy + 1.0} />
                  <line className="evac-plan__exit-cross" x1={cx + 1.0} y1={cy - 1.0} x2={cx - 1.0} y2={cy + 1.0} />
                </>
              )}
              <text
                className="evac-plan__exit-label"
                x={labelX}
                y={cy + 3.1}
                textAnchor={labelOnLeft ? "start" : "end"}
              >
                {exit.label}
              </text>
            </g>
          );
        })}

        {worker && (
          <circle className="evac-plan__worker" cx={worker.x} cy={sy(worker.y)} r={0.75} />
        )}
      </svg>

      <div className="evac-plan__legend">
        <span style={{ color: "var(--evac-safe)" }}>
          <i /> 안전
        </span>
        <span style={{ color: "var(--evac-degraded)" }}>
          <i /> 위험구역 통과
        </span>
        <span style={{ color: "var(--evac-blocked)" }}>
          <i /> 최소 위험 (안전경로 없음)
        </span>
        <span>사다리 구간은 평면에서 한 점으로 겹친다 — 수직 이동은 3D 트윈에서 확인</span>
      </div>
    </div>
  );
}
