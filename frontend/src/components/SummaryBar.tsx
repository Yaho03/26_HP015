import { useEffect, useRef, useState } from "react";
import type { AlertLevel } from "../types";
import type { Projection } from "../utils/projection";
import { levelLabel } from "../utils/alerts";
import { alertMetricLabel } from "../utils/alertLabels";
import { shortNodeLabel } from "../utils/nodes";
import { LEVEL_ICON } from "./icons";

interface SummaryBarProps {
  counts: Record<AlertLevel, number>;
  /** 지금 가장 등급이 높은 온라인 노드. 없으면 null. */
  worstNodeId: string | null;
  worstLevel: AlertLevel;
  /** 전 노드에서 가장 심각한 도달 예측. 상승 중인 지표가 없으면 null. */
  projection: Projection | null;
}

const ITEMS: { level: AlertLevel; label: string }[] = [
  { level: "normal", label: "정상" },
  { level: "level1_caution", label: "주의" },
  { level: "level2_warning", label: "경고" },
  { level: "level3_critical", label: "위험" },
];

// 판정 불가는 평상시엔 0이라 칸을 차지할 이유가 없다. 발생했을 때만 맨 앞에
// 끼워 넣는다 (이슈 #165) — 0을 상시 노출하면 네 칸 요약의 리듬만 깨진다.
const UNKNOWN_ITEM: { level: AlertLevel; label: string } = {
  level: "unknown",
  label: "판정 불가",
};

function AnimatedNumber({ value }: { value: number }) {
  const [displayValue, setDisplayValue] = useState(value);
  // 목표값이 아니라 "지금 화면에 그려져 있는 값"을 담는다.
  // 예전에는 애니메이션 시작 시점에 목표값을 넣었는데, 프레임이 중간에 취소되면
  // 화면은 중간값에 멈춘 채 ref 만 도착했다고 주장했다. 그러면 다음 effect 가
  // difference === 0 으로 일찍 빠져나가 숫자가 옛 값에 영영 얼어붙는다.
  const displayed = useRef(value);

  useEffect(() => {
    const from = displayed.current;
    const difference = value - from;
    if (difference === 0) return;

    const settle = () => {
      displayed.current = value;
      setDisplayValue(value);
    };

    // 애니메이션은 장식이다. 숫자가 참값에 도달하는 것이 애니메이션에 걸리면 안 된다.
    // 탭이 백그라운드면 requestAnimationFrame 은 아예 발화하지 않아서, 예전 코드는
    // 요약 숫자가 옛 값에 멈춘 채로 남았다 — 카드가 L3 인데 요약이 "0 위험"으로
    // 보이는 상태다. 안전 화면에서 이건 장식 문제가 아니라 오독 문제다.
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    if (document.hidden || media.matches) {
      settle();
      return;
    }

    let frame = 0;
    let startedAt = 0;
    const duration = 360;
    const tick = (now: number) => {
      if (!startedAt) startedAt = now;
      const progress = Math.min(1, (now - startedAt) / duration);
      const eased = 1 - Math.pow(1 - progress, 3);
      // 마지막 프레임은 보간값이 아니라 목표값을 그대로 쓴다 — 부동소수 잔차가
      // 남으면 다음 비교에서 difference 가 0 이 아니게 되어 불필요한 재생이 돈다.
      const next = progress < 1 ? from + difference * eased : value;
      displayed.current = next;
      setDisplayValue(next);
      if (progress < 1) frame = requestAnimationFrame(tick);
    };

    frame = requestAnimationFrame(tick);
    // 재생 도중 탭이 숨겨지면 rAF 가 멈춘다. setTimeout 은 스로틀링돼도 발화하므로
    // 여유를 두고 참값을 확정한다. 정상 재생된 뒤에는 같은 값을 다시 쓰는 무해한 호출이다.
    const guard = window.setTimeout(settle, duration + 120);
    return () => {
      cancelAnimationFrame(frame);
      window.clearTimeout(guard);
    };
  }, [value]);

  return <span className="summary-count">{Math.round(displayValue)}</span>;
}

/** 분 단위를 사람이 읽는 문구로. 1분 미만은 "곧" 이다 — "0분 뒤"는 말이 안 된다. */
function formatMinutes(minutes: number): string {
  if (minutes < 1) return "곧";
  return `약 ${Math.round(minutes)}분 뒤`;
}

/**
 * ② 전체 상태 스트립.
 *
 * 노드가 4개뿐이라 등급별 카운트만으로는 면적 대비 정보량이 낮다 — ③ 의 카드
 * 네 장이 이미 같은 것을 색으로 말하고 있다. 그래서 카운트는 한 줄로 눌러두고,
 * 남는 가로에 **다른 칸 어디에도 없는 것**을 넣는다: 지금 가장 나쁜 노드가
 * 무엇이고, 이 추세가 유지되면 언제 어느 등급에 닿는가.
 *
 * 예측 문구는 경보가 아니다 (06_ALERT_RULES §8.2). "추세" 라는 말을 항상 앞에
 * 붙이고, 적합도를 같이 적어 단정처럼 읽히지 않게 한다.
 */
export function SummaryBar({ counts, worstNodeId, worstLevel, projection }: SummaryBarProps) {
  const items = counts.unknown > 0 ? [UNKNOWN_ITEM, ...ITEMS] : ITEMS;
  const WorstIcon = LEVEL_ICON[worstLevel];

  return (
    <section className="summary-bar" role="status" aria-label="전체 노드 요약">
      <div className="summary-bar__counts">
        {items.map(({ level, label }) => {
          const Icon = LEVEL_ICON[level];
          return (
            <div key={level} className={"summary-item is-" + level}>
              <Icon size={12} />
              <span className="summary-label">{label}</span>
              <AnimatedNumber value={counts[level]} />
            </div>
          );
        })}
      </div>

      {/* 우측 열이 ~390px 뿐이라 카운트와 같은 줄에 두면 문구가 줄바꿈되며
          스트립 전체를 밀어올린다. 아랫줄로 내리고 가로를 통째로 쓴다. */}
      <div className="summary-bar__context">
        <div className={"summary-bar__worst is-" + worstLevel}>
          <span className="summary-bar__key">최악</span>
          {worstNodeId ? (
            <>
              <WorstIcon size={12} />
              <span className="summary-bar__node">{shortNodeLabel(worstNodeId)}</span>
              <span className="summary-bar__level">{levelLabel(worstLevel)}</span>
            </>
          ) : (
            // 온라인 노드가 하나도 없는 상태다. "정상"으로 그리면 안 된다.
            <span className="summary-bar__muted">온라인 노드 없음</span>
          )}
        </div>

        <div className={"summary-bar__proj" + (projection ? " is-" + projection.level : "")}>
          <span className="summary-bar__key">추세</span>
          {projection ? (
            <>
              <span className="summary-bar__proj-eta">{formatMinutes(projection.minutes)}</span>
              <span className="summary-bar__proj-level">{levelLabel(projection.level)}</span>
              <span className="summary-bar__proj-metric">
                {alertMetricLabel(projection.metric)}
              </span>
              {/* R² 는 확률이 아니다. "신뢰도 78%" 로 적으면 확률로 읽힌다. */}
              {projection.confidence !== null && (
                <span className="summary-bar__proj-fit">
                  적합도 {projection.confidence.toFixed(2)}
                </span>
              )}
            </>
          ) : (
            <span className="summary-bar__muted">상승 추세 없음</span>
          )}
        </div>
      </div>
    </section>
  );
}
