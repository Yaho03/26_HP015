import { useState } from "react";
import { useEvacuationTopology } from "../hooks/useEvacuationTopology";
import { setExitUsable } from "../services/evacuationApi";
import "../styles/evacuation.css";

/**
 * 통행 구조 설정 탭 (§4.2 PATCH /api/evacuation/exits/{exit_id}).
 *
 * 여기서 하는 일은 하나다 — 출구를 열고 닫는다. 점검이나 사고로 실제로 쓸 수 없게
 * 된 출구를 시스템에 알리는 것이고, 그러면 경로가 즉시 다른 출구로 다시 잡힌다.
 *
 * 토폴로지 자체(노드·간선)는 여기서 편집하지 않는다. YAML 이 소스이고 실측 도면이
 * 들어오면 파일을 교체한다. 화면에서 그래프를 편집하게 만들면 파일과 DB 중 어느
 * 쪽이 진짜인지 알 수 없게 된다.
 */
export function EvacuationTopologyPanel() {
  const { topology, reload } = useEvacuationTopology();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reason, setReason] = useState("");

  async function toggle(exitId: string, next: boolean) {
    setBusy(exitId);
    setError(null);
    try {
      await setExitUsable(exitId, next, reason.trim());
      setReason("");
      reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "출구 상태 변경 실패");
    } finally {
      setBusy(null);
    }
  }

  if (topology === null) {
    return (
      <section className="settings-section" aria-labelledby="topology-title">
        <div className="settings-section-heading">
          <div>
            <p className="settings-section-kicker">FR-801 / EGRESS TOPOLOGY</p>
            <h3 id="topology-title">통행 구조</h3>
          </div>
        </div>
        <div className="evac__banner evac__banner--muted" role="status">
          <strong>탈출 경로 기능 비활성</strong>
          <span>
            통행 구조를 불러오지 못했습니다. 사유는 시스템 탭의 <code>/health</code>
            응답에서 확인할 수 있습니다.
          </span>
        </div>
      </section>
    );
  }

  const usableCount = topology.exits.filter((e) => e.is_usable).length;

  return (
    <section className="settings-section evac" aria-labelledby="topology-title">
      <div className="settings-section-heading">
        <div>
          <p className="settings-section-kicker">FR-801 / EGRESS TOPOLOGY</p>
          <h3 id="topology-title">통행 구조</h3>
        </div>
        <span className="settings-source">
          노드 {topology.nav_nodes.length} · 간선 {topology.nav_edges.length} · 출구{" "}
          {topology.exits.length}
        </span>
      </div>

      <div className="evac__badges">
        <span className="evac__badge evac__badge--provisional">
          통행 구조 가정값 (실측 미반영)
        </span>
        <span className="evac__badge">{topology.coordinate_system}</span>
      </div>

      {/* 마지막 출구를 닫는 것은 "안전 경로 없음"을 스스로 만드는 조작이다.
          막지는 않는다 — 실제로 두 출구가 모두 막히는 상황이 있을 수 있다.
          다만 그 결과를 미리 알려준다. */}
      {usableCount <= 1 && (
        <div className="evac__banner" role="alert">
          <strong>사용 가능한 출구가 {usableCount}개입니다</strong>
          <span>
            마지막 출구까지 닫으면 모든 작업자에게 <code>no_safe_route</code> 경보가
            발령됩니다.
          </span>
        </div>
      )}

      {error && <p className="settings-state settings-state--error">{error}</p>}

      <label className="evac__reason">
        <span>변경 사유 (감사 로그에 기록됩니다)</span>
        <input
          type="text"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="예: 정기 점검으로 후방 트렁크 폐쇄"
        />
      </label>

      <ul className="evac__exits">
        {topology.exits.map((exit) => (
          <li key={exit.exit_id} className="evac__exit-row">
            <span className="evac__exit-name">
              <strong>{exit.label || exit.exit_id}</strong>
              <small>
                {exit.exit_id} · 우선순위 {exit.priority}
              </small>
            </span>
            <span
              className={
                "evac__badge" + (exit.is_usable ? "" : " evac__badge--warn")
              }
            >
              {exit.is_usable ? "사용 가능" : "폐쇄"}
            </span>
            <button
              type="button"
              className="evac__mock-btn"
              disabled={busy === exit.exit_id}
              onClick={() => void toggle(exit.exit_id, !exit.is_usable)}
            >
              {busy === exit.exit_id ? "적용 중…" : exit.is_usable ? "닫기" : "열기"}
            </button>
          </li>
        ))}
      </ul>

      <p className="evac__disclaimer">
        출구를 닫으면 즉시 전 작업자의 경로가 다시 계산됩니다. 통행 구조 자체(노드·간선)는
        <code> config/space_topology.yaml </code>이 단일 소스이며 화면에서 편집하지 않습니다.
      </p>
    </section>
  );
}
