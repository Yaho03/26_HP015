import { useDashboardStore } from "../store/dashboardStore";
import { AI_UNDECIDED } from "../types";
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

  /* 승격된 노드가 둘 이상이면 이 구획은 카드를 접고 머리말만 남는다 — 자리는
     쓰면서 아무 말도 하지 않는 상태다. 한 줄 집계만 남겨 같은 높이에서 최소한
     "AI 가 지금 뭐라고 하는가" 는 답하게 한다. 미판정을 정상에 합치지 않는
     것이 여기서도 규칙이다(이슈 #165). */
  const tally = nodeIds.reduce(
    (acc, id) => {
      const status = anomalies[id]?.status;
      if (!status || AI_UNDECIDED.includes(status)) acc.undecided += 1;
      else if (status === "normal_pattern") acc.normal += 1;
      else acc.flagged += 1;
      return acc;
    },
    { flagged: 0, normal: 0, undecided: 0 },
  );

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

      <p className="ai-grid__tally">
        <span>노드 {nodeIds.length}</span>
        <span className="ai-grid__tally-flag">이상 {tally.flagged}</span>
        <span>정상 패턴 {tally.normal}</span>
        <span>미판정 {tally.undecided}</span>
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
