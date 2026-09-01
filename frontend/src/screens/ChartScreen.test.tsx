import { describe, expect, it } from "vitest";
import { buildWideCsv } from "./ChartScreen";
import { NODE_METRICS } from "../utils/metrics";

describe("buildWideCsv", () => {
  it("같은 시각의 모든 지표를 센서별 한 행으로 합치고 느린 지표는 최신값을 유지한다", () => {
    const csv = buildWideCsv(NODE_METRICS, {
      "sensor-01": {
        co2_ppm: [
          { time: "2026-08-25T00:00:00Z", value: 500 },
          { time: "2026-08-25T00:00:01Z", value: 510 },
        ],
        temperature_c: [{ time: "2026-08-25T00:00:00Z", value: 24.5 }],
      },
      "sensor-02": {
        co2_ppm: [{ time: "2026-08-25T00:00:00Z", value: 600 }],
      },
    });

    const lines = csv.split("\n");
    expect(lines[0]).toBe("time,node_id,co2_ppm,co_ppm,h2s_ppm,temperature_c,humidity_pct,gas_resistance_ohm");
    expect(lines[1]).toBe("2026-08-25T00:00:00Z,sensor-01,500,,,24.5,,");
    expect(lines[2]).toBe("2026-08-25T00:00:01Z,sensor-01,510,,,24.5,,");
    expect(lines[3]).toBe("2026-08-25T00:00:00Z,sensor-02,600,,,,,");
  });
});
