import { memo } from "react";
import { SPARKLINE_WINDOW_MS, type TrendPoint } from "../store/dashboardStore";

/**
 * 최근 구간 추세선.
 *
 * **Recharts 를 쓰지 않는다.** 노드 4개 × 지표 6종 = 24개의 미니 차트가 실시간
 * 스트림마다 갱신되는데, 각각이 ResponsiveContainer + SVG 트리를 들고 있으면
 * 리렌더 비용을 감당할 수 없다. 여기서 필요한 건 축도 툴팁도 아닌 선 하나다.
 *
 * viewBox 를 고정하고 preserveAspectRatio="none" 으로 늘리므로 부모가 어떤
 * 크기든 CSS 로만 정하면 된다. 선 굵기는 non-scaling-stroke 로 유지한다.
 */
interface SparklineProps {
  points: TrendPoint[] | undefined;
  /** 표시 구간. 기본 5분. */
  windowMs?: number;
  /** 값이 멈춘 상태(오프라인)면 선을 죽인다. */
  stale?: boolean;
  className?: string;
}

const W = 100;
const H = 24;

export const Sparkline = memo(function Sparkline({
  points,
  windowMs = SPARKLINE_WINDOW_MS,
  stale = false,
  className,
}: SparklineProps) {
  const all = points ?? [];
  // 마지막 샘플 기준으로 자른다. 벽시계 기준으로 자르면 오프라인 노드의 버퍼가
  // 조용히 비어서, 값이 사라진 건지 0 이 온 건지 구분되지 않는다.
  const last = all.length > 0 ? all[all.length - 1].t : 0;
  const win = all.filter((p) => p.t >= last - windowMs);

  if (win.length < 2) {
    return (
      <span className={"spark spark--empty " + (className ?? "")} aria-hidden="true">
        —
      </span>
    );
  }

  const lo = Math.min(...win.map((p) => p.v));
  const hi = Math.max(...win.map((p) => p.v));
  const span = hi - lo || 1;
  const t0 = win[0].t;
  const tSpan = win[win.length - 1].t - t0 || 1;

  const pts = win
    .map((p) => {
      const x = ((p.t - t0) / tSpan) * W;
      const y = H - 2 - ((p.v - lo) / span) * (H - 4);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  const [hx, hy] = pts.split(" ")[win.length - 1].split(",");

  return (
    <svg
      className={"spark" + (stale ? " spark--stale" : "") + (className ? " " + className : "")}
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
      aria-hidden="true"
      focusable="false"
    >
      <polyline className="spark__line" points={pts} vectorEffect="non-scaling-stroke" />
      <circle className="spark__head" cx={hx} cy={hy} r="1.6" vectorEffect="non-scaling-stroke" />
    </svg>
  );
});
