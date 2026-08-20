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

/** 데이터 출처 배지 문구. 노드가 없으면 아직 아무것도 안 온 상태다. */
export function sourceBadge(
  sourceMode: "live" | "simulation" | undefined,
  hasNode: boolean,
): "LIVE" | "SIM" | "대기" {
  if (!hasNode) return "대기";
  return sourceMode === "simulation" ? "SIM" : "LIVE";
}
