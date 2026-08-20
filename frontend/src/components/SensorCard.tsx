import { memo, useMemo, type ComponentType } from "react";
import type { AlertLevel, MetricKey, SensorNodeState } from "../types";
import type { TrendPoint } from "../store/dashboardStore";
import { levelLabel, nodeAlertLevel } from "../utils/alerts";
import { projectThresholdCrossing } from "../utils/trend";
import { IconClock, LEVEL_ICON } from "./icons";

const PROJECTION_LABEL: Record<AlertLevel, string> = {
  normal: "정상",
  level1_caution: "L1 주의",
  level2_warning: "L2 경고",
  level3_critical: "L3 위험",
};

/** 상승 추세 화살표. 색 단독 표기를 피하려고 아이콘을 함께 쓴다. */
function TrendUpIcon() {
  return (
    <svg viewBox="0 0 12 12" width="11" height="11" aria-hidden="true" focusable="false">
      <path d="M1.5 8.5 L4.5 5 L6.8 7 L10.5 2.8" fill="none" stroke="currentColor"
        strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M7.6 2.6 H10.7 V5.7" fill="none" stroke="currentColor"
        strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

interface SensorCardProps {
  node_id: string;
  node: SensorNodeState | null;
  trend?: TrendPoint[];
}

/** Every metric the frontend can receive for a sensor node except the primary
 *  CO₂ readout, which gets the gauge. o2_pct belongs to the wearable. */
const SECONDARY: { key: MetricKey; label: string; unit: string }[] = [
  { key: "co_ppm", label: "CO", unit: "ppm" },
  { key: "h2s_ppm", label: "H₂S", unit: "ppm" },
  { key: "temperature_c", label: "온도", unit: "°C" },
  { key: "humidity_pct", label: "습도", unit: "%" },
  { key: "gas_resistance_ohm", label: "가스저항", unit: "Ω" },
];

/** CO₂ gauge full-scale. Above this the arc simply pins. */
const CO2_FULL_SCALE = 6000;

function fmt(metric: MetricKey, value: number): string {
  if (metric === "co2_ppm") return Math.round(value).toString();
  if (metric === "gas_resistance_ohm") return Math.round(value).toLocaleString();
  return value.toFixed(1);
}

function sampleTime(value: string | null): string {
  if (!value) return "샘플 없음";
  return new Date(value).toLocaleTimeString("ko-KR", { hour12: false });
}

/** 260° open arc with tick marks — the bridge-console instrument face. */
function Co2Gauge({ value }: { value: number | null }) {
  const R = 52;
  const CX = 64;
  const CY = 64;
  const A0 = 130;
  const A1 = 410;
  const rad = (a: number) => (a * Math.PI) / 180;
  const polar = (a: number, r: number) => [CX + r * Math.cos(rad(a)), CY + r * Math.sin(rad(a))];
  const arc = (from: number, to: number) => {
    const [x0, y0] = polar(from, R);
    const [x1, y1] = polar(to, R);
    return `M${x0.toFixed(2)},${y0.toFixed(2)}A${R},${R} 0 ${to - from > 180 ? 1 : 0} 1 ${x1.toFixed(2)},${y1.toFixed(2)}`;
  };

  const frac = value === null ? 0 : Math.max(0.01, Math.min(1, value / CO2_FULL_SCALE));
  const ticks = [];
  for (let i = 0; i <= 12; i++) {
    const a = A0 + (A1 - A0) * (i / 12);
    const major = i % 3 === 0;
    const [ax, ay] = polar(a, R - 10);
    const [bx, by] = polar(a, R - (major ? 17 : 14));
    ticks.push(
      <path
        key={i}
        d={`M${ax.toFixed(1)},${ay.toFixed(1)}L${bx.toFixed(1)},${by.toFixed(1)}`}
        strokeWidth="1.2"
        opacity={major ? 0.75 : 0.35}
      />,
    );
  }

  return (
    <svg viewBox="0 0 128 128" className="co2-gauge" aria-hidden="true">
      <path d={arc(A0, A1)} className="co2-gauge__track" />
      {value !== null && <path d={arc(A0, A0 + (A1 - A0) * frac)} className="co2-gauge__value" />}
      <g className="co2-gauge__ticks">{ticks}</g>
    </svg>
  );
}

/** CO₂ trend over the buffered window. Needs at least two points to draw a line. */
function TrendLine({ points }: { points: TrendPoint[] }) {
  const W = 200;
  const H = 30;
  const lo = Math.min(...points.map((p) => p.v));
  const hi = Math.max(...points.map((p) => p.v));
  const span = hi - lo || 1;
  const t0 = points[0].t;
  const tSpan = points[points.length - 1].t - t0 || 1;
  const xy = points.map((p) => [
    ((p.t - t0) / tSpan) * (W - 2) + 1,
    H - 2 - ((p.v - lo) / span) * (H - 4),
  ]);
  const d = "M" + xy.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join("L");
  const [lx, ly] = xy[xy.length - 1];

  return (
    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="trend-line" aria-hidden="true">
      <path d={`${d}L${W - 1},${H}L1,${H}Z`} className="trend-line__area" />
      <path d={d} className="trend-line__stroke" vectorEffect="non-scaling-stroke" />
      <circle cx={lx.toFixed(1)} cy={ly.toFixed(1)} r="2.4" className="trend-line__head" />
    </svg>
  );
}

/** One card. When `node` is null the slot renders in a "대기" (pending) state
 *  so the spec layout is complete before live data is wired (#106). */
export const SensorCard = memo(function SensorCard({ node_id, node, trend }: SensorCardProps) {
  const level = node ? nodeAlertLevel(node) : "normal";
  const offline = node?.connection_status === "offline";
  const sim = node?.source_mode === "simulation";
  const co2 = node?.readings.co2_ppm ?? null;

  const cals = node?.calibration_status ?? {};
  const calibrating = Object.values(cals).some((s) => s === "in_progress");
  const calError = Object.values(cals).some((s) => s === "error");

  // 06_ALERT_RULES 8.2 — 추세 표시. 경보를 발령하지 않고 배지로만 알린다.
  // 오프라인 노드의 멈춘 버퍼로 미래를 예측하지 않는다.
  const projection = useMemo(
    () => (trend && !offline ? projectThresholdCrossing(trend, "co2_ppm") : null),
    [trend, offline],
  );

  const cls =
    "sensor-card is-" +
    level +
    (node ? "" : " sensor-card--pending") +
    (offline ? " sensor-card--offline" : "") +
    (sim ? " sensor-card--sim" : "");
  const LevelIcon = LEVEL_ICON[level] as ComponentType<{ size?: number | string }>;

  return (
    <article className={cls} aria-label={node ? `${node_id} ${levelLabel(level)}` : node_id}>
      <i className="brk brk--tl" aria-hidden="true" />
      <i className="brk brk--tr" aria-hidden="true" />
      <i className="brk brk--bl" aria-hidden="true" />
      <i className="brk brk--br" aria-hidden="true" />

      <header className="sensor-card__head">
        <span className="sensor-card__id">{node_id}</span>
        {calibrating && <span className="badge badge--cal-in_progress">CALIBRATING</span>}
        {calError && <span className="badge badge--cal-error">CAL ERR</span>}
        {sim && <span className="badge badge--sim">SIM</span>}
        {!node || offline ? (
          <span className="sensor-card__state state-offline">
            <IconClock size={12} />
            {node ? "연결 끊김" : "대기"}
          </span>
        ) : (
          <span className="sensor-card__state">
            <LevelIcon size={12} />
            {levelLabel(level)}
          </span>
        )}
      </header>

      <div className="sensor-card__body">
        <div className="sensor-card__gauge">
          <Co2Gauge value={co2 ? co2.value : null} />
          <div className="sensor-card__gauge-readout">
            <span className="primary-value">{co2 ? fmt("co2_ppm", co2.value) : "—"}</span>
            <span className="primary-label">CO₂ ppm</span>
          </div>
        </div>

        <div className="sensor-card__metrics">
          {SECONDARY.map(({ key, label, unit }) => {
            const r = node?.readings[key];
            return (
              <div className={"metric-mini" + (r ? "" : " metric-mini--empty")} key={key}>
                <span className="metric-mini__label">{label}</span>
                <span className="metric-mini__value">
                  {r ? (
                    <>
                      {fmt(key, r.value)}
                      <em>{unit}</em>
                    </>
                  ) : (
                    "—"
                  )}
                </span>
              </div>
            );
          })}
        </div>
      </div>

      {trend && trend.length >= 2 && (
        <>
          <div className="sensor-card__sparkhead">
            <span>CO₂ TREND / 60 MIN</span>
            <span>{trend.length}P</span>
          </div>
          <div className="sensor-card__spark">
            <TrendLine points={trend} />
          </div>
        </>
      )}

      {projection && (
        <p className={"sensor-card__projection is-" + projection.level}>
          <TrendUpIcon />
          <span>
            추세 유지 시 <strong>약 {Math.round(projection.minutes)}분 뒤</strong>{" "}
            {PROJECTION_LABEL[projection.level]} 도달 예상
          </span>
        </p>
      )}

      <p className="sensor-card__meta">
        {node ? `최근 수신 ${sampleTime(node.last_seen_at)}` : "데이터 대기 중"}
      </p>
    </article>
  );
});
