import { useEffect, useRef, useState } from "react";
import { LEVEL_RANK } from "../utils/alerts";
import type { AlertLevel } from "../types";

/**
 * 등급 플래핑 억제.
 *
 * 측정값이 임계값 경계에 걸치면 등급이 초 단위로 오르내린다. 그때마다 노드가
 * ② 와 ③ 사이를 오가고, 칸 비율(RISK_SPLIT)이 따라 움직이고, 카드가 자리를
 * 바꾼다 — 화면 전체가 떨린다. 관제 화면에서 이건 장식 문제가 아니라, 읽는
 * 사람이 방금 보던 카드를 매번 다시 찾아야 하는 판독 문제다.
 *
 * **정렬 결과가 아니라 등급 자체를 안정화한다.** 등급이 단일 소스라서, 여기서
 * 한 번 눌러 두면 카운트(②)·승격 분할(③)·높이 비율·카드 정렬이 전부 같은 값을
 * 보게 된다. 리스트를 따로 안정화하면 "카운트는 경고 1인데 카드는 정상" 같은
 * 어긋남이 생긴다.
 *
 * ## 상승은 즉시, 하강만 지연
 *
 * 비대칭이 이 훅의 요점이다.
 *
 *   - 등급이 **오르면 그 프레임에 바로** 반영한다. 위험을 4초 늦게 보여주는
 *     것은 이 화면이 존재하는 이유를 부정한다.
 *   - 등급이 **내리면 유지 시간을 채운 뒤에** 반영한다. 높은 등급을 조금 더
 *     오래 보여주는 쪽은 안전한 방향의 오차다.
 *
 * 그래서 이 훅은 위험을 지연시키지 않는다 — 안심을 지연시킨다.
 *
 * `unknown` 은 normal 위, 경보 아래에 있다 (utils/alerts LEVEL_RANK). 그래서
 * normal → unknown 은 상승으로 취급되어 즉시 반영되고(판정 못 하는 것을
 * 안전하다고 계속 말하지 않는다), unknown → normal 은 하강이라 유지된다.
 */
export const LEVEL_HOLD_MS = 4_000;

export interface LevelHold {
  /** 지금 화면에 그려지는 등급. */
  shown: AlertLevel;
  /** 관측됐지만 아직 채택되지 않은 낮은 등급. 없으면 null. */
  pending: AlertLevel | null;
  /** pending 이 처음 관측된 시각. */
  pendingSince: number;
}

/**
 * 판정은 순수 함수로 둔다 — 렌더러 없이 테스트하기 위해서다.
 * 훅은 시계와 상태 보관만 맡는다.
 */
export function stabilizeLevels(
  incoming: Record<string, AlertLevel>,
  prev: Record<string, LevelHold>,
  now: number,
  holdMs: number = LEVEL_HOLD_MS,
): Record<string, LevelHold> {
  const next: Record<string, LevelHold> = {};

  for (const id of Object.keys(incoming)) {
    const level = incoming[id];
    const before = prev[id];

    // 처음 보는 노드는 그대로 채택한다. 여기서 유지 시간을 걸면 화면이 뜨는
    // 순간 4초 동안 빈 등급이 된다.
    if (!before) {
      next[id] = { shown: level, pending: null, pendingSince: now };
      continue;
    }

    // 상승 또는 동일 — 즉시 반영하고 대기 중이던 하강은 버린다.
    if (LEVEL_RANK[level] >= LEVEL_RANK[before.shown]) {
      next[id] = { shown: level, pending: null, pendingSince: now };
      continue;
    }

    // 하강. 같은 후보가 유지 시간을 채웠으면 채택한다.
    const sameCandidate = before.pending === level;
    const since = sameCandidate ? before.pendingSince : now;
    if (sameCandidate && now - since >= holdMs) {
      next[id] = { shown: level, pending: null, pendingSince: now };
      continue;
    }

    // 아직 유지 중 — 화면은 높은 등급을 그대로 유지한다.
    next[id] = { shown: before.shown, pending: level, pendingSince: since };
  }

  return next;
}

/** 유지 대기 중인 하강이 하나라도 있는가. 있을 때만 시계를 돌린다. */
function hasPending(holds: Record<string, LevelHold>): boolean {
  return Object.values(holds).some((h) => h.pending !== null);
}

export function useStableLevels(
  levels: Record<string, AlertLevel>,
  holdMs: number = LEVEL_HOLD_MS,
): Record<string, AlertLevel> {
  const [holds, setHolds] = useState<Record<string, LevelHold>>(() =>
    stabilizeLevels(levels, {}, Date.now(), holdMs),
  );
  // 최신 입력을 담아 둔다. 유지 시간이 끝났는데 새 데이터가 안 오면(값이 멈춘
  // 경우) 타이머만으로 재판정해야 하기 때문이다.
  const latest = useRef(levels);

  useEffect(() => {
    latest.current = levels;
    setHolds((prev) => stabilizeLevels(levels, prev, Date.now(), holdMs));
  }, [levels, holdMs]);

  useEffect(() => {
    if (!hasPending(holds)) return;
    // 유지 시간이 끝나는 시점에 한 번만 깨운다. 상시 인터벌은 화면 전체를
    // 초마다 다시 그리게 만든다.
    const timer = window.setTimeout(() => {
      setHolds((prev) => stabilizeLevels(latest.current, prev, Date.now(), holdMs));
    }, holdMs);
    return () => window.clearTimeout(timer);
  }, [holds, holdMs]);

  const out: Record<string, AlertLevel> = {};
  for (const id of Object.keys(holds)) out[id] = holds[id].shown;
  return out;
}
