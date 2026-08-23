// 탈출 경로 목 데이터 — 백엔드 없이 UI 를 완성하고 시연 리허설을 돌리기 위한 것.
//
// 이 파일은 백엔드가 붙은 뒤에도 **남긴다** (B4). 목 모드가 있어야 DB·MQTT 없이
// 화면만 확인할 수 있고, 시연 직전에 백엔드가 죽어도 UI 리허설이 계속된다.
//
// 좌표는 docs/12_EVACUATION_ROUTE_SPEC.md §2.5 골격을 그대로 옮긴 것이다.
// **실측 도면 미반영 가정값이다** (OQ-V5). 실측이 들어오면 이 파일이 아니라
// config/space_topology.yaml 이 소스가 된다.

import type { EvacuationRouteMessage } from "../types/ws";
import type { NavTopology } from "../types/evacuation";

// ─────────────────────────────────────────────────────────────────────────────
// nav graph (§2.5)
// ─────────────────────────────────────────────────────────────────────────────

/**
 * 전방·후방 접근 트렁크 2개 + 우현 우회로 1개 + 사다리 2개.
 *
 * 셋이 각각 다른 것을 보여준다 — 출구 2개는 경로 **선택**을, 우회로는 가스
 * **회피**를, 사다리는 traverse_factor 2.5 가 비용에 실리는 것을 드러낸다.
 * 출구가 하나뿐이면 이 기능의 핵심이 화면에 전혀 나타나지 않는다 (§2.3).
 */
// 실측 데모 구역 노드/엣지 (이슈 #225) — config/space_topology.yaml 과 동일 값을
// 유지한다 (backend/tests/test_topology_mock_sync.py 가 어긋나면 실패한다).
const ZONE_NODES: NavTopology["nav_nodes"] = [
  {
    nav_node_id: "nav.zone.fwd.port",
    kind: "floor",
    x_m: 24.0,
    y_m: -3.75,
    z_m: 0.0,
    level_id: "L0",
    label: "실측 구역 전방 좌현",
  },
  {
    nav_node_id: "nav.zone.fwd.stbd",
    kind: "floor",
    x_m: 24.0,
    y_m: 3.75,
    z_m: 0.0,
    level_id: "L0",
    label: "실측 구역 전방 우현",
  },
  {
    nav_node_id: "nav.zone.mid.port",
    kind: "floor",
    x_m: 30.0,
    y_m: -3.75,
    z_m: 0.0,
    level_id: "L0",
    label: "실측 구역 중앙 좌현",
  },
  {
    nav_node_id: "nav.zone.mid.stbd",
    kind: "floor",
    x_m: 30.0,
    y_m: 3.75,
    z_m: 0.0,
    level_id: "L0",
    label: "실측 구역 중앙 우현",
  },
  {
    nav_node_id: "nav.zone.aft.port",
    kind: "floor",
    x_m: 36.0,
    y_m: -3.75,
    z_m: 0.0,
    level_id: "L0",
    label: "실측 구역 후방 좌현",
  },
  {
    nav_node_id: "nav.zone.aft.stbd",
    kind: "floor",
    x_m: 36.0,
    y_m: 3.75,
    z_m: 0.0,
    level_id: "L0",
    label: "실측 구역 후방 우현",
  },
];

const ZONE_EDGES: NavTopology["nav_edges"] = [
  {
    edge_id: "e009",
    from_node_id: "nav.zone.fwd.port",
    to_node_id: "nav.zone.mid.port",
    kind: "walk",
    length_m: 6.0,
    traverse_factor: 1.0,
    bidirectional: true,
    width_m: 1.0,
    is_usable: true,
  },
  {
    edge_id: "e010",
    from_node_id: "nav.zone.fwd.stbd",
    to_node_id: "nav.zone.mid.stbd",
    kind: "walk",
    length_m: 6.0,
    traverse_factor: 1.0,
    bidirectional: true,
    width_m: 1.0,
    is_usable: true,
  },
  {
    edge_id: "e011",
    from_node_id: "nav.zone.mid.port",
    to_node_id: "nav.zone.aft.port",
    kind: "walk",
    length_m: 6.0,
    traverse_factor: 1.0,
    bidirectional: true,
    width_m: 1.0,
    is_usable: true,
  },
  {
    edge_id: "e012",
    from_node_id: "nav.zone.mid.stbd",
    to_node_id: "nav.zone.aft.stbd",
    kind: "walk",
    length_m: 6.0,
    traverse_factor: 1.0,
    bidirectional: true,
    width_m: 1.0,
    is_usable: true,
  },
  {
    edge_id: "e013",
    from_node_id: "nav.zone.mid.port",
    to_node_id: "nav.floor.mid",
    kind: "walk",
    length_m: 3.75,
    traverse_factor: 1.0,
    bidirectional: true,
    width_m: 1.0,
    is_usable: true,
  },
  {
    edge_id: "e014",
    from_node_id: "nav.zone.mid.stbd",
    to_node_id: "nav.floor.mid",
    kind: "walk",
    length_m: 3.75,
    traverse_factor: 1.0,
    bidirectional: true,
    width_m: 1.0,
    is_usable: true,
  },
  {
    edge_id: "e015",
    from_node_id: "nav.zone.fwd.port",
    to_node_id: "nav.zone.fwd.stbd",
    kind: "walk",
    length_m: 7.5,
    traverse_factor: 1.0,
    bidirectional: true,
    width_m: 1.0,
    is_usable: true,
  },
  {
    edge_id: "e016",
    from_node_id: "nav.zone.aft.port",
    to_node_id: "nav.zone.aft.stbd",
    kind: "walk",
    length_m: 7.5,
    traverse_factor: 1.0,
    bidirectional: true,
    width_m: 1.0,
    is_usable: true,
  },
];

export const MOCK_TOPOLOGY: NavTopology = {
  version: 1,
  coordinate_system: "ship-visual",
  is_provisional: true,
  levels: [
    { level_id: "L0", name: "화물창 바닥", height_m: 0.0 },
    { level_id: "L1", name: "1단 비계", height_m: 3.5 },
  ],
  nav_nodes: [
    // 바닥 통로 (선수 → 선미)
    {
      nav_node_id: "nav.floor.fwd",
      kind: "floor",
      x_m: 4.0,
      y_m: 0.0,
      z_m: 0.0,
      level_id: "L0",
      label: "선수 바닥",
    },
    {
      nav_node_id: "nav.floor.mid",
      kind: "floor",
      x_m: 30.0,
      y_m: 0.0,
      z_m: 0.0,
      level_id: "L0",
      label: "중앙 통로",
    },
    {
      nav_node_id: "nav.floor.aft",
      kind: "floor",
      x_m: 56.0,
      y_m: 0.0,
      z_m: 0.0,
      level_id: "L0",
      label: "선미 바닥",
    },
    // 우현측 우회 통로 — 이게 있어야 가스 회피가 눈에 보인다
    {
      nav_node_id: "nav.floor.stbd",
      kind: "floor",
      x_m: 30.0,
      y_m: 5.0,
      z_m: 0.0,
      level_id: "L0",
      label: "우현 우회로",
    },
    // 전방 접근 트렁크
    {
      nav_node_id: "nav.ladder.fwd.bottom",
      kind: "ladder_bottom",
      x_m: 2.0,
      y_m: 0.0,
      z_m: 0.0,
      level_id: "L0",
      label: "전방 트렁크 하단",
    },
    {
      nav_node_id: "nav.exit.trunk-fwd",
      kind: "exit",
      x_m: 2.0,
      y_m: 0.0,
      z_m: 14.0,
      level_id: "L1",
      label: "전방 접근 트렁크",
    },
    // 후방 접근 트렁크
    {
      nav_node_id: "nav.ladder.aft.bottom",
      kind: "ladder_bottom",
      x_m: 58.0,
      y_m: 0.0,
      z_m: 0.0,
      level_id: "L0",
      label: "후방 트렁크 하단",
    },
    {
      nav_node_id: "nav.exit.trunk-aft",
      kind: "exit",
      x_m: 58.0,
      y_m: 0.0,
      z_m: 14.0,
      level_id: "L1",
      label: "후방 접근 트렁크",
    },
    // 실측 데모 구역 (이슈 #225) — UWB 실측 공간(2.5x2.0m)이 균일 배율 6.5로
    // 매핑되는 스트립(x 21.875~38.125, y ±6.5)을 덮는다. config/space_topology.yaml
    // 의 주석과 같은 유도 — 실물 UWB 위치 어디서든 스냅이 성공해야 한다.
    ...ZONE_NODES,
  ],
  nav_edges: [
    {
      edge_id: "e001",
      from_node_id: "nav.floor.fwd",
      to_node_id: "nav.floor.mid",
      kind: "walk",
      length_m: 26.0,
      traverse_factor: 1.0,
      bidirectional: true,
      width_m: 1.2,
      is_usable: true,
    },
    {
      edge_id: "e002",
      from_node_id: "nav.floor.mid",
      to_node_id: "nav.floor.aft",
      kind: "walk",
      length_m: 26.0,
      traverse_factor: 1.0,
      bidirectional: true,
      width_m: 1.2,
      is_usable: true,
    },
    {
      edge_id: "e003",
      from_node_id: "nav.floor.fwd",
      to_node_id: "nav.floor.stbd",
      kind: "walk",
      length_m: 26.5,
      traverse_factor: 1.0,
      bidirectional: true,
      width_m: 0.9,
      is_usable: true,
    },
    {
      edge_id: "e004",
      from_node_id: "nav.floor.stbd",
      to_node_id: "nav.floor.aft",
      kind: "walk",
      length_m: 26.5,
      traverse_factor: 1.0,
      bidirectional: true,
      width_m: 0.9,
      is_usable: true,
    },
    {
      edge_id: "e005",
      from_node_id: "nav.floor.fwd",
      to_node_id: "nav.ladder.fwd.bottom",
      kind: "walk",
      length_m: 2.0,
      traverse_factor: 1.0,
      bidirectional: true,
      width_m: 0.8,
      is_usable: true,
    },
    {
      edge_id: "e006",
      from_node_id: "nav.ladder.fwd.bottom",
      to_node_id: "nav.exit.trunk-fwd",
      kind: "ladder",
      length_m: 14.0,
      traverse_factor: 2.5,
      bidirectional: true,
      width_m: 0.6,
      is_usable: true,
    },
    {
      edge_id: "e007",
      from_node_id: "nav.floor.aft",
      to_node_id: "nav.ladder.aft.bottom",
      kind: "walk",
      length_m: 2.0,
      traverse_factor: 1.0,
      bidirectional: true,
      width_m: 0.8,
      is_usable: true,
    },
    {
      edge_id: "e008",
      from_node_id: "nav.ladder.aft.bottom",
      to_node_id: "nav.exit.trunk-aft",
      kind: "ladder",
      length_m: 14.0,
      traverse_factor: 2.5,
      bidirectional: true,
      width_m: 0.6,
      is_usable: true,
    },
    ...ZONE_EDGES,
  ],
  exits: [
    {
      exit_id: "trunk-fwd",
      nav_node_id: "nav.exit.trunk-fwd",
      kind: "ladder_out",
      x_m: 2.0,
      y_m: 0.0,
      z_m: 14.0,
      is_usable: true,
      priority: 1,
      label: "전방 접근 트렁크",
    },
    {
      exit_id: "trunk-aft",
      nav_node_id: "nav.exit.trunk-aft",
      kind: "ladder_out",
      x_m: 58.0,
      y_m: 0.0,
      z_m: 14.0,
      is_usable: true,
      priority: 2,
      label: "후방 접근 트렁크",
    },
  ],
};

// ─────────────────────────────────────────────────────────────────────────────
// 경로 목 데이터 — route_status 4가지 (§3.5)
// ─────────────────────────────────────────────────────────────────────────────

const NODE_ID = "wearable-01";
const WORKER = { worker_id: 7, worker_name: "김철수" };

/**
 * 무하자 경로. 중앙 통로 → 전방 트렁크.
 *
 * 비용 = 26×1.0 + 2×1.0 + 14×2.5 = 63.0. 후방 트렁크도 정확히 63.0 이라 중앙에서
 * 두 출구는 **동점**이고, priority 1 인 전방이 선택된다. 이 동점은 의도된 것으로,
 * 경로 깜빡임 히스테리시스(§3.4, EXP-8.3)를 시험할 지점이 여기다.
 */
export const MOCK_ROUTE_SAFE: EvacuationRouteMessage = {
  type: "evacuation_route",
  route_id: "01J6X3R8K7VQ2NTP5Z9MA4HWBC",
  node_id: NODE_ID,
  ...WORKER,
  computed_at: "2026-08-21T03:00:00.120Z",
  route_status: "safe",
  coordinate_system: "ship-visual",
  assumed_level_id: "L0",
  target_exit_id: "trunk-fwd",
  entry_nav_node_id: "nav.floor.mid",
  snap_distance_m: 0.85,
  total_length_m: 42.0,
  total_cost: 63.0,
  // Σ(length_m × traverse_factor) / walk_speed_mps = 63.0 / 0.8
  estimated_seconds: 79,
  hazard_multiplier_max: 1.0,
  switch_reason: "initial",
  waypoints: [
    {
      seq: 0,
      nav_node_id: null,
      x_m: 29.4,
      y_m: 0.6,
      z_m: 0.0,
      level_id: "L0",
      edge_kind_to_next: "walk",
      label: "현재 위치",
    },
    {
      seq: 1,
      nav_node_id: "nav.floor.mid",
      x_m: 30.0,
      y_m: 0.0,
      z_m: 0.0,
      level_id: "L0",
      edge_kind_to_next: "walk",
      label: "중앙 통로",
    },
    {
      seq: 2,
      nav_node_id: "nav.floor.fwd",
      x_m: 4.0,
      y_m: 0.0,
      z_m: 0.0,
      level_id: "L0",
      edge_kind_to_next: "walk",
      label: "선수 바닥",
    },
    {
      seq: 3,
      nav_node_id: "nav.ladder.fwd.bottom",
      x_m: 2.0,
      y_m: 0.0,
      z_m: 0.0,
      level_id: "L0",
      edge_kind_to_next: "ladder",
      label: "전방 트렁크 하단",
    },
    {
      seq: 4,
      nav_node_id: "nav.exit.trunk-fwd",
      x_m: 2.0,
      y_m: 0.0,
      z_m: 14.0,
      level_id: "L1",
      edge_kind_to_next: null,
      label: "전방 접근 트렁크",
    },
  ],
  blocked_exits: [],
  warnings: [],
};

/**
 * 우회 경로. 후방 트렁크가 level3 로 막혀 우현 우회로로 돌아 전방으로 나간다.
 *
 * 이 기능의 핵심을 한 화면에 담은 케이스다 — 가장 가까운 출구(후방, 37.0)가
 * 차단되어 90.0 짜리 우회로를 택한다. 우회로가 level1 구역을 스치므로 상태는
 * safe 가 아니라 degraded 다.
 *
 * 비용 = 26.5×1.5 + 26.5 + 2 + 14×2.5 = 103.25
 */
export const MOCK_ROUTE_DEGRADED: EvacuationRouteMessage = {
  type: "evacuation_route",
  route_id: "01J6X3R8K7VQ2NTP5Z9MA4HWBD",
  node_id: NODE_ID,
  ...WORKER,
  computed_at: "2026-08-21T03:04:12.880Z",
  route_status: "degraded",
  coordinate_system: "ship-visual",
  assumed_level_id: "L0",
  target_exit_id: "trunk-fwd",
  entry_nav_node_id: "nav.floor.aft",
  snap_distance_m: 2.16,
  total_length_m: 69.0,
  total_cost: 103.25,
  // 위험 가중은 소요 시간에 넣지 않는다. 가스가 짙다고 사람이 느려지는 게 아니다.
  // (26.5 + 26.5 + 2.0 + 35.0) / 0.8
  estimated_seconds: 113,
  hazard_multiplier_max: 1.5,
  switch_reason: "hazard_changed",
  waypoints: [
    {
      seq: 0,
      nav_node_id: null,
      x_m: 54.0,
      y_m: 0.8,
      z_m: 0.0,
      level_id: "L0",
      edge_kind_to_next: "walk",
      label: "현재 위치",
    },
    {
      seq: 1,
      nav_node_id: "nav.floor.aft",
      x_m: 56.0,
      y_m: 0.0,
      z_m: 0.0,
      level_id: "L0",
      edge_kind_to_next: "walk",
      label: "선미 바닥",
    },
    {
      seq: 2,
      nav_node_id: "nav.floor.stbd",
      x_m: 30.0,
      y_m: 5.0,
      z_m: 0.0,
      level_id: "L0",
      edge_kind_to_next: "walk",
      label: "우현 우회로",
    },
    {
      seq: 3,
      nav_node_id: "nav.floor.fwd",
      x_m: 4.0,
      y_m: 0.0,
      z_m: 0.0,
      level_id: "L0",
      edge_kind_to_next: "walk",
      label: "선수 바닥",
    },
    {
      seq: 4,
      nav_node_id: "nav.ladder.fwd.bottom",
      x_m: 2.0,
      y_m: 0.0,
      z_m: 0.0,
      level_id: "L0",
      edge_kind_to_next: "ladder",
      label: "전방 트렁크 하단",
    },
    {
      seq: 5,
      nav_node_id: "nav.exit.trunk-fwd",
      x_m: 2.0,
      y_m: 0.0,
      z_m: 14.0,
      level_id: "L1",
      edge_kind_to_next: null,
      label: "전방 접근 트렁크",
    },
  ],
  blocked_exits: [{ exit_id: "trunk-aft", reason: "hazard_level3" }],
  warnings: ["passes_hazard_level1"],
};

/**
 * 안전 경로 없음.
 *
 * **경로가 사라지지 않는다.** 두 출구가 모두 level3 구역 뒤에 있을 때 BLOCKED 를
 * 50.0 으로 완화해 재계산한 "최소 위험 경로"를 빨강 점선으로 계속 제시한다.
 * 대피 중인 사람에게 빈 화면을 주는 것이 최악의 설계라서다 (§3.5).
 *
 * 비용 = 26×50 + 2 + 35 = 1337.0 — 완화된 BLOCKED 가 그대로 드러난 값이다.
 */
export const MOCK_ROUTE_NO_SAFE: EvacuationRouteMessage = {
  type: "evacuation_route",
  route_id: "01J6X3R8K7VQ2NTP5Z9MA4HWBE",
  node_id: NODE_ID,
  ...WORKER,
  computed_at: "2026-08-21T03:07:45.010Z",
  route_status: "no_safe_route",
  coordinate_system: "ship-visual",
  assumed_level_id: "L0",
  target_exit_id: "trunk-fwd",
  entry_nav_node_id: "nav.floor.mid",
  snap_distance_m: 0.5,
  total_length_m: 42.0,
  total_cost: 1337.0,
  estimated_seconds: 79,
  hazard_multiplier_max: 50.0,
  switch_reason: "route_blocked",
  waypoints: [
    {
      seq: 0,
      nav_node_id: null,
      x_m: 30.2,
      y_m: 0.45,
      z_m: 0.0,
      level_id: "L0",
      edge_kind_to_next: "walk",
      label: "현재 위치",
    },
    {
      seq: 1,
      nav_node_id: "nav.floor.mid",
      x_m: 30.0,
      y_m: 0.0,
      z_m: 0.0,
      level_id: "L0",
      edge_kind_to_next: "walk",
      label: "중앙 통로",
    },
    {
      seq: 2,
      nav_node_id: "nav.floor.fwd",
      x_m: 4.0,
      y_m: 0.0,
      z_m: 0.0,
      level_id: "L0",
      edge_kind_to_next: "walk",
      label: "선수 바닥",
    },
    {
      seq: 3,
      nav_node_id: "nav.ladder.fwd.bottom",
      x_m: 2.0,
      y_m: 0.0,
      z_m: 0.0,
      level_id: "L0",
      edge_kind_to_next: "ladder",
      label: "전방 트렁크 하단",
    },
    {
      seq: 4,
      nav_node_id: "nav.exit.trunk-fwd",
      x_m: 2.0,
      y_m: 0.0,
      z_m: 14.0,
      level_id: "L1",
      edge_kind_to_next: null,
      label: "전방 접근 트렁크",
    },
  ],
  blocked_exits: [
    { exit_id: "trunk-fwd", reason: "hazard_level3" },
    { exit_id: "trunk-aft", reason: "hazard_level3" },
  ],
  warnings: ["passes_hazard_level3"],
};

/**
 * 산출 불가. UWB 위치가 10초 넘게 갱신되지 않은 상태 (§6.1).
 *
 * waypoints 가 빈 배열인 유일한 케이스다. 이때만 경로를 그리지 않는다 —
 * 나머지 세 상태는 어떤 형태로든 선이 남는다.
 */
export const MOCK_ROUTE_UNAVAILABLE: EvacuationRouteMessage = {
  type: "evacuation_route",
  route_id: "01J6X3R8K7VQ2NTP5Z9MA4HWBF",
  node_id: NODE_ID,
  ...WORKER,
  computed_at: "2026-08-21T03:09:02.400Z",
  route_status: "unavailable",
  unavailable_reason: "stale_position",
  coordinate_system: "ship-visual",
  assumed_level_id: "L0",
  target_exit_id: null,
  entry_nav_node_id: null,
  snap_distance_m: null,
  total_length_m: null,
  total_cost: null,
  estimated_seconds: null,
  hazard_multiplier_max: null,
  switch_reason: null,
  waypoints: [],
  blocked_exits: [],
  warnings: ["low_position_quality"],
};

export type MockRouteKey = "safe" | "degraded" | "no_safe_route" | "unavailable";

export const MOCK_ROUTES: Record<MockRouteKey, EvacuationRouteMessage> = {
  safe: MOCK_ROUTE_SAFE,
  degraded: MOCK_ROUTE_DEGRADED,
  no_safe_route: MOCK_ROUTE_NO_SAFE,
  unavailable: MOCK_ROUTE_UNAVAILABLE,
};

export const MOCK_ROUTE_LABELS: Record<MockRouteKey, string> = {
  safe: "정상",
  degraded: "우회",
  no_safe_route: "안전경로 없음",
  unavailable: "산출 불가",
};
