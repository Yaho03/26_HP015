// Screen 1 ② 위험 상세 ↔ ③ 센서 요약의 연동 규칙.
//
// 두 칸은 하나의 세로 공간을 나눠 쓰는 한 쌍이다. 주의 이상으로 승격된 노드는
// ③ 에서 빠져 ② 로 옮겨가고, 그만큼 ② 가 커진다. "비율이 바뀌는 것"과 "카드가
// 옮겨가는 것"이 같은 사건이어야 화면이 거짓말을 하지 않는다.
//
// 컴포넌트 안에 두지 않고 여기로 뺀 이유는 이 규칙이 사양이기 때문이다 —
// 표(0~4)와 승격 조건은 테스트로 붙잡아 두어야 나중에 조용히 어긋나지 않는다.

import type { AlertLevel, SensorNodeState } from "../types";
import { LEVEL_RANK } from "./alerts";

/** n = 주의 이상 온라인 노드 수 → [② share, ③ share]. */
export const RISK_SPLIT: Record<number, [number, number]> = {
  0: [15, 85],
  1: [35, 65],
  2: [52, 48],
  3: [68, 32],
  4: [82, 18],
};

/** 표에 없는 n(노드가 5개 이상으로 늘어난 경우)은 최대치로 붙잡는다. */
export function splitFor(riskCount: number): [number, number] {
  const n = Math.max(0, Math.min(riskCount, 4));
  return RISK_SPLIT[n];
}

export interface ConsoleSplit {
  /** ② 에 들어갈 노드. 위험도 높은 순(L3 → L2 → L1). */
  risk: string[];
  /** ③ 에 남을 노드. risk 와 겹치지 않는다. */
  summary: string[];
  /** ② / ③ 세로 비율. */
  share: [number, number];
}

/**
 * 노드를 ② 와 ③ 로 가른다.
 *
 * 승격 조건은 세 가지를 모두 만족해야 한다.
 *   1. 노드 데이터가 있을 것
 *   2. 온라인일 것 — 오프라인 노드의 멈춘 값으로 위험 상세를 채우지 않는다
 *   3. 등급이 주의(level1_caution) 이상일 것
 *
 * `unknown` 은 승격하지 않는다. 판정 불가는 위험이 아니라 근거 없음이고,
 * 승격시키면 임계값을 못 받은 동안 전 노드가 위험 상세를 채워서 진짜 위험이
 * 묻힌다. 그렇다고 `normal` 로 취급하지도 않는다 — ③ 에 회색 상태로 남는다
 * (이슈 #165).
 */
export function splitNodes(
  nodeIds: readonly string[],
  nodes: Record<string, SensorNodeState>,
  levelOf: (id: string) => AlertLevel,
): ConsoleSplit {
  const risk = nodeIds
    .filter((id) => {
      const node = nodes[id];
      if (!node || node.connection_status !== "online") return false;
      return LEVEL_RANK[levelOf(id)] >= LEVEL_RANK.level1_caution;
    })
    // 높은 등급이 위로 온다. ② 가 넘쳐 스크롤이 생겨도, 잘리는 쪽은 항상 덜
    // 위험한 카드여야 한다.
    .sort((a, b) => LEVEL_RANK[levelOf(b)] - LEVEL_RANK[levelOf(a)]);

  const promoted = new Set(risk);
  return {
    risk,
    summary: nodeIds.filter((id) => !promoted.has(id)),
    share: splitFor(risk.length),
  };
}
