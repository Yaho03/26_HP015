import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { RiskTimeline } from "./RiskTimeline";
import type { AlertEvent } from "../services/api";

const NOW = Date.parse("2026-08-24T12:30:00.000Z");
const HOUR = 3_600_000;

function event(level: string, at: number): AlertEvent {
  return {
    message_id: `${level}-${at}`,
    alert_id: "a",
    source_node_id: "sensor-01",
    alert_key: "sensor-01:co2_ppm",
    alert_type: "gas_threshold",
    level,
    trigger_value: 1, threshold: 1, metric: "co2_ppm",
    message: "", status: "resolved", schema_version: "1.1",
    activated_at: new Date(at).toISOString(),
    resolved_at: null, published_at: new Date(at).toISOString(),
    worker_id: null, worker_name: null,
    worker_employee_no: null, worker_emergency_contact: null,
  };
}

const cells = (markup: string) =>
  [...markup.matchAll(/class="risk-timeline__cell([^"]*)"/g)].map((m) => m[1].trim());

describe("RiskTimeline", () => {
  it("24칸을 그린다", () => {
    expect(cells(renderToStaticMarkup(<RiskTimeline events={[]} now={NOW} />))).toHaveLength(24);
  });

  it("경보가 없던 시간대를 정상 색으로 칠하지 않는다", () => {
    // "경보가 없었다" 와 "시스템이 살아 있었다" 는 다른 사실이다.
    const all = cells(renderToStaticMarkup(<RiskTimeline events={[]} now={NOW} />));
    expect(all.every((c) => c === "is-quiet")).toBe(true);
    expect(all).not.toContain("is-normal");
  });

  it("한 시간대에 여러 등급이 있으면 가장 높은 것을 칠한다", () => {
    const at = NOW - 3 * HOUR;
    const markup = renderToStaticMarkup(
      <RiskTimeline
        events={[event("level1_caution", at), event("level3_critical", at + 60_000)]}
        now={NOW}
      />,
    );
    expect(cells(markup)).toContain("is-level3_critical");
    expect(cells(markup)).not.toContain("is-level1_caution");
  });

  it("24시간 밖의 사건은 버린다", () => {
    const markup = renderToStaticMarkup(
      <RiskTimeline events={[event("level3_critical", NOW - 30 * HOUR)]} now={NOW} />,
    );
    expect(cells(markup).every((c) => c === "is-quiet")).toBe(true);
  });

  it("알 수 없는 등급은 칠하지 않는다", () => {
    // 서버가 새 등급을 추가해도 화면이 임의의 색을 만들어내지 않는다.
    const markup = renderToStaticMarkup(
      <RiskTimeline events={[event("level9_unknown", NOW - HOUR)]} now={NOW} />,
    );
    expect(cells(markup).every((c) => c === "is-quiet")).toBe(true);
  });
});
