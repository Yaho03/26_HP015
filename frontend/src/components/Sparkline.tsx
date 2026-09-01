import { memo } from "react";
import { SPARKLINE_WINDOW_MS, type TrendPoint } from "../store/dashboardStore";
import type { ProjectionPoint } from "../utils/projection";

/**
 * 최근 구간 추세선.
 *
 * **Recharts 를 쓰지 않는다.** 노드 4개 × 지표 6종 = 24개의 미니 차트가 실시간
 * 스트림마다 갱신되는데, 각각이 ResponsiveContainer + SVG 트리를 들고 있으면
 * 리렌더 비용을 감당할 수 없다. 여기서 필요한 건 축도 툴팁도 아닌 선 하나다.
 *
 * viewBox 를 고정하고 preserveAspectRatio="none" 으로 늘리므로 부모가 어떤
 * 크기든 CSS 로만 정하면 된다. 선 굵기는 non-scaling-stroke 로 유지한다.
 *
 * `projection` 을 주면 오른쪽에 점선 구간이 붙는다. **실측과 예측은 절대 같은
 * 선으로 그리지 않는다** — 실선/점선으로 갈라 두지 않으면 "지금 570ppm 인데 왜
 * 경고인가"를 화면에서 되짚을 방법이 없다.
 */
interface SparklineProps {
  points: TrendPoint[] | undefined;
  /** 표시 구간. 기본 5분. */
  windowMs?: number;
  /** 값이 멈춘 상태(오프라인)면 선을 죽인다. */
  stale?: boolean;
  /**
   * 외삽 구간. 마지막 점의 값이 곧 도달 임계값이므로(projection.ts 가 그렇게
   * 자른다) 그 높이에 임계선을 함께 긋는다. 임계값을 여기서 따로 받지 않는
   * 이유다 — 두 값이 어긋날 여지를 만들지 않는다.
   */
  projection?: ProjectionPoint[];
  className?: string;
}

const W = 100;
const H = 24;
const PAD = 2;

export const Sparkline = memo(function Sparkline({
  points,
  windowMs = SPARKLINE_WINDOW_MS,
  stale = false,
  projection,
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

  // 오프라인 노드의 멈춘 버퍼로 미래를 그리지 않는다.
  const proj = !stale && projection && projection.length > 0 ? projection : null;

  // 세로 눈금은 실측과 예측을 함께 담는다. 예측이 범위 밖으로 나가면 점선이
  // 잘려 "아직 여유 있다"로 보인다.
  const values = win.map((p) => p.v);
  if (proj) for (const p of proj) values.push(p.value);
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const span = hi - lo || 1;

  // 가로 눈금도 하나로 잇는다 — 실측과 예측의 시간 축척이 다르면 기울기가
  // 꺾여 보여서, 없는 가속을 있는 것처럼 읽게 만든다.
  const t0 = win[0].t;
  const observedSpan = win[win.length - 1].t - t0;
  const projSpanMs = proj ? Math.max(...proj.map((p) => p.offsetS)) * 1000 : 0;
  const totalSpan = observedSpan + projSpanMs || 1;

  const xAt = (ms: number) => (ms / totalSpan) * W;
  const yAt = (v: number) => H - PAD - ((v - lo) / span) * (H - PAD * 2);

  const observedPts = win.map((p) => `${xAt(p.t - t0).toFixed(1)},${yAt(p.v).toFixed(1)}`);
  const headX = xAt(observedSpan);
  const headY = yAt(win[win.length - 1].v);

  // 점선은 마지막 실측점에서 출발한다. 띄워 놓으면 두 선이 다른 계열로 보인다.
  const projPts = proj
    ? [
        `${headX.toFixed(1)},${headY.toFixed(1)}`,
        ...proj.map((p) => `${xAt(observedSpan + p.offsetS * 1000).toFixed(1)},${yAt(p.value).toFixed(1)}`),
      ]
    : null;
  const thresholdY = proj ? yAt(proj[proj.length - 1].value) : null;

  return (
    <svg
      className={"spark" + (stale ? " spark--stale" : "") + (className ? " " + className : "")}
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
      aria-hidden="true"
      focusable="false"
    >
      {thresholdY !== null && (
        <line
          className="spark__threshold"
          x1="0"
          y1={thresholdY.toFixed(1)}
          x2={W}
          y2={thresholdY.toFixed(1)}
          vectorEffect="non-scaling-stroke"
        />
      )}
      <polyline
        className="spark__line"
        points={observedPts.join(" ")}
        vectorEffect="non-scaling-stroke"
      />
      {projPts && (
        <polyline
          className="spark__proj"
          points={projPts.join(" ")}
          vectorEffect="non-scaling-stroke"
        />
      )}
      <circle
        className="spark__head"
        cx={headX.toFixed(1)}
        cy={headY.toFixed(1)}
        r="1.6"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
});
