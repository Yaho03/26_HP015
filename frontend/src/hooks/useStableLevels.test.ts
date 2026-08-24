import { describe, expect, it } from "vitest";
import { LEVEL_HOLD_MS, stabilizeLevels, type LevelHold } from "./useStableLevels";
import type { AlertLevel } from "../types";

const T0 = 1_000_000;

/** shown 등급만 뽑아 비교하기 쉽게. */
function shown(holds: Record<string, LevelHold>): Record<string, AlertLevel> {
  const out: Record<string, AlertLevel> = {};
  for (const id of Object.keys(holds)) out[id] = holds[id].shown;
  return out;
}

describe("stabilizeLevels", () => {
  it("처음 보는 노드는 그대로 채택한다", () => {
    // 유지 시간을 걸면 화면이 뜨는 순간 4초 동안 빈 등급이 된다.
    const s = stabilizeLevels({ a: "level2_warning" }, {}, T0);
    expect(shown(s)).toEqual({ a: "level2_warning" });
  });

  it("등급 상승은 그 프레임에 바로 반영한다", () => {
    const s1 = stabilizeLevels({ a: "normal" }, {}, T0);
    const s2 = stabilizeLevels({ a: "level3_critical" }, s1, T0 + 1);
    expect(shown(s2)).toEqual({ a: "level3_critical" });
  });

  it("등급 하강은 유지 시간을 채우기 전까지 반영하지 않는다", () => {
    const s1 = stabilizeLevels({ a: "level2_warning" }, {}, T0);
    const s2 = stabilizeLevels({ a: "normal" }, s1, T0 + 1_000);
    expect(shown(s2)).toEqual({ a: "level2_warning" });
    expect(s2.a.pending).toBe("normal");
  });

  it("유지 시간을 채우면 하강을 반영한다", () => {
    const s1 = stabilizeLevels({ a: "level2_warning" }, {}, T0);
    const s2 = stabilizeLevels({ a: "normal" }, s1, T0 + 1_000);
    const s3 = stabilizeLevels({ a: "normal" }, s2, T0 + 1_000 + LEVEL_HOLD_MS);
    expect(shown(s3)).toEqual({ a: "normal" });
    expect(s3.a.pending).toBeNull();
  });

  it("경계에서 오르내려도 높은 등급을 유지한다", () => {
    // 임계값에 걸친 값이 1초마다 뒤집히는 상황. 화면이 떨리면 안 된다.
    let s = stabilizeLevels({ a: "level1_caution" }, {}, T0);
    for (let i = 1; i <= 6; i++) {
      const level: AlertLevel = i % 2 === 0 ? "level1_caution" : "normal";
      s = stabilizeLevels({ a: level }, s, T0 + i * 1_000);
      expect(shown(s)).toEqual({ a: "level1_caution" });
    }
  });

  it("하강 대기 중 다시 오르면 대기를 버린다", () => {
    const s1 = stabilizeLevels({ a: "level2_warning" }, {}, T0);
    const s2 = stabilizeLevels({ a: "normal" }, s1, T0 + 1_000);
    expect(s2.a.pending).toBe("normal");
    const s3 = stabilizeLevels({ a: "level2_warning" }, s2, T0 + 2_000);
    expect(s3.a.pending).toBeNull();
    // 대기가 버려졌으므로, 다시 내려가면 시계도 처음부터다.
    const s4 = stabilizeLevels({ a: "normal" }, s3, T0 + 2_500);
    const s5 = stabilizeLevels({ a: "normal" }, s4, T0 + 2_500 + LEVEL_HOLD_MS - 1);
    expect(shown(s5)).toEqual({ a: "level2_warning" });
  });

  it("더 낮은 후보로 바뀌면 시계를 다시 센다", () => {
    const s1 = stabilizeLevels({ a: "level3_critical" }, {}, T0);
    const s2 = stabilizeLevels({ a: "level2_warning" }, s1, T0 + 1_000);
    // 3초 뒤 후보가 normal 로 바뀐다 — 이전 후보의 경과를 물려받으면 안 된다.
    const s3 = stabilizeLevels({ a: "normal" }, s2, T0 + 4_000);
    expect(shown(s3)).toEqual({ a: "level3_critical" });
    const s4 = stabilizeLevels({ a: "normal" }, s3, T0 + 4_000 + LEVEL_HOLD_MS);
    expect(shown(s4)).toEqual({ a: "normal" });
  });

  it("판정 불가로 오르는 것은 즉시 반영한다", () => {
    // unknown 은 normal 위다. 판정 못 하는 것을 안전하다고 계속 말하지 않는다.
    const s1 = stabilizeLevels({ a: "normal" }, {}, T0);
    const s2 = stabilizeLevels({ a: "unknown" }, s1, T0 + 1);
    expect(shown(s2)).toEqual({ a: "unknown" });
  });

  it("사라진 노드는 결과에서 빠진다", () => {
    const s1 = stabilizeLevels({ a: "normal", b: "normal" }, {}, T0);
    const s2 = stabilizeLevels({ a: "normal" }, s1, T0 + 1_000);
    expect(Object.keys(s2)).toEqual(["a"]);
  });

  it("노드마다 독립적으로 판정한다", () => {
    const s1 = stabilizeLevels({ a: "level2_warning", b: "normal" }, {}, T0);
    const s2 = stabilizeLevels({ a: "normal", b: "level3_critical" }, s1, T0 + 1_000);
    expect(shown(s2)).toEqual({ a: "level2_warning", b: "level3_critical" });
  });
});
