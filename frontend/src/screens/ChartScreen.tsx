import { useEffect, useMemo, useState } from "react";
import { MetricChart } from "../components/MetricChart";
import { fetchSensorData, type SensorDataPoint } from "../services/api";
import { useDashboardStore } from "../store/dashboardStore";
import type { MetricKey } from "../types";
import { formatMetricValue, NODE_METRICS, type MetricMeta } from "../utils/metrics";

const RANGES_MIN = [60, 360, 1440, 10080] as const;
const DEFAULT_RANGE_MIN = 60;
type MetricData = Partial<Record<MetricKey, SensorDataPoint[]>>;
type NodeMetricData = Record<string, MetricData>;
const SENSOR_IDS = ["sensor-01", "sensor-02", "sensor-03", "sensor-04"] as const;

function rangeLabel(minutes: number): string {
  if (minutes >= 10080) return "7일";
  if (minutes >= 1440) return "24시간";
  if (minutes >= 360) return "6시간";
  return "1시간";
}

function trendLabel(rows: SensorDataPoint[]): string {
  if (rows.length < 2) return "→ 변화 없음";
  const delta = rows.at(-1)!.value - rows[0].value;
  if (Math.abs(delta) < 0.001) return "→ 유지";
  return delta > 0 ? "↗ 상승" : "↘ 하락";
}

export function buildWideCsv(metrics: readonly MetricMeta[], nodeData: NodeMetricData): string {
  const header = ["time", "node_id", ...metrics.map((metric) => metric.key)];
  const rows = [header.join(",")];

  for (const [nodeId, data] of Object.entries(nodeData).sort(([a], [b]) => a.localeCompare(b))) {
    const byTime = new Map<string, Partial<Record<MetricKey, number>>>();
    for (const metric of metrics) {
      for (const point of data[metric.key] ?? []) {
        const values = byTime.get(point.time) ?? {};
        values[metric.key] = point.value;
        byTime.set(point.time, values);
      }
    }

    const latest: Partial<Record<MetricKey, number>> = {};
    for (const time of [...byTime.keys()].sort()) {
      Object.assign(latest, byTime.get(time));
      rows.push([
        time,
        nodeId,
        ...metrics.map((metric) => latest[metric.key] ?? ""),
      ].join(","));
    }
  }
  return rows.join("\n");
}

function downloadCsv(filename: string, metrics: readonly MetricMeta[], nodeData: NodeMetricData): void {
  const blob = new Blob(["\uFEFF", buildWideCsv(metrics, nodeData)], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

export function ChartScreen() {
  const nodes = useDashboardStore((s) => s.sensor_nodes);
  const nodeIds = Object.keys(nodes).filter((id) => id.startsWith("sensor-"));
  const defaultNode = nodeIds[0] ?? "sensor-01";
  const [nodeId, setNodeId] = useState(defaultNode);
  const [selectedKeys, setSelectedKeys] = useState<MetricKey[]>(NODE_METRICS.map((m) => m.key));
  const [rangeMin, setRangeMin] = useState(DEFAULT_RANGE_MIN);
  const [use1min, setUse1min] = useState(false);
  const [data, setData] = useState<MetricData>({});
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [queryVersion, setQueryVersion] = useState(0);
  const selectedNode = nodes[nodeId];
  const selectedMetrics = useMemo(
    () => NODE_METRICS.filter((metric) => selectedKeys.includes(metric.key)),
    [selectedKeys],
  );

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    const start = new Date(Date.now() - rangeMin * 60_000).toISOString();
    const end = new Date().toISOString();
    Promise.all(selectedMetrics.map(async (metric) => [
      metric.key,
      await fetchSensorData(nodeId, metric.key, start, end, use1min ? "1min" : undefined),
    ] as const))
      .then((entries) => { if (!cancelled) setData(Object.fromEntries(entries) as MetricData); })
      .catch((reason: unknown) => { if (!cancelled) setError(reason instanceof Error ? reason.message : String(reason)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [nodeId, selectedMetrics, rangeMin, use1min, queryVersion]);

  const toggleMetric = (key: MetricKey) => setSelectedKeys((current) => {
    if (current.includes(key)) return current.length === 1 ? current : current.filter((item) => item !== key);
    return [...current, key];
  });

  const downloadAllSensors = async () => {
    setExporting(true);
    setError(null);
    const start = new Date(Date.now() - rangeMin * 60_000).toISOString();
    const end = new Date().toISOString();
    try {
      const entries = await Promise.all(SENSOR_IDS.map(async (sensorId) => {
        const metricEntries = await Promise.all(selectedMetrics.map(async (metric) => [
          metric.key,
          await fetchSensorData(sensorId, metric.key, start, end, use1min ? "1min" : undefined),
        ] as const));
        return [sensorId, Object.fromEntries(metricEntries) as MetricData] as const;
      }));
      downloadCsv(
        `sensor-01-04-${selectedMetrics.length === NODE_METRICS.length ? "all-metrics" : "selected"}.csv`,
        selectedMetrics,
        Object.fromEntries(entries),
      );
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="screen chart-screen chart-screen--overview">
      <div className="chart-heading">
        <div><p className="chart-kicker">ANALYZE / SIX-SENSOR OVERVIEW</p><h2 className="chart-title">센서 추세 분석</h2></div>
        <div className="chart-heading-tools">
          <div className="chart-heading-meta" aria-label="차트 조회 상태">
            <span>{nodeId}</span><span>{selectedMetrics.length === 6 ? "6종 전체" : `${selectedMetrics.length}종 선택`}</span><span>{rangeLabel(rangeMin)}</span>
          </div>
          <div className="chart-export-actions" aria-label="CSV 내보내기">
            <button type="button" className="chart-action" onClick={() => downloadCsv(`${nodeId}-${selectedMetrics.length === NODE_METRICS.length ? "all-metrics" : "selected"}.csv`, selectedMetrics, { [nodeId]: data })} disabled={loading || selectedMetrics.every((m) => (data[m.key]?.length ?? 0) === 0)}>↓ 선택 센서 CSV</button>
            <button type="button" className="chart-action chart-action--export" onClick={downloadAllSensors} disabled={loading || exporting}>↓ 센서 1~4 전체 CSV</button>
          </div>
        </div>
      </div>

      <section className="panel chart-controls chart-controls--overview">
        <label className="control"><span className="control-label">NODE</span><select value={nodeId} onChange={(e) => setNodeId(e.target.value)}>
          {nodeIds.length === 0 && <option value={defaultNode}>{defaultNode}</option>}
          {nodeIds.map((id) => <option key={id} value={id}>{id}</option>)}
        </select></label>
        <div className="chart-metric-filter"><span className="control-label">표시 항목</span><div className="chart-metric-chips">
          <button type="button" className={selectedMetrics.length === 6 ? "is-active" : ""} onClick={() => setSelectedKeys(NODE_METRICS.map((m) => m.key))}>전체 6종</button>
          {NODE_METRICS.map((metric) => <button key={metric.key} type="button" className={selectedKeys.includes(metric.key) ? "is-active" : ""} aria-pressed={selectedKeys.includes(metric.key)} onClick={() => toggleMetric(metric.key)}>{metric.label}</button>)}
        </div></div>
        <label className="control"><span className="control-label">RANGE</span><select value={String(rangeMin)} onChange={(e) => setRangeMin(Number(e.target.value))}>
          {RANGES_MIN.map((minutes) => <option key={minutes} value={minutes}>{rangeLabel(minutes)}</option>)}
        </select></label>
        <label className="control control-checkbox"><input type="checkbox" checked={use1min} onChange={(e) => setUse1min(e.target.checked)} /><span>1분 평균</span></label>
        <div className="chart-actions">
          <button type="button" className="chart-action chart-action--primary" onClick={() => setQueryVersion((v) => v + 1)} disabled={loading}>↻ 조회</button>
        </div>
      </section>

      {error && <p className="panel panel-empty panel-error">조회 실패: {error}</p>}
      <section className={`chart-overview-grid${selectedMetrics.length === 1 ? " is-single" : ""}`} aria-busy={loading}>
        {selectedMetrics.map((metric) => {
          const rows = data[metric.key] ?? [];
          const values = rows.map((row) => row.value);
          const latest = values.at(-1);
          const height = selectedMetrics.length === 1 ? 360 : 190;
          return <article key={metric.key} className="panel chart-metric-card">
            <header className="chart-metric-card__head"><div><span>{metric.label}</span><small>{metric.unit}</small></div><strong>{latest === undefined ? "—" : formatMetricValue(metric, latest)} <small>{latest === undefined ? "" : metric.unit}</small></strong></header>
            <div className="chart-metric-card__stats"><span>최소 <b>{values.length ? formatMetricValue(metric, Math.min(...values)) : "—"}</b></span><span>최대 <b>{values.length ? formatMetricValue(metric, Math.max(...values)) : "—"}</b></span><span>{trendLabel(rows)}</span><span>{rows.length} points</span></div>
            {loading ? <div className="metric-chart-empty" style={{ height }}>불러오는 중…</div> : <MetricChart data={rows} metric={metric.key} sourceMode={selectedNode?.source_mode} height={height} />}
          </article>;
        })}
      </section>
    </div>
  );
}
