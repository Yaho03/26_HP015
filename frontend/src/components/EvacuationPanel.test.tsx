import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { MOCK_TOPOLOGY } from "../mocks/evacuation";
import { EvacuationPanel } from "./EvacuationPanel";

vi.mock("../hooks/useEvacuationStatus", () => ({
  useEvacuationStatus: () => null,
}));

describe("EvacuationPanel", () => {
  it("keeps demo controls reachable while the live route is unavailable", () => {
    const html = renderToStaticMarkup(
      <EvacuationPanel route={null} topology={MOCK_TOPOLOGY}>
        <button type="button">안전 경로 목 보기</button>
      </EvacuationPanel>,
    );

    expect(html).toContain("경로 정보 없음");
    expect(html).toContain("안전 경로 목 보기");
  });
});
