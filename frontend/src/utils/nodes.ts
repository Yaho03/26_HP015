import type { SensorNodeState } from "../types";

/**
 * `sensor-01` → `S1`. 관제 화면은 원거리에서 훑는 용도라 긴 노드 id 를 그대로
 * 쓰면 스캔이 안 된다. 규칙에 맞지 않는 id 는 원문을 그대로 돌려준다 —
 * 알 수 없는 노드를 임의로 줄여 표시하면 실제 id 와 대조가 안 된다.
 */
export function shortNodeLabel(nodeId: string): string {
  const m = /^sensor-0*(\d+)$/.exec(nodeId);
  if (m) return `S${m[1]}`;
  if (/^wearable-0*\d+$/.test(nodeId)) return "웨어러블";
  return nodeId;
}

/**
 * 데이터 출처 배지 문구. 노드가 없으면 아직 아무것도 안 온 상태다.
 *
 * 값이 멈췄으면 LIVE 라고 말하지 않는다. 흐리게 처리하는 것만으로는 부족하다 —
 * 흐린 "LIVE" 도 여전히 LIVE 로 읽히고, 옆의 STALE 배지와 정면으로 모순된다.
 */
export function sourceBadge(
  sourceMode: "live" | "simulation" | undefined,
  hasNode: boolean,
  stale = false,
): "LIVE" | "SIM" | "대기" | "지연" {
  if (!hasNode) return "대기";
  if (stale) return "지연";
  return sourceMode === "simulation" ? "SIM" : "LIVE";
}

/**
 * 이 노드에서 마지막으로 값을 본 시각.
 *
 * `last_seen_at` 은 실시간 메시지(sensor_reading·node_status)에서만 채워진다.
 * 스냅숏으로 복원된 직후에는 비어 있어서, 새로고침한 관제 화면이 값을 띄운 채
 * 신선도만 "—" 로 남는다 — 그 사이엔 STALE 판정이 아예 돌지 않는다.
 *
 * 각 측정값이 들고 있는 `sampled_at` 이 이미 그 답을 갖고 있으므로, 그중
 * 가장 최근 것으로 메운다. 없는 정보를 만들어내는 게 아니라 있는 정보를 쓰는 것이다.
 */
export function nodeLastSeenAt(node: SensorNodeState | null | undefined): string | null {
  if (!node) return null;
  if (node.last_seen_at) return node.last_seen_at;

  let newest: string | null = null;
  for (const reading of Object.values(node.readings)) {
    if (!reading) continue;
    if (newest === null || reading.sampled_at > newest) newest = reading.sampled_at;
  }
  return newest;
}
