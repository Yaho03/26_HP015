import { memo, type ComponentType } from "react";
import type { AlertLevel, AlertState, SensorNodeState } from "../types";
import type { TrendPoint, TrendMetric } from "../store/dashboardStore";
import type { AssignedWorker } from "../services/api";
import { classifyMetric, levelLabel, LEVEL_RANK } from "../utils/alerts";
import { alertMetricLabel, metricFromAlertKey } from "../utils/alertLabels";
import { formatMetricValue, isUncalibrated, NODE_METRICS, unitFor } from "../utils/metrics";
import { nodeLastSeenAt, shortNodeLabel } from "../utils/nodes";
import { mostUrgentProjection } from "../utils/projection";
import { useFreshness } from "../hooks/useFreshness";
import { LEVEL_ICON } from "./icons";
import { Sparkline } from "./Sparkline";
import { ThresholdBar } from "./ThresholdBar";

type Trends = Partial<Record<TrendMetric, TrendPoint[]>>;

interface RiskDetailPanelProps {
  /** 주의(level1_caution) 이상인 온라인 노드. 위험도 높은 순으로 정렬돼 온다. */
  nodeIds: string[];
  nodes: Record<string, SensorNodeState>;
  trends: Record<string, Trends>;
  alerts: AlertState[];
  levelOf: (nodeId: string) => AlertLevel;
  workerFor: (nodeId: string) => AssignedWorker | null;
}

function formatTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString("ko-KR", { hour12: false });
}

const RiskCard = memo(function RiskCard({
  nodeId,
  node,
  trends,
  level,
  alerts,
  worker,
}: {
  nodeId: string;
  node: SensorNodeState | null;
  trends: Trends;
  level: AlertLevel;
  alerts: AlertState[];
  worker: AssignedWorker | null;
}) {
  const LevelIcon = LEVEL_ICON[level] as ComponentType<{
    size?: number | string;
  }>;
  const sim = node?.source_mode === "simulation";
  const fresh = useFreshness(nodeLastSeenAt(node));
  // 멈춘 버퍼로 미래를 예측하지 않는다. 승격된 카드일수록 이 구분이 중요하다 —
  // 위험 등급인 채로 값이 멈추면 "계속 위험" 인지 "보고가 끊긴" 것인지 갈린다.
  const projection = fresh.isStale ? null : mostUrgentProjection(trends);
  // 가장 먼저 발생한 경보가 이 노드가 승격된 시점이다.
  const firstAlert = alerts.reduce<AlertState | null>(
    (earliest, a) =>
      !earliest || Date.parse(a.activated_at) < Date.parse(earliest.activated_at) ? a : earliest,
    null,
  );

  return (
    <article
      className={"rcard is-" + level + (sim ? " rcard--sim" : "")}
      aria-label={`${shortNodeLabel(nodeId)} ${levelLabel(level)} 상세`}
    >
      <i className="brk brk--tl" aria-hidden="true" />
      <i className="brk brk--tr" aria-hidden="true" />
      <i className="brk brk--bl" aria-hidden="true" />
      <i className="brk brk--br" aria-hidden="true" />

      <header className="rcard__head">
        <LevelIcon size={15} />
        <span className="rcard__id">{shortNodeLabel(nodeId)}</span>
        <span className="rcard__node">{nodeId}</span>
        <span className="rcard__level">{levelLabel(level)}</span>
        {sim && <span className="badge badge--sim">SIM</span>}
        {node && (
          <span className={"rcard__age" + (fresh.isStale ? " rcard__age--stale" : "")}>
            {fresh.isStale ? "STALE " + fresh.label : fresh.label}
          </span>
        )}
      </header>

      {/* 6종 전부. 어느 지표가 등급을 끌어올렸는지 그 행이 강조된다. */}
      <table className="rcard__table">
        <tbody>
          {NODE_METRICS.map((meta) => {
            const r = node?.readings[meta.key];
            const uncal = isUncalibrated(node, meta);
            // 등급을 끌어올린 지표 판정. 미교정 값은 ppm 이 아니므로 근거로 쓰지 않는다.
            const metricLevel: AlertLevel =
              r && !uncal ? classifyMetric(meta.key, r.value) : "normal";
            const driving =
              LEVEL_RANK[metricLevel] >= LEVEL_RANK[level] && metricLevel !== "normal";

            return (
              <tr
                key={meta.key}
                className={"rcard__row is-" + metricLevel + (driving ? " rcard__row--driving" : "")}
              >
                <th scope="row">
                  {driving && (
                    <span className="rcard__driver" aria-label="등급 상승 원인">
                      ▸
                    </span>
                  )}
                  {meta.label}
                </th>
                <td className="rcard__value">
                  {r ? formatMetricValue(meta, r.value) : "—"}
                  <em>{r ? unitFor(node, meta) : ""}</em>
                  {uncal && <span className="badge badge--uncal">UNCAL</span>}
                </td>
                <td className="rcard__bar">
                  <ThresholdBar
                    metric={meta.key}
                    value={r?.value ?? null}
                    uncalibrated={uncal}
                    label={meta.label}
                  />
                </td>
                <td className="rcard__spark">
                  <Sparkline
                    points={trends[meta.key]}
                    stale={fresh.isStale}
                    projection={
                      projection?.metric === meta.key ? projection.curve : undefined
                    }
                  />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <footer className="rcard__foot">
        {projection && (
          // 06_ALERT_RULES §8.2 — 이 줄은 경보가 아니다. 출처와 적합도를 같이
          // 적어 단정으로 읽히지 않게 한다. R² 는 확률이 아니므로 % 로 쓰지 않는다.
          <div className={"rcard__projection is-" + projection.level}>
            <span className="rcard__proj-src">
              {projection.source === "lstm" ? "AI 예측" : "추세"}
            </span>
            <span className="rcard__proj-body">
              {alertMetricLabel(projection.metric)} · 약 {Math.round(projection.minutes)}분 뒤{" "}
              {levelLabel(projection.level)}
            </span>
            {projection.confidence !== null && (
              <span className="rcard__proj-fit">적합도 {projection.confidence.toFixed(2)}</span>
            )}
          </div>
        )}
        <div className="rcard__foot-row">
          <span className="rcard__foot-label">경보 발생</span>
          <span className="rcard__foot-value">{formatTime(firstAlert?.activated_at)}</span>
        </div>
        <ul className="rcard__alerts">
          {alerts.map((a) => (
            <li key={a.alert_key} className={"rcard__alert is-" + a.level}>
              <span className="rcard__alert-metric">
                {alertMetricLabel(metricFromAlertKey(a.alert_key))}
              </span>
              <span className="rcard__alert-value">
                {a.trigger_value.toFixed(1)} / 임계값 {a.threshold}
              </span>
              <span className="rcard__alert-level">{levelLabel(a.level)}</span>
            </li>
          ))}
          {alerts.length === 0 && (
            // 서버 경보 없이 프론트 판정만으로 승격된 경우다. 조용히 비우면
            // "경보가 해제됐다"로 읽히므로 그 차이를 문장으로 밝힌다.
            <li className="rcard__alert rcard__alert--none">
              활성 서버 경보 없음 — 측정값 기준 등급
            </li>
          )}
        </ul>
        <div className="rcard__foot-row">
          <span className="rcard__foot-label">배정 작업자</span>
          <span className="rcard__foot-value">
            {worker ? `${worker.name} · ${worker.employee_no}` : "미배정"}
          </span>
        </div>
      </footer>
    </article>
  );
});

/**
 * ② 위험 센서 상세.
 *
 * 주의 이상으로 승격된 노드만 여기 온다. 같은 노드가 ③ 에 중복 표시되지 않는
 * 것이 이 칸의 전제다 — ③ 이 줄어드는 만큼 여기가 커진다.
 */
export function RiskDetailPanel({
  nodeIds,
  nodes,
  trends,
  alerts,
  levelOf,
  workerFor,
}: RiskDetailPanelProps) {
  // 승격된 노드가 없으면 칸을 접는다. "주의 이상 노드 없음" 한 줄은 바로 위
  // 카운트(주의 0 · 경고 0 · 위험 0)가 이미 하는 말이고, 빈 껍데기가 ② 와 ③
  // 사이에 끼면 경계선만 하나 더 늘어난다.
  //
  // 조건부로 아예 빼지는 않는다 — 그리드 자식이 하나 줄면 뒤 칸들이 한 행씩
  // 당겨져 템플릿과 어긋난다 (실제로 ④ 가 암묵 행으로 밀려 겹친 적이 있다).
  if (nodeIds.length === 0) {
    return <section className="panel-2 panel-2--none" aria-hidden="true" />;
  }

  return (
    <section className="panel-2" aria-label="위험 센서 상세">
      {/* n 이 3~4 로 커지면 카드가 세로로 다 안 들어간다. 내부 스크롤로 받고
          위험도 높은 순으로 정렬해, 잘리는 쪽이 항상 덜 위험한 카드가 되게 한다. */}
      <div className="panel-2__body">
        {(
          nodeIds.map((id) => (
            <RiskCard
              key={id}
              nodeId={id}
              node={nodes[id] ?? null}
              trends={trends[id] ?? {}}
              level={levelOf(id)}
              alerts={alerts.filter((a) => a.node_id === id)}
              worker={workerFor(id)}
            />
          ))
        )}
      </div>
    </section>
  );
}
