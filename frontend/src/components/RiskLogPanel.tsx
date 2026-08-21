import { useEffect, useState } from "react";
import { fetchAlertEvents, type AlertEvent } from "../services/api";
import { alertTypeLabel, ALERT_LEVEL_LABEL } from "../utils/alertLabels";
import { shortNodeLabel } from "../utils/nodes";

/**
 * ④ 최근 위험 로그.
 *
 * **L2 이상만 싣는다.** L1 까지 넣으면 평상시 잡음이 실제 위험 이력을 밀어낸다 —
 * 이 칸은 20행짜리 고정 높이라 밀려난 행은 사실상 없는 것과 같다.
 */
const VISIBLE_LEVELS = new Set(["level2_warning", "level3_critical"]);
const FETCH_LIMIT = 20;
const REFRESH_MS = 30_000;

interface RiskLogPanelProps {
  /** 행 클릭 시 이벤트 로그 화면으로 필터를 걸고 이동한다. */
  onOpenEventLog?: (filter: { nodeId?: string; level?: string }) => void;
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("ko-KR", { hour12: false });
}

export function RiskLogPanel({ onOpenEventLog }: RiskLogPanelProps) {
  const [events, setEvents] = useState<AlertEvent[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    const load = () => {
      fetchAlertEvents({ limit: FETCH_LIMIT })
        .then((rows) => {
          if (cancelled) return;
          setEvents(rows.filter((e) => VISIBLE_LEVELS.has(e.level)));
          setError(null);
        })
        .catch((e: unknown) => {
          if (!cancelled) setError(e instanceof Error ? e.message : String(e));
        });
    };

    load();
    const timer = window.setInterval(load, REFRESH_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  return (
    <section className="panel-4" aria-label="최근 위험 로그">
      <header className="panel-4__head">
        <span className="panel-4__title">최근 위험 로그</span>
        <span className="panel-4__note">L2 이상 · 최근 {FETCH_LIMIT}건</span>
      </header>

      <div className="panel-4__body">
        {error && <p className="panel-4__empty panel-4__empty--error">이력 조회 실패: {error}</p>}
        {!error && events.length === 0 && (
          // 빈 표가 아니라 문장으로 밝힌다 — 표만 비어 있으면 "로딩 중"과 구분되지 않는다.
          <p className="panel-4__empty">최근 위험 이력 없음</p>
        )}
        {events.length > 0 && (
          <table className="risk-log">
            <thead>
              <tr>
                <th>시각</th>
                <th>노드</th>
                <th>유형</th>
                <th>등급</th>
                <th>상태</th>
              </tr>
            </thead>
            <tbody>
              {events.map((e) => (
                <tr
                  key={e.message_id}
                  className={e.status === "active" ? "risk-log__row--active" : ""}
                  tabIndex={onOpenEventLog ? 0 : undefined}
                  role={onOpenEventLog ? "button" : undefined}
                  onClick={() =>
                    onOpenEventLog?.({
                      nodeId: e.source_node_id,
                      level: e.level,
                    })
                  }
                  onKeyDown={(ev) => {
                    if (ev.key === "Enter" || ev.key === " ") {
                      ev.preventDefault();
                      onOpenEventLog?.({
                        nodeId: e.source_node_id,
                        level: e.level,
                      });
                    }
                  }}
                >
                  <td className="risk-log__time">{formatTime(e.activated_at)}</td>
                  <td>
                    {shortNodeLabel(e.source_node_id)}
                    {/* 이슈 #136 — 지금 착용자가 아니라 경보 시점의 착용자다. */}
                    {e.worker_name && <em className="risk-log__worker">{e.worker_name}</em>}
                  </td>
                  <td>{alertTypeLabel(e.alert_type)}</td>
                  <td>
                    <span className={"event-level " + e.level}>
                      {ALERT_LEVEL_LABEL[e.level] ?? e.level}
                    </span>
                  </td>
                  <td>
                    <span className={"event-status event-status-" + e.status}>
                      {e.status === "active" ? "활성" : "해제"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
}
