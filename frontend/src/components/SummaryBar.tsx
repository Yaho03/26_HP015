import { useEffect, useRef, useState } from "react";
import type { AlertLevel } from "../types";
import { LEVEL_ICON } from "./icons";

interface SummaryBarProps {
  counts: Record<AlertLevel, number>;
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

export function SummaryBar({ counts }: SummaryBarProps) {
  const items = counts.unknown > 0 ? [UNKNOWN_ITEM, ...ITEMS] : ITEMS;
  const total = items.reduce((sum, { level }) => sum + counts[level], 0);

  return (
    <div className="summary-bar" role="status" aria-label="전체 노드 요약">
      {items.map(({ level, label }) => {
        const Icon = LEVEL_ICON[level];
        const share = total > 0 ? (counts[level] / total) * 100 : 0;
        return (
          <div key={level} className={"summary-item is-" + level}>
            <AnimatedNumber value={counts[level]} />
            <span className="summary-label">
              <Icon size={12} />
              {label}
            </span>
            <span className="summary-meter" aria-hidden="true">
              <span className="summary-meter__fill" style={{ width: `${share}%` }} />
            </span>
          </div>
        );
      })}
    </div>
  );
}
