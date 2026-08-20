import { useEffect, useMemo, useState } from "react";
import { fetchAlertEvents, type AlertEvent, type AlertEventFilter } from "../services/api";

const STATUS_OPTIONS: { value: "" | "active" | "resolved"; label: string }[] = [
  { value: "", label: "전체" },
  { value: "active", label: "활성" },
  { value: "resolved", label: "해제" },
];

const LIMIT_OPTIONS = [50, 100, 200, 500];
const NODE_OPTIONS = ["", "sensor-01", "sensor-02", "sensor-03", "sensor-04", "wearable-01"];
const DATE_OPTIONS: { value: "" | "today" | "7d" | "30d"; label: string }[] = [
  { value: "", label: "전체 기간" },
  { value: "today", label: "오늘" },
  { value: "7d", label: "최근 7일" },
  { value: "30d", label: "최근 30일" },
];
const LEVEL_OPTIONS = [
  { value: "", label: "전체 등급" },
  { value: "level1_caution", label: "L1 주의" },
  { value: "level2_warning", label: "L2 경고" },
  { value: "level3_critical", label: "L3 위험" },
];
const TYPE_OPTIONS = [
  { value: "", label: "전체 유형" },
  { value: "gas_threshold", label: "가스 임계값" },
  { value: "fall_detection", label: "낙상 감지" },
  { value: "o2_low", label: "O₂ 저농도" },
  { value: "o2_high", label: "O₂ 고농도" },
  { value: "zone_intrusion", label: "위험 구역 진입" },
  { value: "connection_lost", label: "연결 끊김" },
];

const TYPE_LABEL: Record<string, string> = Object.fromEntries(
  TYPE_OPTIONS.filter((option) => option.value).map((option) => [option.value, option.label]),
);

const LEVEL_LABEL: Record<string, string> = {
  level1_caution: "L1 주의",
  level2_warning: "L2 경고",
  level3_critical: "L3 위험",
};

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

function startIsoFor(range: "" | "today" | "7d" | "30d"): string | undefined {
  if (!range) return undefined;
  const start = new Date();
  if (range === "today") {
    start.setHours(0, 0, 0, 0);
  } else {
    start.setDate(start.getDate() - (range === "7d" ? 7 : 30));
  }
  return start.toISOString();
}

function formatType(type: string): string {
  return TYPE_LABEL[type] ?? type;
}

export function EventLogScreen() {
  const [nodeId, setNodeId] = useState("");
  const [alertKey, setAlertKey] = useState("");
  const [status, setStatus] = useState<"" | "active" | "resolved">("");
  const [dateRange, setDateRange] = useState<"" | "today" | "7d" | "30d">("");
  const [level, setLevel] = useState("");
  const [alertType, setAlertType] = useState("");
  const [limit, setLimit] = useState(100);
  const [events, setEvents] = useState<AlertEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [refreshVersion, setRefreshVersion] = useState(0);

  useEffect(() => {
    const filter: AlertEventFilter = { limit, start: startIsoFor(dateRange) };
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
  }, [nodeId, alertKey, status, dateRange, limit, refreshVersion]);

  const visibleEvents = useMemo(
    () => events.filter((event) => {
      if (level && event.level !== level) return false;
      if (alertType && event.alert_type !== alertType) return false;
      return true;
    }),
    [events, level, alertType],
  );
  const activeCount = visibleEvents.filter((event) => event.status === "active").length;

  return (
    <div className="screen event-log-screen">
      <div className="event-log-heading">
        <div>
          <p className="event-kicker">REVIEW / ALERT HISTORY</p>
          <h2 className="event-log-title">경보 이벤트 로그</h2>
        </div>
        <div className="event-log-meta" aria-label="이벤트 로그 요약">
          <span><small>SHOWN</small><strong>{visibleEvents.length}</strong></span>
          <span><small>ACTIVE</small><strong className={activeCount > 0 ? "event-meta-alert" : ""}>{activeCount}</strong></span>
          <button
            type="button"
            className="event-refresh"
            onClick={() => setRefreshVersion((version) => version + 1)}
            disabled={loading}
          >
            <span aria-hidden="true">↻</span> 새로고침
          </button>
        </div>
      </div>

      <section className="panel event-filters">
        <label className="control">
          <span className="control-label">DATE</span>
          <select value={dateRange} onChange={(e) => setDateRange(e.target.value as typeof dateRange)}>
            {DATE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </select>
        </label>
        <label className="control">
          <span className="control-label">LEVEL</span>
          <select value={level} onChange={(e) => setLevel(e.target.value)}>
            {LEVEL_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </select>
        </label>
        <label className="control">
          <span className="control-label">NODE</span>
          <select value={nodeId} onChange={(e) => setNodeId(e.target.value)}>
            {NODE_OPTIONS.map((id) => (
              <option key={id} value={id}>{id || "전체 노드"}</option>
            ))}
          </select>
        </label>
        <label className="control">
          <span className="control-label">TYPE</span>
          <select value={alertType} onChange={(e) => setAlertType(e.target.value)}>
            {TYPE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </select>
        </label>
        <label className="control">
          <span className="control-label">STATUS</span>
          <select value={status} onChange={(e) => setStatus(e.target.value as typeof status)}>
            {STATUS_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </label>
        <label className="control event-filter-key">
          <span className="control-label">ALERT KEY</span>
          <input
            type="text"
            value={alertKey}
            onChange={(e) => setAlertKey(e.target.value)}
            placeholder="co2_ppm"
          />
        </label>
        <label className="control">
          <span className="control-label">LIMIT</span>
          <select value={String(limit)} onChange={(e) => setLimit(Number(e.target.value))}>
            {LIMIT_OPTIONS.map((n) => (
              <option key={n} value={n}>{n}건</option>
            ))}
          </select>
        </label>
      </section>

      <section className="panel event-list-panel">
        <div className="event-list-head">
          <div>
            <p className="event-kicker">AUDIT TRAIL</p>
            <h2 className="panel-title">최근 경보 이력</h2>
          </div>
          <span className="event-list-count">{loading ? "LOADING" : `${visibleEvents.length} EVENTS`}</span>
        </div>
        {error && <p className="panel-empty panel-error">조회 실패: {error}</p>}
        {!error && !loading && visibleEvents.length === 0 && (
          <p className="panel-empty">조건에 맞는 이벤트가 없습니다.</p>
        )}
        {visibleEvents.length > 0 && (
          <div className="event-table-wrap">
            <table className="event-table">
              <thead>
                <tr>
                  <th>시각</th>
                  <th>노드</th>
                  <th>유형</th>
                  <th>등급</th>
                  <th>메시지</th>
                  <th>상태</th>
                  <th>측정값</th>
                  <th>해제 시각</th>
                </tr>
              </thead>
              <tbody>
                {visibleEvents.map((ev) => (
                  <tr key={ev.message_id} className={ev.status === "active" ? "event-row-active" : ""}>
                    <td className="cell-time">{formatTime(ev.activated_at)}</td>
                    <td className="event-node">{ev.source_node_id}</td>
                    <td>
                      <span className="event-type">{formatType(ev.alert_type)}</span>
                      <span className="event-key">{ev.alert_key}</span>
                    </td>
                    <td><span className={levelClass(ev.level)}>{LEVEL_LABEL[ev.level] ?? ev.level}</span></td>
                    <td className="event-message">{ev.message || "—"}</td>
                    <td><span className={"event-status event-status-" + ev.status}>{ev.status === "active" ? "활성" : "해제"}</span></td>
                    <td className="cell-num">
                      {ev.trigger_value !== null ? ev.trigger_value.toFixed(1) : "—"}
                      {ev.threshold !== null && <span className="event-threshold"> / {ev.threshold}</span>}
                    </td>
                    <td className="cell-time">{formatTime(ev.resolved_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
