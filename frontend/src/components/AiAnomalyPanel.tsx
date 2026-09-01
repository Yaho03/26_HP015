import type { AiAnomalyState, AiAnomalyStatus } from "../types";
import { AI_UNDECIDED } from "../types";

/** 화면 문구. **"위험"·"대피"·"누출" 을 쓰지 않는다 (§10.3).**
 *  이 판정은 평소와 다른 움직임을 가리킬 뿐 위험 물질을 특정하지 못한다. */
const STATUS_LABEL: Record<AiAnomalyStatus, string> = {
  model_not_ready: "모델 미준비",
  insufficient_data: "데이터 부족",
  stale_data: "데이터 지연",
  feature_mismatch: "입력 불일치",
  normal_pattern: "정상 패턴",
  anomaly_candidate: "이상 후보",
  anomaly: "AI 이상징후",
};

/** 상태를 색이 아니라 **글리프**로도 구분한다 (§10.3 접근성).
 *  기존 경보의 ▲/●/■ 와 겹치지 않는 기호를 쓴다. */
const STATUS_GLYPH: Record<AiAnomalyStatus, string> = {
  model_not_ready: "·",
  insufficient_data: "·",
  stale_data: "·",
  feature_mismatch: "·",
  normal_pattern: "≈",
  anomaly_candidate: "≠",
  anomaly: "≠",
};

const METRIC_LABEL: Record<string, string> = {
  co2_ppm: "CO₂",
  temperature_c: "온도",
  humidity_pct: "습도",
  gas_resistance_ohm: "가스저항",
  mq7_rs_ohm: "MQ-7",
  mq136_rs_ohm: "MQ-136",
  mq2_rs_ohm: "MQ-2",
};

function metricLabel(metric: string): string {
  return METRIC_LABEL[metric] ?? metric;
}

/** AI 이상징후 표시 (연구용).
 *
 *  기존 경보 등급과 시각적으로 완전히 분리한다 — 카드 본문이 아니라 하단 별도
 *  구획에 두고, L1/L2/L3 색 토큰을 쓰지 않으며, toast·modal·진동을 만들지 않는다.
 *  판단하지 않은 상태(데이터 부족 등)를 "정상" 으로 그리지 않는 것이 이 컴포넌트의
 *  가장 중요한 규칙이다. */
export function AiAnomalyPanel({ ai }: { ai: AiAnomalyState | null }) {
  // 아직 아무 판정도 못 받았으면 "정상" 이 아니라 "판정 대기" 다.
  const status: AiAnomalyStatus = ai?.status ?? "model_not_ready";
  const undecided = AI_UNDECIDED.includes(status);
  const label = ai ? STATUS_LABEL[status] : "판정 대기";

  return (
    <section className={"ai-panel is-" + status} aria-label="AI 이상징후 (연구용)">
      <header className="ai-panel__head">
        <span className="ai-panel__kicker">AI 이상징후 · Research</span>
        <span className="ai-panel__state">
          <span className="ai-panel__glyph" aria-hidden="true">{STATUS_GLYPH[status]}</span>
          {label}
        </span>
      </header>

      <div className="ai-panel__body">
        <div className="ai-panel__row">
          <span className="ai-panel__key">이상 점수</span>
          <span className="ai-panel__val">
            {/* 판단하지 않았으면 0 이 아니라 — 이다. 0 은 "완벽히 정상" 으로 읽힌다. */}
            {undecided || ai?.score == null
              ? "—"
              : `${ai.score.toFixed(2)} / 기준 ${ai.threshold?.toFixed(2) ?? "—"}`}
          </span>
        </div>
        <div className="ai-panel__row">
          <span className="ai-panel__key">주요 기여</span>
          <span className="ai-panel__val">
            {undecided || !ai?.top_contributors?.length
              ? "—"
              : ai.top_contributors.slice(0, 2).map((c) => metricLabel(c.metric)).join(", ")}
          </span>
        </div>
        <div className="ai-panel__row">
          <span className="ai-panel__key">모델</span>
          <span className="ai-panel__val ai-panel__val--mono">
            {ai?.model_version ?? "—"}
          </span>
        </div>
      </div>

      <p className="ai-panel__disclaimer">실제 안전 경보 아님 · 참고용</p>
    </section>
  );
}
