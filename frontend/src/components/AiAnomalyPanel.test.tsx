import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { AiAnomalyPanel } from "./AiAnomalyPanel";
import type { AiAnomalyState, AiAnomalyStatus } from "../types";

function state(overrides: Partial<AiAnomalyState> = {}): AiAnomalyState {
  return {
    node_id: "sensor-01",
    status: "normal_pattern",
    score: 1.42,
    threshold: 3.19,
    consecutive_exceedances: 0,
    top_contributors: [
      { metric: "mq7_rs_ohm", error: 0.62 },
      { metric: "humidity_pct", error: 0.31 },
    ],
    model_version: "lstm-ae-v0.1.0",
    evaluated_at: "2026-08-24T12:00:00Z",
    is_research_only: true,
    ...overrides,
  };
}

const html = (ai: AiAnomalyState | null) =>
  renderToStaticMarkup(<AiAnomalyPanel ai={ai} />);

const UNDECIDED: AiAnomalyStatus[] = [
  "model_not_ready",
  "insufficient_data",
  "stale_data",
  "feature_mismatch",
];

describe("AiAnomalyPanel", () => {
  it("항상 연구용 표기를 낸다 (§10.2)", () => {
    const out = html(state());
    expect(out).toContain("Research");
    expect(out).toContain("실제 안전 경보 아님");
  });

  it("점수와 기준값을 함께 보여준다", () => {
    expect(html(state())).toContain("1.42 / 기준 3.19");
  });

  it("주요 기여 feature 를 사람이 읽는 이름으로 낸다", () => {
    expect(html(state())).toContain("MQ-7, 습도");
  });

  // ---- 판단하지 않은 것을 정상이라 말하지 않는다 (§10.3) ----
  //
  // 이 그룹이 이 파일의 존재 이유다. 밀폐공간에서 센서가 죽었는데 화면이
  // "정상" 으로 남는 것은 미검출보다 위험하다.

  it.each(UNDECIDED)("%s 는 '정상 패턴' 으로 표시하지 않는다", (status) => {
    expect(html(state({ status, score: null }))).not.toContain("정상 패턴");
  });

  it("데이터 부족이면 점수를 0 이 아니라 — 로 낸다", () => {
    const out = html(state({ status: "insufficient_data", score: null }));
    expect(out).toContain("데이터 부족");
    expect(out).not.toContain("0.00");
  });

  it("판정을 아직 못 받은 노드는 '판정 대기' 다", () => {
    const out = html(null);
    expect(out).toContain("판정 대기");
    expect(out).not.toContain("정상 패턴");
  });

  it("stale_data 는 정상이 아니라 데이터 지연이다", () => {
    expect(html(state({ status: "stale_data", score: null }))).toContain("데이터 지연");
  });

  it("판단 불가 상태에서는 기여 feature 도 내지 않는다", () => {
    // 판정하지 못한 window 의 오차는 그 자체로 의미가 없다.
    expect(html(state({ status: "insufficient_data", score: null }))).not.toContain("MQ-7");
  });

  // ---- 경보 어휘·색 체계를 쓰지 않는다 (§10.3) ----

  it.each(["anomaly", "anomaly_candidate"] as AiAnomalyStatus[])(
    "%s 를 위험/대피/누출로 표현하지 않는다",
    (status) => {
      const out = html(state({ status }));
      for (const forbidden of ["위험", "대피", "누출", "긴급"]) {
        expect(out).not.toContain(forbidden);
      }
    },
  );

  it("기존 경보 등급 클래스를 쓰지 않는다", () => {
    const out = html(state({ status: "anomaly" }));
    expect(out).not.toMatch(/level[123]_|is-l[123]\b/);
    expect(out).toContain("is-anomaly");
  });

  it("상태를 색만이 아니라 텍스트와 글리프로도 전달한다", () => {
    const out = html(state({ status: "anomaly" }));
    expect(out).toContain("AI 이상징후");
    expect(out).toContain("≠");
  });

  it("정상 패턴은 이상과 다른 글리프를 쓴다", () => {
    expect(html(state({ status: "normal_pattern" }))).toContain("≈");
  });
});
