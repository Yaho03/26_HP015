import { type ComponentType } from "react";
import type { MetricKey, SensorNodeState } from "../types";
import { levelLabel, nodeAlertLevel } from "../utils/alerts";
import { IconClock, LEVEL_ICON } from "./icons";

interface LiveSensorPanelProps {
  slots: string[];
  nodes: Record<string, SensorNodeState>;
}

const READOUTS: { key: MetricKey; label: string; unit: string; digits: number }[] = [
  { key: "co2_ppm", label: "CO₂", unit: "ppm", digits: 0 },
  { key: "co_ppm", label: "CO", unit: "ppm", digits: 1 },
  { key: "h2s_ppm", label: "H₂S", unit: "ppm", digits: 1 },
  { key: "temperature_c", label: "온도", unit: "°C", digits: 1 },
];

function formatValue(value: number, digits: number): string {
  return digits === 0 ? Math.round(value).toString() : value.toFixed(digits);
}

function sampleTime(value: string | null): string {
  if (!value) return "sample pending";
  return new Date(value).toLocaleTimeString("ko-KR", { hour12: false });
}

export function LiveSensorPanel({ slots, nodes }: LiveSensorPanelProps) {
  return (
    <section className="panel monitor-live-sensors" aria-labelledby="live-sensors-title">
      <header className="monitor-live-sensors__head">
        <div>
          <p className="monitor-live-sensors__kicker">LIVE SENSOR READOUT</p>
          <h3 id="live-sensors-title">최신 센서값</h3>
        </div>
        <span className="monitor-live-sensors__source">CURRENT SAMPLE</span>
      </header>

      <div className="live-sensor-list">
        {slots.map((id) => {
          const node = nodes[id];
          if (!node) {
            return (
              <article className="live-sensor-row live-sensor-row--pending" key={id}>
                <div className="live-sensor-row__head">
                  <strong>{id}</strong>
                  <span className="live-sensor-state">
                    <IconClock size={11} /> 데이터 대기
                  </span>
                </div>
                <div className="live-sensor-values">
                  {READOUTS.map(({ key, label, unit }) => (
                    <span className="live-sensor-value" key={key}>
                      <small>{label}</small>
                      <b>—</b>
                      <em>{unit}</em>
                    </span>
                  ))}
                </div>
                <span className="live-sensor-meta">NO SAMPLE · SLOT RESERVED</span>
              </article>
            );
          }

          const level = nodeAlertLevel(node);
          const LevelIcon = LEVEL_ICON[level] as ComponentType<{ size?: number | string }>;
          return (
            <article
              className={`live-sensor-row is-${level}${node.connection_status === "offline" ? " live-sensor-row--offline" : ""}`}
              key={id}
            >
              <div className="live-sensor-row__head">
                <strong>{id}</strong>
                <span className="live-sensor-state">
                  <LevelIcon size={11} />{" "}
                  {node.connection_status === "offline" ? "연결 끊김" : levelLabel(level)}
                </span>
              </div>
              <div className="live-sensor-values">
                {READOUTS.map(({ key, label, unit, digits }) => {
                  const reading = node.readings[key];
                  return (
                    <span className="live-sensor-value" key={key}>
                      <small>{label}</small>
                      <b>{reading ? formatValue(reading.value, digits) : "—"}</b>
                      <em>{unit}</em>
                    </span>
                  );
                })}
              </div>
              <span className="live-sensor-meta">
                {node.source_mode === "simulation" ? "SIM" : "LIVE"} ·{" "}
                {sampleTime(node.last_seen_at)}
              </span>
            </article>
          );
        })}
      </div>
      <p className="monitor-live-sensors__foot">
        센서 선택 시 상세 이력은 차트 메뉴에서 확인합니다.
      </p>
    </section>
  );
}
