import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { Sparkline } from "./Sparkline";
import type { TrendPoint } from "../store/dashboardStore";
import type { ProjectionPoint } from "../utils/projection";

/** 0 초와 60 초, 두 점. 관측 구간 = 60 초. */
const OBSERVED: TrendPoint[] = [
  { t: 0, v: 100 },
  { t: 60_000, v: 200 },
];

/** 관측과 같은 60 초 구간을 예측한다 → 전체 폭의 딱 절반씩 나눠 갖는다. */
const PROJ: ProjectionPoint[] = [{ offsetS: 60, value: 300 }];

const html = (props: Parameters<typeof Sparkline>[0]) =>
  renderToStaticMarkup(<Sparkline {...props} />);

/** polyline 의 points 속성을 좌표쌍 배열로. */
function polyline(markup: string, cls: string): [number, number][] | null {
  const m = markup.match(new RegExp(`<polyline class="${cls}" points="([^"]+)"`));
  if (!m) return null;
  return m[1].split(" ").map((pair) => {
    const [x, y] = pair.split(",").map(Number);
    return [x, y];
  });
}

describe("Sparkline", () => {
  it("점이 부족하면 선 대신 빈 표시를 낸다", () => {
    expect(html({ points: [] })).toContain("spark--empty");
    expect(html({ points: [{ t: 0, v: 1 }] })).toContain("spark--empty");
    expect(html({ points: undefined })).toContain("spark--empty");
  });

  it("예측이 없으면 점선도 임계선도 그리지 않는다", () => {
    const markup = html({ points: OBSERVED });
    expect(markup).toContain("spark__line");
    expect(markup).not.toContain("spark__proj");
    expect(markup).not.toContain("spark__threshold");
  });

  it("예측을 주면 점선과 임계선이 함께 나온다", () => {
    const markup = html({ points: OBSERVED, projection: PROJ });
    expect(markup).toContain("spark__proj");
    expect(markup).toContain("spark__threshold");
  });

  it("점선은 마지막 실측점에서 출발한다", () => {
    // 띄워 놓으면 두 선이 서로 다른 계열로 보인다.
    const markup = html({ points: OBSERVED, projection: PROJ });
    const solid = polyline(markup, "spark__line")!;
    const dashed = polyline(markup, "spark__proj")!;
    expect(dashed[0]).toEqual(solid[solid.length - 1]);
  });

  it("실측과 예측이 가로 축척을 공유한다", () => {
    // 관측 60초 + 예측 60초 = 전체 120초. 이음매는 정확히 폭의 절반이어야 한다.
    // 두 구간이 다른 축척을 쓰면 기울기가 꺾여, 없는 가속이 있는 것처럼 읽힌다.
    const markup = html({ points: OBSERVED, projection: PROJ });
    const dashed = polyline(markup, "spark__proj")!;
    expect(dashed[0][0]).toBeCloseTo(50, 1);
    expect(dashed[dashed.length - 1][0]).toBeCloseTo(100, 1);
  });

  it("예측값이 세로 범위 안에 들어온다", () => {
    // 관측(100~200) 밖으로 나가는 300 이 눈금에 포함되지 않으면 점선이 잘리고,
    // 잘린 그래프는 "아직 여유 있다" 로 읽힌다.
    const markup = html({ points: OBSERVED, projection: PROJ });
    const dashed = polyline(markup, "spark__proj")!;
    for (const [, y] of dashed) {
      expect(y).toBeGreaterThanOrEqual(0);
      expect(y).toBeLessThanOrEqual(24);
    }
  });

  it("임계선 높이가 예측 마지막 점과 일치한다", () => {
    // 임계값을 따로 받지 않고 곡선 끝에서 파생하므로 둘이 어긋날 수 없다.
    const markup = html({ points: OBSERVED, projection: PROJ });
    const dashed = polyline(markup, "spark__proj")!;
    const lineY = Number(markup.match(/class="spark__threshold" x1="0" y1="([\d.]+)"/)![1]);
    expect(lineY).toBeCloseTo(dashed[dashed.length - 1][1], 1);
  });

  it("값이 멈춘 상태에서는 미래를 그리지 않는다", () => {
    const markup = html({ points: OBSERVED, projection: PROJ, stale: true });
    expect(markup).toContain("spark--stale");
    expect(markup).not.toContain("spark__proj");
    expect(markup).not.toContain("spark__threshold");
  });
});
