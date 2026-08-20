// 공간 통행 구조 (nav graph) 타입 — docs/12_EVACUATION_ROUTE_SPEC.md §2.
//
// 경로 메시지 타입(EvacuationRouteMessage)은 types/ws.ts 에 있다. 이 파일은
// **토폴로지** 쪽이다. 둘을 나눈 이유는 전송 경로가 다르기 때문이다 — 경로는
// WebSocket 으로 매번 오고, 토폴로지는 REST(`/api/evacuation/topology`)로 한 번
// 받아 두고 거의 바뀌지 않는다.

import type { NavEdgeKind, RouteStatus, RouteWaypoint } from "./ws";

/** 비계 층. UWB 가 2D 라 작업자가 어느 층에 있는지는 측정되지 않는다 (§7 한계 #2). */
export interface NavLevel {
  level_id: string;
  name: string;
  height_m: number;
}

export type NavNodeKind =
  | "floor"
  | "scaffold_deck"
  | "ladder_top"
  | "ladder_bottom"
  | "exit";

export interface NavNode {
  nav_node_id: string;
  kind: NavNodeKind;
  x_m: number;
  y_m: number;
  z_m: number;
  level_id: string;
  label: string;
}

export interface NavEdge {
  edge_id: string;
  from_node_id: string;
  to_node_id: string;
  kind: NavEdgeKind;
  /**
   * 실제 이동 거리. 좌표 직선거리와 다를 수 있다 — 우회 통로는 두 끝점이
   * 가까워도 실제로는 돌아가야 한다. 화면은 좌표로 그리고 비용은 이 값으로
   * 계산하므로, 둘이 어긋나는 것은 정상이다.
   */
  length_m: number;
  traverse_factor: number;
  bidirectional: boolean;
  width_m: number | null;
  is_usable: boolean;
}

export type EvacuationExitKind = "manhole" | "hatch" | "ladder_out";

export interface EvacuationExit {
  exit_id: string;
  nav_node_id: string;
  kind: EvacuationExitKind;
  x_m: number;
  y_m: number;
  z_m: number;
  is_usable: boolean;
  /** 비용이 같을 때 선호 순위. 낮을수록 우선. */
  priority: number;
  label: string;
}

export interface NavTopology {
  version: number;
  /** 항상 "ship-visual". FILL 프리셋 좌표는 여기 들어오지 않는다 (ADR-010). */
  coordinate_system: "ship-visual";
  /** 실측 도면 미반영 여부. 가정값이면 화면이 그 사실을 숨기지 않는다 (OQ-V5). */
  is_provisional: boolean;
  levels: NavLevel[];
  nav_nodes: NavNode[];
  nav_edges: NavEdge[];
  exits: EvacuationExit[];
}

/**
 * 3D/2D 렌더러에 넘기는 경로 최소 형태.
 *
 * 전체 메시지를 넘기지 않는 이유: 렌더러는 좌표와 상태만 알면 되고, 그래야
 * 목 데이터와 실제 WebSocket 메시지를 같은 컴포넌트에 꽂을 수 있다.
 */
export interface RouteOverlay {
  route_status: RouteStatus;
  waypoints: RouteWaypoint[];
  target_exit_id?: string | null;
}
