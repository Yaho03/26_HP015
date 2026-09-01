import { describe, expect, it } from "vitest";
import { shouldShowEstimatedPeak } from "./TwinScene";

describe("estimated peak marker", () => {
  it("stays hidden while every sensor is normal", () => {
    expect(shouldShowEstimatedPeak(["normal", "normal", "normal", "normal"])).toBe(false);
  });

  it("appears when at least one sensor reaches caution", () => {
    expect(shouldShowEstimatedPeak(["normal", "level1_caution"])).toBe(true);
  });
});
