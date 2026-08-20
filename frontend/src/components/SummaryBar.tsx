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

function AnimatedNumber({ value }: { value: number }) {
  const [displayValue, setDisplayValue] = useState(value);
  const previousValue = useRef(value);

  useEffect(() => {
    const from = previousValue.current;
    const difference = value - from;
    if (difference === 0) return;

    let frame = 0;
    let startedAt = 0;
    const duration = 360;
    const tick = (now: number) => {
      if (!startedAt) startedAt = now;
      const progress = Math.min(1, (now - startedAt) / duration);
      const eased = 1 - Math.pow(1 - progress, 3);
      setDisplayValue(from + difference * eased);
      if (progress < 1) frame = requestAnimationFrame(tick);
    };

    frame = requestAnimationFrame(tick);
    previousValue.current = value;
    return () => cancelAnimationFrame(frame);
  }, [value]);

  return <span className="summary-count">{Math.round(displayValue)}</span>;
}

export function SummaryBar({ counts }: SummaryBarProps) {
  const total = ITEMS.reduce((sum, { level }) => sum + counts[level], 0);

  return (
    <div className="summary-bar" role="status" aria-label="전체 노드 요약">
      {ITEMS.map(({ level, label }) => {
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
