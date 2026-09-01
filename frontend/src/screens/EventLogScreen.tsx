import { useEffect, useMemo, useState } from "react";
import {
  fetchAlertEvents,
  fetchSensorData,
  type AlertEvent,
  type AlertEventFilter,
  type SensorDataPoint,
} from "../services/api";
import { ALERT_TYPE_LABEL } from "../utils/alertLabels";
import type { MetricKey } from "../types";

/** Screen 1 ④ 에서 행을 클릭해 넘어올 때 걸고 오는 초기 필터. */
export interface EventLogFilter {
  nodeId?: string;
  level?: string;
}

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
// 유형 표기는 Screen 1 ④ 와 같은 표를 본다 (utils/alertLabels). 화면마다 따로
// 들고 있으면 유형이 하나 늘 때 한쪽만 갱신되어 같은 사건이 다르게 보인다.
const TYPE_OPTIONS = [
  { value: "", label: "전체 유형" },
  ...Object.entries(ALERT_TYPE_LABEL).map(([value, label]) => ({ value, label })),
];

const TYPE_LABEL = ALERT_TYPE_LABEL;

const LEVEL_LABEL: Record<string, string> = {
  level1_caution: "L1 주의",
  level2_warning: "L2 경고",
  level3_critical: "L3 위험",
};
const REPLAY_METRICS = new Set<MetricKey>([
  "co2_ppm",
  "co_ppm",
  "h2s_ppm",
  "temperature_c",
  "humidity_pct",
  "gas_resistance_ohm",
]);

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

export function EventLogScreen({ initialFilter }: { initialFilter?: EventLogFilter } = {}) {
  const [nodeId, setNodeId] = useState(initialFilter?.nodeId ?? "");
  const [alertKey, setAlertKey] = useState("");
  const [status, setStatus] = useState<"" | "active" | "resolved">("");
  const [dateRange, setDateRange] = useState<"" | "today" | "7d" | "30d">("");
  const [level, setLevel] = useState(initialFilter?.level ?? "");
  const [alertType, setAlertType] = useState("");
  const [limit, setLimit] = useState(100);
  const [events, setEvents] = useState<AlertEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [refreshVersion, setRefreshVersion] = useState(0);
  const [replayEvent, setReplayEvent] = useState<AlertEvent | null>(null);
  const [replayPoints, setReplayPoints] = useState<SensorDataPoint[]>([]);
  const [replayIndex, setReplayIndex] = useState(0);
  const [replayPlaying, setReplayPlaying] = useState(false);
  const [replayError, setReplayError] = useState<string | null>(null);

  useEffect(() => {
    if (!replayEvent?.metric || !REPLAY_METRICS.has(replayEvent.metric as MetricKey)) return;
    const center = Date.parse(replayEvent.activated_at);
    setReplayPlaying(false);
    setReplayIndex(0);
    setReplayError(null);
    fetchSensorData(
      replayEvent.source_node_id,
      replayEvent.metric as MetricKey,
      new Date(center - 5 * 60_000).toISOString(),
      new Date(center + 10 * 60_000).toISOString(),
      "1min",
    )
      .then(setReplayPoints)
      .catch((error: unknown) => setReplayError(error instanceof Error ? error.message : String(error)));
  }, [replayEvent]);

  useEffect(() => {
    if (!replayPlaying || replayPoints.length < 2) return;
    const timer = window.setInterval(() => {
      setReplayIndex((index) => {
        if (index >= replayPoints.length - 1) {
          setReplayPlaying(false);
          return index;
        }
        return index + 1;
      });
    }, 500);
    return () => window.clearInterval(timer);
  }, [replayPlaying, replayPoints.length]);

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
    () =>
      events.filter((event) => {
        if (level && event.level !== level) return false;
        if (alertType && event.alert_type !== alertType) return false;
        return true;
      }),
    [events, level, alertType],
  );
  const activeCount = visibleEvents.filter((event) => event.status === "active").length;
  const levelCounts = {
    level1_caution: visibleEvents.filter((event) => event.level === "level1_caution").length,
    level2_warning: visibleEvents.filter((event) => event.level === "level2_warning").length,
    level3_critical: visibleEvents.filter((event) => event.level === "level3_critical").length,
  };
  const filterCount = [nodeId, alertKey, status, dateRange, level, alertType].filter(Boolean).length;
  const resetFilters = () => {
    setNodeId(""); setAlertKey(""); setStatus(""); setDateRange(""); setLevel(""); setAlertType("");
  };

  return (
    <div className="screen event-log-screen">
      <div className="event-log-heading">
        <div>
          <p className="event-kicker">REVIEW / ALERT HISTORY</p>
          <h2 className="event-log-title">경보 이벤트 로그</h2>
        </div>
        <div className="event-log-meta" aria-label="이벤트 로그 요약">
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

      <section className="event-kpi-strip" aria-label="경보 등급별 요약">
        <div><small>표시 중</small><strong>{visibleEvents.length}</strong></div>
        <div className="is-active"><small>활성</small><strong>{activeCount}</strong></div>
        <div className="is-l1"><small>L1 주의</small><strong>{levelCounts.level1_caution}</strong></div>
        <div className="is-l2"><small>L2 경고</small><strong>{levelCounts.level2_warning}</strong></div>
        <div className="is-l3"><small>L3 위험</small><strong>{levelCounts.level3_critical}</strong></div>
      </section>

      <section className="panel event-filters">
        <label className="control">
          <span className="control-label">DATE</span>
          <select
            value={dateRange}
            onChange={(e) => setDateRange(e.target.value as typeof dateRange)}
          >
            {DATE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <label className="control">
          <span className="control-label">LEVEL</span>
          <select value={level} onChange={(e) => setLevel(e.target.value)}>
            {LEVEL_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <label className="control">
          <span className="control-label">NODE</span>
          <select value={nodeId} onChange={(e) => setNodeId(e.target.value)}>
            {NODE_OPTIONS.map((id) => (
              <option key={id} value={id}>
                {id || "전체 노드"}
              </option>
            ))}
          </select>
        </label>
        <label className="control">
          <span className="control-label">TYPE</span>
          <select value={alertType} onChange={(e) => setAlertType(e.target.value)}>
            {TYPE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <label className="control">
          <span className="control-label">STATUS</span>
          <select value={status} onChange={(e) => setStatus(e.target.value as typeof status)}>
            {STATUS_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
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
              <option key={n} value={n}>
                {n}건
              </option>
            ))}
          </select>
        </label>
        <button type="button" className="event-filter-reset" onClick={resetFilters} disabled={filterCount === 0}>
          필터 초기화{filterCount > 0 ? ` · ${filterCount}` : ""}
        </button>
      </section>

      <section className="panel event-list-panel">
        <div className="event-list-head">
          <div>
            <p className="event-kicker">AUDIT TRAIL</p>
            <h2 className="panel-title">최근 경보 이력</h2>
          </div>
          <span className="event-list-count">
            {loading ? "LOADING" : `${visibleEvents.length} EVENTS`}
          </span>
        </div>
        {error && <p className="panel-empty panel-error">조회 실패: {error}</p>}
        {!error && !loading && visibleEvents.length === 0 && (
          <p className="panel-empty">조건에 맞는 이벤트가 없습니다.</p>
        )}
        {replayEvent && (
          <div className="incident-replay" aria-label="사고 센서값 재생">
            <div className="incident-replay__head">
              <div>
                <span className="event-kicker">INCIDENT REPLAY</span>
                <strong>{replayEvent.source_node_id} · {replayEvent.metric ?? replayEvent.alert_key}</strong>
              </div>
              <button type="button" onClick={() => setReplayEvent(null)}>닫기</button>
            </div>
            {replayError && <p className="panel-error">재생 데이터 조회 실패: {replayError}</p>}
            {!replayError && replayPoints.length === 0 && <p className="pending">경보 전후 시계열을 불러오는 중…</p>}
            {replayPoints.length > 0 && (
              <div className="incident-replay__controls">
                <button
                  type="button"
                  onClick={() => {
                    if (!replayPlaying && replayIndex >= replayPoints.length - 1) setReplayIndex(0);
                    setReplayPlaying((playing) => !playing);
                  }}
                >
                  {replayPlaying ? "일시정지" : replayIndex >= replayPoints.length - 1 ? "다시 재생" : "재생"}
                </button>
                <input
                  type="range"
                  min="0"
                  max={replayPoints.length - 1}
                  value={replayIndex}
                  aria-label="사고 재생 시점"
                  onChange={(event) => {
                    setReplayPlaying(false);
                    setReplayIndex(Number(event.target.value));
                  }}
                />
                <time>{formatTime(replayPoints[replayIndex]?.time ?? null)}</time>
                <strong>{replayPoints[replayIndex]?.value.toLocaleString("ko-KR") ?? "—"}</strong>
                <span>임계 {replayEvent.threshold?.toLocaleString("ko-KR") ?? "—"}</span>
              </div>
            )}
            <p className="incident-replay__limit">현재 저장 범위: 센서 시계열 · 작업자 위치와 당시 탈출 경로는 저장 연동 필요</p>
          </div>
        )}
        {visibleEvents.length > 0 && (
          <div className="event-table-wrap">
            <table className="event-table">
              <thead>
                <tr>
                  <th>시각</th>
                  <th>노드</th>
                  <th>당시 작업자</th>
                  <th>유형</th>
                  <th>등급</th>
                  <th>메시지</th>
                  <th>상태</th>
                  <th>측정값</th>
                  <th>해제 시각</th>
                  <th>재생</th>
                </tr>
              </thead>
              <tbody>
                {visibleEvents.map((ev) => (
                  <tr
                    key={ev.message_id}
                    className={`${ev.status === "active" ? "event-row-active " : ""}event-row--${ev.level}`}
                  >
                    <td className="cell-time">{formatTime(ev.activated_at)}</td>
                    <td className="event-node">{ev.source_node_id}</td>
                    {/* 이슈 #136 — 지금 착용자가 아니라 이 경보가 났을 때의 착용자다.
                        배정이 바뀐 뒤 조회해도 당시 사람이 나와야 사고 조사가 성립한다. */}
                    <td className="event-worker">
                      {ev.worker_name ? (
                        <>
                          <span className="event-worker__name">{ev.worker_name}</span>
                          <span className="event-worker__no">{ev.worker_employee_no}</span>
                        </>
                      ) : (
                        <span className="pending">미배정</span>
                      )}
                    </td>
                    <td>
                      <span className="event-type">{formatType(ev.alert_type)}</span>
                      <span className="event-key">{ev.alert_key}</span>
                    </td>
                    <td>
                      <span className={levelClass(ev.level)}>
                        {LEVEL_LABEL[ev.level] ?? ev.level}
                      </span>
                    </td>
                    <td className="event-message">{ev.message || "—"}</td>
                    <td>
                      <span className={"event-status event-status-" + ev.status}>
                        {ev.status === "active" ? "활성" : "해제"}
                      </span>
                    </td>
                    <td className="cell-num">
                      {ev.trigger_value !== null ? ev.trigger_value.toFixed(1) : "—"}
                      {ev.threshold !== null && (
                        <span className="event-threshold"> / {ev.threshold}</span>
                      )}
                    </td>
                    <td className="cell-time">{formatTime(ev.resolved_at)}</td>
                    <td>
                      <button
                        type="button"
                        className="event-replay-btn"
                        disabled={!ev.metric || !REPLAY_METRICS.has(ev.metric as MetricKey)}
                        onClick={() => setReplayEvent(ev)}
                      >
                        재생
                      </button>
                    </td>
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
