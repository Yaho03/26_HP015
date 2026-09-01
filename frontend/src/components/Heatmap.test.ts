import { describe, expect, it } from "vitest";
import {
  buildGridIndices,
  buildVolumePositions,
  verticalConcentrationFactor,
  volumePointStyle,
} from "./Heatmap";

describe("buildGridIndices", () => {
  it("fills every heatmap cell with two triangles", () => {
    expect(Array.from(buildGridIndices(2, 2))).toEqual([0, 2, 1, 1, 2, 3]);
    expect(buildGridIndices(3, 3)).toHaveLength(24);
  });
});

describe("3D gas volume", () => {
  it("builds a dense field across horizontal cells and height layers", () => {
    const positions = buildVolumePositions(
      { minX: 0, maxX: 60, minY: -6.5, maxY: 6.5 },
      32,
      8,
      6.4,
    );
    expect(positions).toHaveLength(33 * 33 * 8 * 3);

    const heights = positions.filter((_, index) => index % 3 === 1);
    expect(Math.min(...heights)).toBeGreaterThan(0);
    expect(Math.max(...heights)).toBeCloseTo(6.4, 4);
  });

  it("keeps CO2 denser near the floor and expands upward at high concentration", () => {
    expect(verticalConcentrationFactor(0.5, 600)).toBeGreaterThan(
      verticalConcentrationFactor(5, 600),
    );
    expect(verticalConcentrationFactor(5, 5000)).toBeGreaterThan(
      verticalConcentrationFactor(5, 600),
    );
  });

  it("keeps normal gas particles subordinate to sensor markers", () => {
    const normal = volumePointStyle("normal");
    const warning = volumePointStyle("level2_warning");
    expect(normal.size).toBeLessThan(warning.size);
    expect(normal.opacity).toBeLessThan(warning.opacity);
  });
});
