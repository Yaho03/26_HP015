import { describe, expect, it } from "vitest";
import { RISK_SPLIT, splitFor, splitNodes } from "./consoleSplit";
import type { AlertLevel, SensorNodeState } from "../types";

const IDS = ["sensor-01", "sensor-02", "sensor-03", "sensor-04"];

function node(status: "online" | "offline" = "online"): SensorNodeState {
  return {
    node_id: "n",
    readings: {},
    battery_pct: null,
    wifi_rssi_dbm: null,
    connection_status: status,
    last_seen_at: null,
  };
}

/** id → 등급 표를 levelOf 함수로. 표에 없으면 판정 불가. */
function levels(map: Partial<Record<string, AlertLevel>>) {
  return (id: string): AlertLevel => map[id] ?? "unknown";
}

function allOnline(): Record<string, SensorNodeState> {
  return Object.fromEntries(IDS.map((id) => [id, node()]));
}

describe("splitFor — 지시서 §4 의 높이 표", () => {
  it("n 이 커질수록 ② 가 커지고 ③ 이 줄어든다", () => {
    const shares = [0, 1, 2, 3, 4].map((n) => splitFor(n));
    expect(shares).toEqual([
      [15, 85],
      [35, 65],
      [52, 48],
      [68, 32],
      [82, 18],
    ]);
    for (let i = 1; i < shares.length; i++) {
      expect(shares[i][0]).toBeGreaterThan(shares[i - 1][0]);
      expect(shares[i][1]).toBeLessThan(shares[i - 1][1]);
    }
  });

  it("두 몫의 합은 항상 100 이다", () => {
    for (const [a, b] of Object.values(RISK_SPLIT)) expect(a + b).toBe(100);
  });

  it("표를 벗어난 n 은 양끝으로 붙잡는다", () => {
    expect(splitFor(-1)).toEqual([15, 85]);
    expect(splitFor(9)).toEqual([82, 18]);
  });
});

describe("splitNodes — 승격 규칙", () => {
  it("주의 이상만 ② 로 간다", () => {
    const s = splitNodes(
      IDS,
      allOnline(),
      levels({
        "sensor-01": "normal",
        "sensor-02": "level1_caution",
        "sensor-03": "normal",
        "sensor-04": "normal",
      }),
    );
    expect(s.risk).toEqual(["sensor-02"]);
    expect(s.share).toEqual([35, 65]);
  });

  it("승격된 노드는 ③ 에서 빠진다 — 두 칸에 중복 표시하지 않는다", () => {
    const s = splitNodes(
      IDS,
      allOnline(),
      levels({
        "sensor-01": "level2_warning",
        "sensor-02": "level1_caution",
        "sensor-03": "normal",
        "sensor-04": "normal",
      }),
    );
    expect(s.risk).toHaveLength(2);
    expect(s.summary).toEqual(["sensor-03", "sensor-04"]);
    // 이것이 ③ 이 줄어드는 이유다. 겹치면 비율만 바뀌고 내용은 그대로가 된다.
    for (const id of s.risk) expect(s.summary).not.toContain(id);
    expect([...s.risk, ...s.summary].sort()).toEqual([...IDS].sort());
  });

  it("위험도 높은 순으로 정렬한다 — 잘리는 쪽이 덜 위험한 카드여야 한다", () => {
    const s = splitNodes(
      IDS,
      allOnline(),
      levels({
        "sensor-01": "level1_caution",
        "sensor-02": "level3_critical",
        "sensor-03": "level2_warning",
        "sensor-04": "normal",
      }),
    );
    expect(s.risk).toEqual(["sensor-02", "sensor-03", "sensor-01"]);
  });

  it("unknown 은 승격 대상이 아니다 (이슈 #165)", () => {
    // 임계값을 못 받으면 전 노드가 unknown 이 된다. 이때 승격시키면 위험 상세가
    // 전 노드로 가득 차서 진짜 위험이 묻힌다.
    const s = splitNodes(IDS, allOnline(), levels({}));
    expect(s.risk).toEqual([]);
    expect(s.summary).toEqual(IDS);
    expect(s.share).toEqual([15, 85]);
  });

  it("unknown 을 normal 로 취급하지도 않는다 — ③ 에 그대로 남는다", () => {
    const s = splitNodes(
      IDS,
      allOnline(),
      levels({ "sensor-01": "normal", "sensor-02": "unknown" }),
    );
    expect(s.summary).toContain("sensor-02");
  });

  it("오프라인 노드는 등급이 높아도 승격하지 않는다", () => {
    // 멈춘 값으로 위험 상세를 채우면 현재 상태로 읽힌다.
    const nodes = allOnline();
    nodes["sensor-01"] = node("offline");
    const s = splitNodes(IDS, nodes, levels({ "sensor-01": "level3_critical" }));
    expect(s.risk).toEqual([]);
    expect(s.summary).toContain("sensor-01");
  });

  it("데이터가 없는 슬롯도 승격하지 않는다", () => {
    const s = splitNodes(IDS, {}, levels({ "sensor-01": "level3_critical" }));
    expect(s.risk).toEqual([]);
  });

  it("네 노드 전부 승격되면 ③ 이 비고 ② 가 82% 를 갖는다", () => {
    const s = splitNodes(
      IDS,
      allOnline(),
      levels({
        "sensor-01": "level1_caution",
        "sensor-02": "level1_caution",
        "sensor-03": "level2_warning",
        "sensor-04": "level3_critical",
      }),
    );
    expect(s.risk).toHaveLength(4);
    expect(s.summary).toEqual([]);
    expect(s.share).toEqual([82, 18]);
  });
});
