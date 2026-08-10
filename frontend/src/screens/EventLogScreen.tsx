import { useEffect, useState } from "react";
import { fetchAlertEvents, type AlertEvent, type AlertEventFilter } from "../services/api";

const STATUS_OPTIONS: { value: "" | "active" | "resolved"; label: string }[] = [
  { value: "", label: "전체" },
  { value: "active", label: "활성" },
  { value: "resolved", label: "해제" },
];

const LIMIT_OPTIONS = [50, 100, 200, 500];

function formatTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString("en-US", { hour12: false });
}

function levelClass(level: string): string {
  if (level === "level3_critical") return "event-level level3_critical";
  if (level === "level2_warning") return "event-level level2_warning";
  if (level === "level1_caution") return "event-level level1_caution";
  return "event-level";
}

export function EventLogScreen() {
  const [nodeId, setNodeId] = useState("");
  const [alertKey, setAlertKey] = useState("");
  const [status, setStatus] = useState<"" | "active" | "resolved">("");
  const [limit, setLimit] = useState(100);
  const [events, setEvents] = useState<AlertEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const filter: AlertEventFilter = { limit };
    if (nodeId) filter.nodeId = nodeId;
    if (alertKey) filter.alertKey = alertKey;
    if (status) filter.status = status;

    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchAlertEvents(filter)
      .then((rows) => {
        if (!cancelled) setEvents(rows);
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
  }, [nodeId, alertKey, status, limit]);

  return (
    <div className="screen event-log-screen">
      <section className="panel event-filters">
        <label className="control">
          <span className="control-label">Node ID</span>
          <input
            type="text"
            value={nodeId}
            onChange={(e) => setNodeId(e.target.value)}
            placeholder="예: sensor-01"
          />
        </label>
        <label className="control">
          <span className="control-label">Alert Key</span>
          <input
            type="text"
            value={alertKey}
            onChange={(e) => setAlertKey(e.target.value)}
            placeholder="예: co2_ppm, o2_low"
          />
        </label>
        <label className="control">
          <span className="control-label">Status</span>
          <select value={status} onChange={(e) => setStatus(e.target.value as typeof status)}>
            {STATUS_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </label>
        <label className="control">
          <span className="control-label">Limit</span>
          <select value={String(limit)} onChange={(e) => setLimit(Number(e.target.value))}>
            {LIMIT_OPTIONS.map((n) => (
              <option key={n} value={n}>{n}</option>
            ))}
          </select>
        </label>
      </section>

      <section className="panel event-list-panel">
        <h2 className="panel-title">
          Alert Events ({events.length}{loading ? " · loading" : ""})
        </h2>
        {error && <p className="panel-empty panel-error">조회 실패: {error}</p>}
        {!error && !loading && events.length === 0 && (
          <p className="panel-empty">이벤트가 없습니다.</p>
        )}
        {events.length > 0 && (
          <table className="event-table">
            <thead>
              <tr>
                <th>Activated</th>
                <th>Node</th>
                <th>Alert Key</th>
                <th>Level</th>
                <th>Status</th>
                <th>Value</th>
                <th>Threshold</th>
                <th>Resolved</th>
              </tr>
            </thead>
            <tbody>
              {events.map((ev) => (
                <tr key={ev.message_id} className={ev.status === "active" ? "event-row-active" : ""}>
                  <td className="cell-time">{formatTime(ev.activated_at)}</td>
                  <td>{ev.source_node_id}</td>
                  <td>{ev.alert_key}</td>
                  <td><span className={levelClass(ev.level)}>{ev.level}</span></td>
                  <td>
                    <span className={"event-status event-status-" + ev.status}>{ev.status}</span>
                  </td>
                  <td className="cell-num">
                    {ev.trigger_value !== null ? ev.trigger_value.toFixed(1) : "—"}
                  </td>
                  <td className="cell-num">
                    {ev.threshold !== null ? ev.threshold : "—"}
                  </td>
                  <td className="cell-time">{formatTime(ev.resolved_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
