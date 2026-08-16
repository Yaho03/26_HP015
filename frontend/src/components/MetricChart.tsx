import { useMemo } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { MetricKey } from "../types";
import type { SensorNodeState } from "../types";
import type { SensorDataPoint } from "../services/api";
import { thresholdLinesFor } from "../utils/alerts";

interface MetricChartProps {
  data: SensorDataPoint[];
  metric: MetricKey;
  sourceMode?: SensorNodeState["source_mode"];
  height?: number;
}

const METRIC_UNIT: Record<MetricKey, string> = {
  co2_ppm: "ppm",
  co_ppm: "ppm",
  h2s_ppm: "ppm",
  temperature_c: "°C",
  humidity_pct: "%",
  gas_resistance_ohm: "Ω",
  o2_pct: "%",
};

const LEVEL_COLOR: Record<string, string> = {
  level1_caution: "#facc15",
  level2_warning: "#fb923c",
  level3_critical: "#ef4444",
};

const LEVEL_SHORT_LABEL: Record<string, string> = {
  level1_caution: "L1",
  level2_warning: "L2",
  level3_critical: "L3",
};

function formatTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleTimeString("en-US", { hour12: false, hour: "2-digit", minute: "2-digit" });
}

export function MetricChart({ data, metric, sourceMode, height = 320 }: MetricChartProps) {
  const unit = METRIC_UNIT[metric] ?? "";
  const thresholds = useMemo(() => thresholdLinesFor(metric), [metric]);
  const chartData = useMemo(
    () => data.map((p) => ({ time: p.time, value: p.value })),
    [data],
  );

  if (chartData.length === 0) {
    return (
      <div className="metric-chart-empty" style={{ height }}>
        데이터가 없습니다.
      </div>
    );
  }

  return (
    <div className="metric-chart" style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={chartData} margin={{ top: 12, right: 24, bottom: 8, left: 0 }}>
          <CartesianGrid stroke="#2a3142" strokeDasharray="3 3" />
          <XAxis
            dataKey="time"
            tickFormatter={formatTime}
            stroke="#6b7280"
            tick={{ fontSize: 11 }}
          />
          <YAxis
            stroke="#6b7280"
            tick={{ fontSize: 11 }}
            label={unit ? { value: unit, angle: -90, position: "insideLeft", fill: "#6b7280", fontSize: 11 } : undefined}
          />
          <Tooltip
            contentStyle={{ background: "#1f2633", border: "1px solid #2a3142", color: "#e6e9ef", fontSize: 12 }}
            labelFormatter={(label) => formatTime(typeof label === "string" ? label : "")}
            formatter={(value) => [`${value} ${unit}`, metric]}
          />
          {thresholds.map((t) => (
            <ReferenceLine
              key={t.level}
              y={t.value}
              stroke={LEVEL_COLOR[t.level] ?? "#6b7280"}
              strokeDasharray="4 4"
              label={{ value: LEVEL_SHORT_LABEL[t.level] ?? t.level, fill: LEVEL_COLOR[t.level] ?? "#6b7280", fontSize: 10, position: "right" }}
            />
          ))}
          <Line
            type="monotone"
            dataKey="value"
            stroke="#3b82f6"
            strokeWidth={2}
            strokeDasharray={sourceMode === "simulation" ? "6 4" : undefined}
            dot={false}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
