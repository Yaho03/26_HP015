import { useEffect, useState } from "react";

/**
 * 마지막 수신으로부터 얼마나 지났는가.
 *
 * 안전 화면에서 가장 무서운 실패는 값이 틀린 것이 아니라 **값이 멈춘 것을
 * 모르는 것**이다. 마지막 프레임이 화면에 그대로 남아 있으면 570ppm 정상은
 * 계속 570ppm 정상으로 보인다. 연결 상태(connection_status)는 서버가 판정해
 * 내려주지만 그 판정 자체가 늦거나 끊길 수 있어서, 화면이 직접 시계를 본다.
 *
 * 스로틀이 지표당 1초(#106)이므로 5초면 최소 네 프레임을 놓친 것이다.
 */
export const STALE_AFTER_MS = 5_000;

/** 1초마다 다시 센다. 더 잘게 돌려도 표시가 초 단위라 바뀌는 게 없다. */
const TICK_MS = 1_000;

export interface Freshness {
  /** 마지막 수신 이후 경과 초. 타임스탬프가 없으면 null. */
  secondsAgo: number | null;
  /** 5초 이상 조용하면 true. 타임스탬프가 없으면 판정하지 않는다(false). */
  isStale: boolean;
  /** "2초 전" · 타임스탬프가 없으면 "—". */
  label: string;
}

/**
 * 판정 자체는 순수 함수로 둔다 — 렌더러 없이 테스트하기 위해서다.
 * 훅은 시계를 돌리는 일만 한다.
 *
 * @param lastSeenAt ISO 문자열. null/undefined 면 판정하지 않는다 —
 *   여기서 stale 을 참으로 만들면 아직 한 번도 보고하지 않은 대기 슬롯이
 *   전부 "지연" 으로 붉어진다. 그건 "연결이 끊겼다"와 다른 상태다.
 */
export function freshnessAt(lastSeenAt: string | null | undefined, now: number): Freshness {
  if (!lastSeenAt) return { secondsAgo: null, isStale: false, label: "—" };

  const parsed = Date.parse(lastSeenAt);
  // 파싱 실패를 0 으로 떨어뜨리면 "방금 도착" 으로 보인다.
  if (Number.isNaN(parsed)) return { secondsAgo: null, isStale: false, label: "—" };

  // 기기 시계가 앞서 있으면 음수가 나온다. 미래 시각을 "0초 전" 으로 보여줄 뿐
  // 지연으로 판정하지는 않는다.
  const elapsed = Math.max(0, now - parsed);
  const secondsAgo = Math.floor(elapsed / 1000);

  return {
    secondsAgo,
    isStale: elapsed >= STALE_AFTER_MS,
    label: `${secondsAgo}초 전`,
  };
}

export function useFreshness(lastSeenAt: string | null | undefined): Freshness {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), TICK_MS);
    return () => window.clearInterval(timer);
  }, []);

  return freshnessAt(lastSeenAt, now);
}
