import { useEffect, useState } from "react";
import { MetricChart } from "../components/MetricChart";
import { fetchSensorData, type SensorDataPoint } from "../services/api";
import { useDashboardStore } from "../store/dashboardStore";
import { levelLabel, thresholdLinesFor } from "../utils/alerts";
import type { MetricKey } from "../types";

const METRICS: { key: MetricKey; label: string }[] = [
  { key: "co2_ppm", label: "CO₂" },
  { key: "co_ppm", label: "CO" },
  { key: "h2s_ppm", label: "H₂S" },
  { key: "temperature_c", label: "온도" },
  { key: "humidity_pct", label: "습도" },
  { key: "o2_pct", label: "O₂" },
];

const RANGES_MIN = [60, 360, 1440, 10080] as const;
const DEFAULT_RANGE_MIN = 60;

const METRIC_UNITS: Partial<Record<MetricKey, string>> = {
  co2_ppm: "ppm",
  co_ppm: "ppm",
  h2s_ppm: "ppm",
  temperature_c: "°C",
  humidity_pct: "%",
  o2_pct: "%",
};

function isoMinutesAgo(min: number): string {
  return new Date(Date.now() - min * 60 * 1000).toISOString();
}
function isoNow(): string {
  return new Date().toISOString();
}

function rangeLabel(rangeMin: number): string {
  if (rangeMin >= 10080) return "7일";
  if (rangeMin >= 1440) return "24시간";
  if (rangeMin >= 360) return "6시간";
  return "1시간";
}

function downloadCsv(nodeId: string, metric: MetricKey, rows: SensorDataPoint[]): void {
  const csv = [
    "time,value",
    ...rows.map((row) => `${row.time},${row.value}`),
  ].join("\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${nodeId}-${metric}.csv`;
  link.click();
  URL.revokeObjectURL(url);
}

export function ChartScreen() {
  const nodes = useDashboardStore((s) => s.sensor_nodes);
  const nodeIds = Object.keys(nodes);
  const defaultNode = nodeIds[0] ?? "sensor-01";

  const [nodeId, setNodeId] = useState(defaultNode);
  const [metric, setMetric] = useState<MetricKey>("co2_ppm");
  const [rangeMin, setRangeMin] = useState<number>(DEFAULT_RANGE_MIN);
  const [use1min, setUse1min] = useState(false);
  const [data, setData] = useState<SensorDataPoint[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [queryVersion, setQueryVersion] = useState(0);

  const selectedNode = nodes[nodeId];
  const metricLabel = METRICS.find((item) => item.key === metric)?.label ?? metric;
  const unit = METRIC_UNITS[metric] ?? "";
  const thresholds = thresholdLinesFor(metric);
  const latest = data[data.length - 1]?.value ?? null;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchSensorData(nodeId, metric, isoMinutesAgo(rangeMin), isoNow(), use1min ? "1min" : undefined)
      .then((rows) => {
        if (!cancelled) setData(rows);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [nodeId, metric, rangeMin, use1min, queryVersion]);

  return (
    <div className="screen chart-screen">
      <div className="chart-heading">
        <div>
          <p className="chart-kicker">ANALYZE / TIME SERIES</p>
          <h2 className="chart-title">센서 추세 분석</h2>
        </div>
        <div className="chart-heading-meta" aria-label="차트 조회 상태">
          <span>{nodeId}</span>
          <span>{metricLabel}{unit ? ` · ${unit}` : ""}</span>
          <span>{rangeLabel(rangeMin)}</span>
        </div>
      </div>
      <section className="panel chart-controls">
        <label className="control">
          <span className="control-label">NODE</span>
          <select value={nodeId} onChange={(e) => setNodeId(e.target.value)}>
            {nodeIds.length === 0 ? <option value={defaultNode}>{defaultNode}</option> : null}
            {nodeIds.map((id) => (
              <option key={id} value={id}>{id}</option>
            ))}
          </select>
        </label>
        <label className="control">
          <span className="control-label">METRIC</span>
          <select value={metric} onChange={(e) => setMetric(e.target.value as MetricKey)}>
            {METRICS.map((m) => (
              <option key={m.key} value={m.key}>{m.label}</option>
            ))}
          </select>
        </label>
        <label className="control">
          <span className="control-label">RANGE</span>
          <select
            value={String(rangeMin)}
            onChange={(e) => setRangeMin(Number(e.target.value))}
          >
            {RANGES_MIN.map((m) => (
              <option key={m} value={m}>{rangeLabel(m)}</option>
            ))}
          </select>
        </label>
        <label className="control control-checkbox">
          <input
            type="checkbox"
            checked={use1min}
            onChange={(e) => setUse1min(e.target.checked)}
          />
          <span>1분 평균</span>
        </label>
        <div className="chart-actions">
          <button
            type="button"
            className="chart-action chart-action--primary"
            onClick={() => setQueryVersion((version) => version + 1)}
            disabled={loading}
          >
            <span aria-hidden="true">↻</span> 조회
          </button>
          <button
            type="button"
            className="chart-action"
            onClick={() => downloadCsv(nodeId, metric, data)}
            disabled={data.length === 0 || loading}
          >
            <span aria-hidden="true">↓</span> CSV
          </button>
        </div>
      </section>

      <section className="panel chart-panel">
        <div className="chart-panel-head">
          <div>
            <p className="chart-kicker">MEASUREMENT TRACE</p>
            <h2 className="panel-title">
              {metricLabel} · {nodeId} · 최근 {rangeLabel(rangeMin)}{use1min ? " · 1분 평균" : ""}
            </h2>
          </div>
          <div className="chart-readout" aria-label="차트 데이터 요약">
            <span><small>POINTS</small><strong>{data.length}</strong></span>
            <span><small>LATEST</small><strong>{latest !== null ? `${latest.toFixed(1)}${unit ? ` ${unit}` : ""}` : "—"}</strong></span>
            {selectedNode?.source_mode === "simulation" && <span className="chart-source-badge">SIM</span>}
          </div>
        </div>
        <div className="chart-threshold-strip" aria-label="임계값 기준선">
          <span className="chart-threshold-title">THRESHOLDS</span>
          {thresholds.length > 0 ? thresholds.map((threshold) => (
            <span key={threshold.level} className={"chart-threshold chart-threshold--" + threshold.level}>
              {levelLabel(threshold.level)} ≥ {threshold.value}{unit ? ` ${unit}` : ""}
            </span>
          )) : <span className="chart-threshold-empty">기준선 없음</span>}
        </div>
        {loading && <p className="panel-empty">불러오는 중…</p>}
        {error && (
          <p className="panel-empty panel-error">조회 실패: {error}</p>
        )}
        {!loading && !error && <MetricChart data={data} metric={metric} sourceMode={selectedNode?.source_mode} />}
      </section>
    </div>
  );
}
