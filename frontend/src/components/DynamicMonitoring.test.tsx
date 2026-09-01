import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { AlertBanner } from "./AlertBanner";
import { ExposureDoseRow } from "./WearableStrip";
import { TwinHeatmapPanel } from "./TwinHeatmapPanel";
import { mockExposure } from "../mocks/exposure";

vi.mock("./TwinScene", () => ({ TwinScene: () => <div data-testid="twin" /> }));

describe("동적 관제 상호작용", () => {
  it("최신 센서가 부족하면 오래된 값을 분포로 그리지 않았다고 밝힌다", () => {
    const html = renderToStaticMarkup(
      <TwinHeatmapPanel
        nodes={[]}
        wearable={null}
        samples={[]}
        metric="co2_ppm"
        onlineCount={2}
        staleCount={2}
        sourceLabel="LIVE"
        mapped={false}
      />,
    );
    expect(html).toContain("현재 분포 산출 불가");
    expect(html).toContain("오래된 값 2개 제외");
  });

  it("교정 전 CO와 H₂S 분포 버튼은 비활성 상태다", () => {
    const html = renderToStaticMarkup(
      <TwinHeatmapPanel
        nodes={[]}
        wearable={null}
        samples={[]}
        metric="co2_ppm"
        onlineCount={0}
        sourceLabel="대기"
        mapped={false}
      />,
    );
    expect(html.match(/disabled/g)?.length).toBe(2);
    expect(html).toContain("교정 필요");
  });

  it("주의 이상 가스가 없으면 CO₂ 기본 분포와 산출 불가 경고를 띄우지 않는다", () => {
    const html = renderToStaticMarkup(
      <TwinHeatmapPanel
        nodes={[]}
        wearable={null}
        samples={[]}
        metric="co2_ppm"
        distributionEnabled={false}
        showMetricControls={false}
        onlineCount={0}
        sourceLabel="대기"
        mapped={false}
      />,
    );
    expect(html).not.toContain("가스 분포 대기");
    expect(html).not.toContain("주의 이상 시 원인 가스 표시");
    expect(html).not.toContain("현재 분포 산출 불가");
  });

  it("노출 데이터가 없으면 가짜 주요인과 위험 순위를 만들지 않는다", () => {
    const exposure = mockExposure("uncalibrated", Date.now());
    exposure.metrics = {};
    const html = renderToStaticMarkup(<ExposureDoseRow exposure={exposure} />);
    expect(html).not.toContain("주요인");
    expect(html).toContain("위험 순위 산출 불가");
  });

  it("경보 문구에 작업자·센서·예상 등급을 함께 표시한다", () => {
    const html = renderToStaticMarkup(
      <AlertBanner
        alert={{
          alert_key: "sensor-01:co2_ppm",
          node_id: "sensor-01",
          level: "level1_caution",
          trigger_value: 1200,
          threshold: 1000,
          activated_at: new Date().toISOString(),
          status: "active",
          resolved_at: null,
        }}
        workerName="김안전"
        projection={null}
      />,
    );
    expect(html).toContain("김안전 작업자에게 배정된");
    expect(html).toContain("S1 센서가");
    expect(html).toContain("L1 주의 단계로");
    expect(html).toContain("경보음 꺼짐");
  });
});
