import { describe, expect, it } from "vitest";
import { freshnessAt, STALE_AFTER_MS } from "./useFreshness";

const NOW = Date.parse("2026-08-24T12:00:00.000Z");

function at(offsetMs: number): string {
  return new Date(NOW - offsetMs).toISOString();
}

describe("freshnessAt", () => {
  it("경과 초를 센다", () => {
    const result = freshnessAt(at(2_000), NOW);
    expect(result.secondsAgo).toBe(2);
    expect(result.label).toBe("2초 전");
    expect(result.isStale).toBe(false);
  });

  it("5초 이상이면 지연으로 판정한다", () => {
    const result = freshnessAt(at(STALE_AFTER_MS), NOW);
    expect(result.isStale).toBe(true);
  });

  it("타임스탬프가 없으면 판정하지 않는다", () => {
    // 아직 한 번도 보고하지 않은 대기 슬롯을 "지연" 으로 붉히면 안 된다 —
    // 그건 연결이 끊긴 것과 다른 상태다.
    for (const value of [null, undefined]) {
      const result = freshnessAt(value, NOW);
      expect(result.isStale).toBe(false);
      expect(result.secondsAgo).toBeNull();
      expect(result.label).toBe("—");
    }
  });

  it("파싱할 수 없는 값을 '방금' 으로 그리지 않는다", () => {
    const result = freshnessAt("not-a-date", NOW);
    expect(result.secondsAgo).toBeNull();
    expect(result.isStale).toBe(false);
  });

  it("미래 시각은 0초로 보여주되 지연으로 판정하지 않는다", () => {
    const result = freshnessAt(at(-10_000), NOW);
    expect(result.secondsAgo).toBe(0);
    expect(result.isStale).toBe(false);
  });
});
