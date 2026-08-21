import { memo, type ComponentType } from "react";
import { useDashboardStore } from "../store/dashboardStore";
import { SENSOR_SCREEN_ORDER } from "../utils/coordinates";
import { levelLabel, nodeAlertLevel } from "../utils/alerts";
import { formatMetricValue, isUncalibrated, NODE_METRICS, unitFor } from "../utils/metrics";
import { shortNodeLabel } from "../utils/nodes";
import { LEVEL_ICON, IconClock } from "./icons";
import { Sparkline } from "./Sparkline";
import { ThresholdBar } from "./ThresholdBar";
import type { AlertLevel } from "../types";

function formatTime(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString("ko-KR", { hour12: false });
}

/**
 * 한 노드 = 한 칸. 지표별 행에 현재값 · 임계값 대비 바 · 최근 5분 추세선을 둔다.
 *
 * 이 칸의 고유한 일은 **노드 간 비교와 추세 판독**이다. ③(현재값 글랜스)이나
 * Screen 3(시계열 차트)과 역할이 겹치면 안 되므로, 큰 수치 하나가 아니라
 * 6종을 같은 눈금으로 나란히 세운 표를 유지한다.
 *
 * 셀 단위로 구독한다 — 한 노드의 갱신이 나머지 3칸을 리렌더시키지 않는다
 * (10_UI_FLOW §10.3).
 */
const NodeMetricsCell = memo(function NodeMetricsCell({ nodeId }: { nodeId: string }) {
  const node = useDashboardStore((s) => s.sensor_nodes[nodeId]);
  const trends = useDashboardStore((s) => s.sensor_trend[nodeId]);

  const level: AlertLevel = node ? nodeAlertLevel(node) : "unknown";
  const offline = node?.connection_status === "offline";
  const sim = node?.source_mode === "simulation";
  const LevelIcon = LEVEL_ICON[level] as ComponentType<{
    size?: number | string;
  }>;

  return (
    <article
      className={
        "ncell is-" + level + (offline ? " ncell--offline" : "") + (sim ? " ncell--sim" : "")
      }
      aria-label={`${shortNodeLabel(nodeId)} 센서 데이터`}
    >
      <header className="ncell__head">
        {offline || !node ? <IconClock size={12} /> : <LevelIcon size={12} />}
        <span className="ncell__id">{shortNodeLabel(nodeId)}</span>
        <span className="ncell__node">{nodeId}</span>
        {sim && <span className="badge badge--sim">SIM</span>}
        <span className="ncell__state">
          {/* 오프라인이어도 값을 지우거나 0 으로 만들지 않는다. 마지막으로 관측된
              상태가 남아 있어야 "언제부터 모르는지"를 판단할 수 있다. */}
          {offline
            ? `OFFLINE · 마지막 수신 ${formatTime(node?.last_seen_at ?? null)}`
            : node
              ? levelLabel(level)
              : "대기"}
        </span>
      </header>

      <table className="ncell__table">
        <tbody>
          {NODE_METRICS.map((meta) => {
            const r = node?.readings[meta.key];
            const uncal = isUncalibrated(node ?? null, meta);
            return (
              <tr key={meta.key}>
                <th scope="row">{meta.label}</th>
                <td className="ncell__value">
                  {r ? formatMetricValue(meta, r.value) : "—"}
                  <em>{r ? unitFor(node ?? null, meta) : ""}</em>
                </td>
                <td className="ncell__bar">
                  <ThresholdBar
                    metric={meta.key}
                    value={r?.value ?? null}
                    uncalibrated={uncal}
                    label={meta.label}
                  />
                </td>
                <td className="ncell__spark">
                  <Sparkline points={trends?.[meta.key]} stale={offline} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </article>
  );
});

/**
 * ⑤ 노드별 센서 데이터 2×2.
 *
 * 배치 순서는 ① 사선 탑뷰 화면의 사분면과 일치해야 한다. 순서를 여기 적지 않고
 * utils/coordinates 의 SENSOR_SCREEN_ORDER 를 쓰는 이유가 그것이다 — 좌표나
 * 카메라가 바뀌면 coordinates.test.ts 가 먼저 깨진다.
 */
export function NodeMetricsGrid() {
  return (
    <div className="panel-5__grid">
      {SENSOR_SCREEN_ORDER.map((id) => (
        <NodeMetricsCell key={id} nodeId={id} />
      ))}
    </div>
  );
}
