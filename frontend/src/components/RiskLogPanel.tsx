import { useEffect, useState } from "react";
import { fetchAlertEvents, type AlertEvent } from "../services/api";
import { alertTypeLabel, ALERT_LEVEL_LABEL } from "../utils/alertLabels";
import { LEVEL_RANK } from "../utils/alerts";
import { shortNodeLabel } from "../utils/nodes";
import { RiskTimeline } from "./RiskTimeline";
import type { AlertLevel } from "../types";

/**
 * ④ 최근 위험 로그 + 24시간 등급 띠.
 *
 * **주의(L1) 이상을 싣되, 시간순이 아니라 등급순으로 정렬한다.**
 *
 * 예전에는 L2 이상만 실었다. 이 칸이 몇 행 안 되는 고정 높이라, L1 을 시간순으로
 * 섞으면 평상시 잡음이 실제 위험 이력을 목록 밖으로 밀어내기 때문이었다.
 * 등급순으로 세우면 그 문제가 사라진다 — L1 이 아무리 쏟아져도 L3 를 밀어낼 수
 * 없고, 잘리는 쪽은 언제나 가장 덜 위험한 행이다.
 *
 * 아래쪽 띠는 이 칸이 평상시 비어 있는 문제를 메운다. 사고가 없으면 로그도 없어서
 * "기록 없음" 한 줄이 화면에서 가장 큰 죽은 공간이 된다.
 */
const VISIBLE_LEVELS = new Set<string>([
  "level1_caution",
  "level2_warning",
  "level3_critical",
]);
const FETCH_LIMIT = 200;
const TIMELINE_WINDOW_MS = 24 * 3_600_000;
const REFRESH_MS = 30_000;

/**
 * 이 칸에 실제로 그리는 행 수.
 *
 * 스크롤을 두지 않는다 — 관제 화면에서 스크롤 막대는 "아래에 뭔가 더 있다" 는
 * 사실만 알리고 그게 무엇인지는 안 알려준다. 등급순으로 세워 두었으므로 위쪽
 * 몇 줄이 언제나 가장 위험한 건이고, 나머지는 건수로만 밝히고 전체 로그로 넘긴다.
 */
const VISIBLE_ROWS = 3;

/** 등급 내림차순, 같은 등급이면 최신순. */
function bySeverityThenRecency(a: AlertEvent, b: AlertEvent): number {
  const rank = LEVEL_RANK[b.level as AlertLevel] - LEVEL_RANK[a.level as AlertLevel];
  if (rank !== 0) return rank;
  return b.activated_at.localeCompare(a.activated_at);
}

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
      // 띠가 24시간을 그리므로 그만큼 받아온다. 목록은 이 중 앞쪽만 쓴다.
      const start = new Date(Date.now() - TIMELINE_WINDOW_MS).toISOString();
      fetchAlertEvents({ limit: FETCH_LIMIT, start })
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

  const sorted = [...events].sort(bySeverityThenRecency);
  const hidden = Math.max(0, sorted.length - VISIBLE_ROWS);

  return (
    <section className="panel-4" aria-label="최근 위험 로그">
      <header className="panel-4__head">
        <span className="panel-4__title">최근 위험 로그</span>
        <span className="panel-4__note">주의 이상 · 등급순</span>
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
              {sorted.slice(0, VISIBLE_ROWS).map((e) => (
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

        {hidden > 0 && (
          // 잘린 건수를 숨기지 않는다. 스크롤 막대를 없앤 대신 "더 있다" 는
          // 사실과 그 개수를 글자로 말한다.
          <button
            type="button"
            className="risk-log__more"
            onClick={() => onOpenEventLog?.({})}
          >
            외 {hidden}건 · 전체 로그
          </button>
        )}
      </div>

      {/* 로그가 있으면 아래로 밀리고, 없으면 이 칸의 유일한 내용이 된다. */}
      <RiskTimeline events={events} />
    </section>
  );
}
