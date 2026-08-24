import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it } from "vitest";
import { SensorSummaryPanel } from "./SensorSummaryPanel";
import { setThresholdTable } from "../utils/alerts";
import { STALE_AFTER_MS } from "../hooks/useFreshness";
import type { TrendPoint } from "../store/dashboardStore";
import type { SensorNodeState } from "../types";

// 임계값은 서버에서 온다 (FR-204). 테이블이 없으면 전 노드가 "판정 불가" 라
// 예측 배지도 나오지 않으므로, 실제 마이그레이션 값과 같은 CO₂ 사다리를 심는다.
beforeEach(() => {
  setThresholdTable([
    { metric: "co2_ppm", level: "level1_caution", direction: "above", enter_threshold: 1000 },
    { metric: "co2_ppm", level: "level2_warning", direction: "above", enter_threshold: 2000 },
    { metric: "co2_ppm", level: "level3_critical", direction: "above", enter_threshold: 5000 },
  ]);
});

/** 마지막 점이 `endsAt` 이 되도록 뒤로 뻗은 상승 램프. */
function risingCo2(endsAt: number): TrendPoint[] {
  const out: TrendPoint[] = [];
  for (let i = 10; i >= 0; i--) {
    out.push({ t: endsAt - i * 30_000, v: 600 + (10 - i) * 20 });
  }
  return out;
}

function node(lastSeenAt: string): SensorNodeState {
  return {
    node_id: "sensor-01",
    readings: { co2_ppm: { metric: "co2_ppm", value: 790, sampled_at: lastSeenAt } },
    battery_pct: 80,
    wifi_rssi_dbm: -50,
    connection_status: "online",
    last_seen_at: lastSeenAt,
  };
}

function render(lastSeenAt: string) {
  return renderToStaticMarkup(
    <SensorSummaryPanel
      nodeIds={["sensor-01"]}
      nodes={{ "sensor-01": node(lastSeenAt) }}
      trends={{ "sensor-01": { co2_ppm: risingCo2(Date.parse(lastSeenAt)) } }}
      wearable={null}
      levelOf={() => "normal"}
    />,
  );
}

describe("SensorSummaryPanel — 예측 배지와 신선도", () => {
  it("값이 흐르는 동안 추세 배지와 점선을 그린다", () => {
    const markup = render(new Date().toISOString());
    expect(markup).toContain("scard__projection");
    // 출처를 항상 밝힌다. LSTM 이 붙으면 이 자리만 "AI 예측" 으로 바뀐다.
    expect(markup).toContain("추세");
    expect(markup).toMatch(/약 \d+분 뒤/);
    expect(markup).toContain("spark__proj");
    expect(markup).toContain("spark__threshold");
  });

  it("추세 배지는 경보 문구를 쓰지 않는다", () => {
    // 06_ALERT_RULES §8.2 — 추세는 독립 경보를 발령하지 않는다. 화면 문구가
    // 경보처럼 읽히면 규칙을 지켜도 사용자에겐 경보다.
    const markup = render(new Date().toISOString());
    for (const word of ["대피", "누출", "발생했습니다"]) {
      expect(markup).not.toContain(word);
    }
  });

  it("값이 멈추면 STALE 을 띄우고 미래를 그리지 않는다", () => {
    const stale = new Date(Date.now() - STALE_AFTER_MS - 1_000).toISOString();
    const markup = render(stale);
    expect(markup).toContain("STALE");
    expect(markup).toContain("scard--stale");
    // 멈춘 버퍼로 외삽하면 "곧 위험" 이 영영 화면에 박힌다.
    expect(markup).not.toContain("scard__projection");
    expect(markup).not.toContain("spark__proj");
  });

  it("갓 도착한 값에는 STALE 을 붙이지 않는다", () => {
    const markup = render(new Date().toISOString());
    expect(markup).not.toContain("STALE");
    expect(markup).not.toContain("scard--stale");
  });
});
