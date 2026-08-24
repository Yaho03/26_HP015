import { useDashboardStore } from "../store/dashboardStore";
import { AiAnomalyPanel } from "./AiAnomalyPanel";

/** 노드별 AI 이상징후 (연구용).
 *
 *  기존 경보 패널(RiskDetailPanel / RiskLogPanel)과 **별도 구획**으로 둔다.
 *  같은 목록에 섞으면 관리자가 둘을 같은 성격의 알림으로 읽게 되고, 그 순간
 *  검증되지 않은 참고 지표가 산업안전 판단 근거가 된다.
 *
 *  판정을 못 받은 노드도 카드를 그린다 — 목록에서 빠지면 "이 노드는 문제없다" 로
 *  읽히지만 실제로는 아무것도 모르는 상태다. */
export function AiAnomalyGrid({ nodeIds }: { nodeIds: string[] }) {
  const anomalies = useDashboardStore((s) => s.ai_anomalies);

  return (
    <section className="panel ai-grid" aria-label="AI 이상징후 (연구용)">
      <header className="ai-grid__head">
        <div>
          <p className="ai-grid__kicker">RESEARCH / LSTM AUTOENCODER</p>
          <h2 className="panel-title">AI 이상징후</h2>
        </div>
        <span className="ai-grid__badge">실제 안전 경보 아님</span>
      </header>

      <p className="ai-grid__note">
        정상 패턴 학습 기반 참고 지표입니다. 가스 종류를 판정하지 않으며
        임계값 경보를 대체하지 않습니다.
      </p>

      <div className="ai-grid__cards">
        {nodeIds.map((node_id) => (
          <div key={node_id} className="ai-grid__cell">
            <span className="ai-grid__node">{node_id}</span>
            <AiAnomalyPanel ai={anomalies[node_id] ?? null} />
          </div>
        ))}
      </div>
    </section>
  );
}
