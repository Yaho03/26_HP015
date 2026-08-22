import { memo } from "react";
import type { CalibrationState, MetricKey, SensorNodeState } from "../types";
import { classifyMetric, classifyO2High, classifyO2Low, levelLabel } from "../utils/alerts";

interface NodeCardProps {
  node: SensorNodeState;
}

const METRIC_DISPLAY: { key: MetricKey; label: string; unit: string }[] = [
  { key: "co2_ppm", label: "CO₂", unit: "ppm" },
  { key: "co_ppm", label: "CO", unit: "ppm" },
  { key: "h2s_ppm", label: "H₂S", unit: "ppm" },
  { key: "temperature_c", label: "온도", unit: "°C" },
  { key: "humidity_pct", label: "습도", unit: "%" },
  { key: "o2_pct", label: "O₂", unit: "%" },
];

const CALIB_LABEL: Record<string, string> = {
  co_calibration_status: "CO",
  h2s_calibration_status: "H₂S",
  mq2_calibration_status: "MQ-2",
};

const CALIB_ICON: Record<CalibrationState, string> = {
  not_started: "○",
  in_progress: "◐",
  done: "●",
  error: "✗",
};

function levelClass(metric: MetricKey, value: number): string {
  if (metric === "o2_pct") {
    const low = classifyO2Low(value);
    const high = classifyO2High(value);
    if (low !== "normal") return `metric-${low}`;
    if (high !== "normal") return `metric-${high}`;
    return "metric-normal";
  }
  return `metric-${classifyMetric(metric, value)}`;
}

function formatValue(metric: MetricKey, value: number): string {
  if (metric === "co2_ppm" || metric === "gas_resistance_ohm") return Math.round(value).toString();
  if (metric === "humidity_pct" || metric === "o2_pct") return value.toFixed(1);
  if (metric === "temperature_c") return value.toFixed(1);
  return value.toString();
}

function formatLastSeen(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleTimeString("en-US", { hour12: false });
}

function batteryClass(pct: number | null): string {
  if (pct === null) return "battery-unknown";
  if (pct < 20) return "battery-low";
  if (pct < 50) return "battery-mid";
  return "battery-ok";
}

function rssiClass(dbm: number | null): string {
  if (dbm === null) return "rssi-unknown";
  if (dbm < -80) return "rssi-bad";
  if (dbm < -65) return "rssi-mid";
  return "rssi-ok";
}

export const NodeCard = memo(function NodeCard({ node }: NodeCardProps) {
  const calibrations = node.calibration_status ?? {};
  const calibrationEntries = Object.entries(calibrations).filter(([k]) => k in CALIB_LABEL);

  return (
    <article
      className={"node-card " + (node.connection_status === "offline" ? "node-card-offline" : "")}
    >
      <header className="node-card-header">
        <span className="node-id">{node.node_id}</span>
        <span
          className={
            "node-status " + (node.connection_status === "online" ? "node-online" : "node-offline")
          }
        >
          {node.connection_status}
        </span>
      </header>

      <div className="node-card-vitals">
        <span className={"vital-chip " + batteryClass(node.battery_pct)}>
          <span className="vital-label">BAT</span>
          <span className="vital-value">
            {node.battery_pct !== null ? `${node.battery_pct}%` : "—"}
          </span>
        </span>
        <span className={"vital-chip " + rssiClass(node.wifi_rssi_dbm)}>
          <span className="vital-label">RSSI</span>
          <span className="vital-value">
            {node.wifi_rssi_dbm !== null ? `${node.wifi_rssi_dbm}dBm` : "—"}
          </span>
        </span>
        <span className="vital-chip vital-seen">
          <span className="vital-label">SEEN</span>
          <span className="vital-value">{formatLastSeen(node.last_seen_at)}</span>
        </span>
      </div>

      <ul className="metric-list">
        {METRIC_DISPLAY.map(({ key, label, unit }) => {
          const reading = node.readings[key];
          if (!reading) return null;
          const cls = levelClass(key, reading.value);
          const levelText = levelLabel(
            key === "o2_pct"
              ? classifyO2Low(reading.value) !== "normal"
                ? classifyO2Low(reading.value)
                : classifyO2High(reading.value)
              : classifyMetric(key, reading.value),
          );
          return (
            <li key={key} className={"metric-row " + cls}>
              <span className="metric-label">{label}</span>
              <span className="metric-value">
                {formatValue(key, reading.value)}
                <span className="metric-unit"> {unit}</span>
              </span>
              <span className="metric-level">{levelText}</span>
            </li>
          );
        })}
      </ul>

      {calibrationEntries.length > 0 && (
        <footer className="node-card-calibration">
          {calibrationEntries.map(([key, state]) => (
            <span key={key} className={"calibration-chip calibration-" + state}>
              <span className="calibration-icon">{CALIB_ICON[state]}</span>
              <span className="calibration-name">{CALIB_LABEL[key]}</span>
            </span>
          ))}
        </footer>
      )}
    </article>
  );
});
