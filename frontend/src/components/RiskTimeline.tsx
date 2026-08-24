import { memo } from "react";
import type { AlertEvent } from "../services/api";
import { LEVEL_RANK } from "../utils/alerts";
import type { AlertLevel } from "../types";

/** 24시간을 1시간 칸 24개로 나눈다. 더 잘게 쪼개면 132px 칸에서 칸이 뭉갠다. */
const BUCKETS = 24;
const HOUR_MS = 3_600_000;

interface RiskTimelineProps {
  events: AlertEvent[];
  /** 기준 시각. 테스트에서 고정하기 위해 주입받는다. */
  now?: number;
}

/**
 * 지난 24시간 등급 띠.
 *
 * ④ 는 평상시 비어 있는 칸이다 — 사고가 없으면 로그도 없다. "기록 없음" 한 줄만
 * 남으면 화면에서 가장 큰 죽은 공간이 되므로, 같은 자리에 "오늘 하루 어땠는가"를
 * 싣는다. 로그가 생기면 위로 쌓이고 이 띠는 아래로 밀린다.
 *
 * 빈 시간대를 회색이 아니라 **정상 색**으로 칠하지 않는다. 경보가 없었다는 것과
 * 그 시간에 시스템이 살아 있었다는 것은 다른 사실이고, 이 데이터는 전자만 안다.
 */
export const RiskTimeline = memo(function RiskTimeline({ events, now }: RiskTimelineProps) {
  const end = now ?? Date.now();
  // 정시 경계로 맞춘다. 칸 하나가 걸치는 시간대가 매 렌더 미끄러지면 띠가 흔들린다.
  const endHour = Math.floor(end / HOUR_MS) * HOUR_MS + HOUR_MS;
  const start = endHour - BUCKETS * HOUR_MS;

  const worst: (AlertLevel | null)[] = Array.from({ length: BUCKETS }, () => null);
  for (const e of events) {
    const t = Date.parse(e.activated_at);
    if (Number.isNaN(t) || t < start || t >= endHour) continue;
    const i = Math.floor((t - start) / HOUR_MS);
    const level = e.level as AlertLevel;
    if (!(level in LEVEL_RANK)) continue;
    const current = worst[i];
    if (current === null || LEVEL_RANK[level] > LEVEL_RANK[current]) worst[i] = level;
  }

  return (
    <div className="risk-timeline">
      <div className="risk-timeline__head">
        <span className="risk-timeline__title">최근 24시간</span>
      </div>
      <div className="risk-timeline__strip" role="img" aria-label="최근 24시간 등급 추이">
        {worst.map((level, i) => {
          const hour = new Date(start + i * HOUR_MS).getHours();
          return (
            <span
              key={i}
              className={"risk-timeline__cell" + (level ? " is-" + level : " is-quiet")}
              title={`${String(hour).padStart(2, "0")}시 — ${level ? level : "경보 없음"}`}
            />
          );
        })}
      </div>
      <div className="risk-timeline__axis" aria-hidden="true">
        <span>{String(new Date(start).getHours()).padStart(2, "0")}시</span>
        <span>{String(new Date(start + 12 * HOUR_MS).getHours()).padStart(2, "0")}시</span>
        <span>현재</span>
      </div>
    </div>
  );
});
