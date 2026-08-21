import { memo, type ComponentType } from "react";
import type { AlertLevel, SensorNodeState, WearableState } from "../types";
import type { TrendPoint, TrendMetric } from "../store/dashboardStore";
import {
  classifyMetric,
  classifyO2High,
  classifyO2Low,
  levelLabel,
  maxLevel,
} from "../utils/alerts";
import {
  ASPHYXIANT_METRICS,
  CHIP_LABEL,
  formatMetricValue,
  isUncalibrated,
  metricChipState,
  NODE_METRICS,
  unitFor,
  type MetricMeta,
} from "../utils/metrics";
import { shortNodeLabel, sourceBadge } from "../utils/nodes";
import { projectThresholdCrossing } from "../utils/trend";
import { LEVEL_ICON, IconClock } from "./icons";
import { Sparkline } from "./Sparkline";
import { ThresholdBar } from "./ThresholdBar";

const CO2 = NODE_METRICS[0];
/** CO₂ 를 뺀 나머지 질식 가스 — 수치 없이 상태 칩으로만 보이는 것들. */
const CHIP_METRICS = ASPHYXIANT_METRICS.filter((m) => m.key !== "co2_ppm");

type Trends = Partial<Record<TrendMetric, TrendPoint[]>>;

interface SensorSummaryPanelProps {
  /** ② 로 승격되지 않은 노드만 온다. 두 칸에 중복 표시하지 않는다. */
  nodeIds: string[];
  nodes: Record<string, SensorNodeState>;
  trends: Record<string, Trends>;
  wearable: WearableState | null;
  levelOf: (nodeId: string) => AlertLevel;
}

/**
 * 미교정 MQ 센서의 상태 칩.
 *
 * Rs/R0 저항비를 ppm 처럼 큰 수치로 띄우면 오독을 부른다. 그래서 이 칸에서는
 * **수치를 숨기고** 상태와 임계 근접 바만 보인다. 실제 값이 필요하면 카드를
 * 펼치거나 ⑤ 표를 본다.
 */
function MetricChip({ meta, node }: { meta: MetricMeta; node: SensorNodeState | null }) {
  const state = metricChipState(node, meta);
  const reading = node?.readings[meta.key];
  const level: AlertLevel =
    state === "graded" && reading ? classifyMetric(meta.key, reading.value) : "unknown";

  const text = state === "graded" ? levelLabel(level).replace(/^L\d\s/, "") : CHIP_LABEL[state];

  return (
    <span className={"mchip is-" + level}>
      <span className="mchip__label">{meta.label}</span>
      <span className="mchip__state">{text}</span>
      <ThresholdBar
        metric={meta.key}
        value={reading?.value ?? null}
        uncalibrated={isUncalibrated(node, meta)}
        label={meta.label}
      />
    </span>
  );
}

/** 펼침 시 보이는 6종 전체. 기본은 접혀 있어야 카드가 낮게 유지된다. */
function AllMetrics({ node, trends }: { node: SensorNodeState | null; trends: Trends }) {
  return (
    <dl className="scard__all-list">
      {NODE_METRICS.map((meta) => {
        const r = node?.readings[meta.key];
        return (
          <div className="scard__all-row" key={meta.key}>
            <dt>{meta.label}</dt>
            <dd>{r ? `${formatMetricValue(meta, r.value)} ${unitFor(node, meta)}` : "—"}</dd>
            <Sparkline points={trends[meta.key]} />
          </div>
        );
      })}
    </dl>
  );
}

const SummaryCard = memo(function SummaryCard({
  nodeId,
  node,
  trends,
  level,
}: {
  nodeId: string;
  node: SensorNodeState | null;
  trends: Trends;
  level: AlertLevel;
}) {
  const offline = node?.connection_status === "offline";
  const sim = node?.source_mode === "simulation";
  const co2 = node?.readings.co2_ppm ?? null;
  const LevelIcon = LEVEL_ICON[level] as ComponentType<{
    size?: number | string;
  }>;

  // 06_ALERT_RULES §8.2 — 등급이 오르기 전에 알리는 선제 표시. 경보를 발령하지
  // 않고 배지로만 알린다. 아직 위험하지 않은 노드가 모이는 이 칸이 제자리다.
  // 오프라인 노드의 멈춘 버퍼로 미래를 예측하지 않는다.
  const projection =
    !offline && trends.co2_ppm ? projectThresholdCrossing(trends.co2_ppm, "co2_ppm") : null;

  return (
    <article
      className={
        "scard is-" +
        level +
        (offline ? " scard--offline" : "") +
        (sim ? " scard--sim" : "") +
        (node ? "" : " scard--pending")
      }
      aria-label={`${shortNodeLabel(nodeId)} ${levelLabel(level)}`}
    >
      {/* 등급을 색 하나로 전달하지 않는다 — 브래킷 + 아이콘 + 텍스트가 함께 나른다. */}
      <i className="brk brk--tl" aria-hidden="true" />
      <i className="brk brk--br" aria-hidden="true" />

      <header className="scard__head">
        {offline || !node ? <IconClock size={13} /> : <LevelIcon size={13} />}
        <span className="scard__id">{shortNodeLabel(nodeId)}</span>
        <span className="scard__level">
          {offline ? "연결 끊김" : node ? levelLabel(level) : "대기"}
        </span>
        <span className={"scard__src" + (sim ? " scard__src--sim" : "")}>
          {sourceBadge(node?.source_mode, !!node)}
        </span>
      </header>

      {/* 유일하게 교정된 값이라 이것만 큰 수치로 띄운다. */}
      <div className="scard__co2">
        <span className="scard__co2-value">{co2 ? formatMetricValue(CO2, co2.value) : "—"}</span>
        <span className="scard__co2-unit">ppm</span>
        <Sparkline points={trends.co2_ppm} stale={offline} className="scard__co2-spark" />
      </div>

      <div className="scard__chips">
        {CHIP_METRICS.map((meta) => (
          <MetricChip key={meta.key} meta={meta} node={node} />
        ))}
      </div>

      {projection && (
        <p className={"scard__projection is-" + projection.level}>
          <span aria-hidden="true">↗</span>
          추세 유지 시 약 {Math.round(projection.minutes)}분 뒤 {levelLabel(projection.level)}
        </p>
      )}

      {/* 클릭으로 펼친다. 호버 펼침은 관제 화면에서 마우스를 스쳐 지나갈 때마다
          카드가 튀어 오히려 스캔을 방해한다. details 는 키보드로도 열린다. */}
      <details className="scard__all">
        <summary>6종 전체</summary>
        <AllMetrics node={node} trends={trends} />
      </details>
    </article>
  );
});

/**
 * ③ 센서 4종 + 웨어러블 요약.
 *
 * 정상 상태에서 이 칸이 화면 대부분을 쓰고, 주의 이상 노드가 생기면 그 노드를
 * ②로 넘겨주며 줄어든다. 그래서 카드 높이를 짧게 유지하는 것이 이 칸의 제약이다.
 */
export function SensorSummaryPanel({
  nodeIds,
  nodes,
  trends,
  wearable,
  levelOf,
}: SensorSummaryPanelProps) {
  const o2 = wearable?.o2_pct ?? null;
  // O₂ 값이 없으면 판정 불가다 (이슈 #165). 측정 못 한 것을 정상이라 하면 안 된다.
  const o2Level: AlertLevel =
    o2 !== null ? maxLevel(classifyO2Low(o2), classifyO2High(o2)) : "unknown";
  const O2Icon = LEVEL_ICON[o2Level] as ComponentType<{
    size?: number | string;
  }>;

  return (
    <section className="panel-3" aria-label="센서 요약">
      {/* O₂ 는 웨어러블에만 있고 센서 노드에는 없다. 카드마다 반복하지 않고
          칸 헤더에 한 번만 표시한다 (10_UI_FLOW §8.5). */}
      <header className={"panel-3__head is-" + o2Level}>
        <span className="panel-3__title">센서 요약</span>
        <span className="panel-3__o2">
          <O2Icon size={13} />
          <span className="panel-3__o2-label">공간 O₂</span>
          <strong>{o2 !== null ? `${o2.toFixed(1)}%` : "—"}</strong>
          <span className="panel-3__o2-level">{levelLabel(o2Level)}</span>
        </span>
        <span className="panel-3__o2-note">센서 응답 지연 가능성 (최대 15초)</span>
      </header>

      <div className="panel-3__grid">
        {nodeIds.map((id) => (
          <SummaryCard
            key={id}
            nodeId={id}
            node={nodes[id] ?? null}
            trends={trends[id] ?? {}}
            level={levelOf(id)}
          />
        ))}
        {nodeIds.length === 0 && (
          <p className="panel-3__empty">모든 노드가 주의 이상입니다 — 위험 상세를 확인하세요.</p>
        )}
      </div>
    </section>
  );
}
