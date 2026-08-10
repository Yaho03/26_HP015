import { useEffect, useState } from "react";
import { MetricChart } from "../components/MetricChart";
import { fetchSensorData, type SensorDataPoint } from "../services/api";
import { useDashboardStore } from "../store/dashboardStore";
import type { MetricKey } from "../types";

const METRICS: { key: MetricKey; label: string }[] = [
  { key: "co2_ppm", label: "CO₂" },
  { key: "co_ppm", label: "CO" },
  { key: "h2s_ppm", label: "H₂S" },
  { key: "temperature_c", label: "온도" },
  { key: "humidity_pct", label: "습도" },
  { key: "o2_pct", label: "O₂" },
];

const RANGES_MIN = [5, 30, 60, 180] as const;
const DEFAULT_RANGE_MIN = 30;

function isoMinutesAgo(min: number): string {
  return new Date(Date.now() - min * 60 * 1000).toISOString();
}
function isoNow(): string {
  return new Date().toISOString();
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
  }, [nodeId, metric, rangeMin, use1min]);

  return (
    <div className="screen chart-screen">
      <section className="panel chart-controls">
        <label className="control">
          <span className="control-label">Node</span>
          <select value={nodeId} onChange={(e) => setNodeId(e.target.value)}>
            {nodeIds.length === 0 ? <option value={defaultNode}>{defaultNode}</option> : null}
            {nodeIds.map((id) => (
              <option key={id} value={id}>{id}</option>
            ))}
          </select>
        </label>
        <label className="control">
          <span className="control-label">Metric</span>
          <select value={metric} onChange={(e) => setMetric(e.target.value as MetricKey)}>
            {METRICS.map((m) => (
              <option key={m.key} value={m.key}>{m.label}</option>
            ))}
          </select>
        </label>
        <label className="control">
          <span className="control-label">Range</span>
          <select
            value={String(rangeMin)}
            onChange={(e) => setRangeMin(Number(e.target.value))}
          >
            {RANGES_MIN.map((m) => (
              <option key={m} value={m}>{m}분</option>
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
      </section>

      <section className="panel chart-panel">
        <h2 className="panel-title">
          {nodeId} · {metric} · 최근 {rangeMin}분{use1min ? " (1분 평균)" : ""}
        </h2>
        {loading && <p className="panel-empty">불러오는 중…</p>}
        {error && (
          <p className="panel-empty panel-error">조회 실패: {error}</p>
        )}
        {!loading && !error && <MetricChart data={data} metric={metric} />}
      </section>
    </div>
  );
}
