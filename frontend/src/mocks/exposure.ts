// 노출량 목 데이터 (FR-701~708, A1).
//
// 백엔드 적산 서비스가 아직 스텁이라 화면을 이 데이터로 먼저 완성한다. A5 에서
// 실제 WebSocket 으로 교체하되 **이 파일은 남긴다** — 백엔드 없이 UI 를 확인하는
// 경로가 있어야 시연 리허설과 디버깅이 쉽다.
//
// 농도·시간·소진율은 화면 확인용 예시지만 limit 은 운영 DB 시드와 같아야 한다.
// 고용노동부고시 제2020-48호 별표 1을 대조한 값이며, DB 의 단일 소스는
// 011_exposure_limits.sql 이다. 둘이 어긋나면 데모 화면이 운영 화면과 다른 기준을
// 설명하게 되므로 테스트에서 정확값을 고정한다.
//
// CO·H₂S 가 active 로 나오는 목 상태(normal/warning/exceeded)는 MVP 에서는
// 발생하지 않는다 — MQ 센서 미교정으로 두 지표는 MVP 기간 내내 unavailable 이다
// (§7 한계 #2). 교정 이후의 렌더 경로를 미리 확인하려고 넣어 둔 것이다.

import { create } from "zustand";
import type { WorkerExposureMessage } from "../types/ws";

/** 목 데이터가 만들어내는 상태. 화면이 갈라지는 분기마다 하나씩 있다. */
export type ExposureMockState =
  | "normal"
  | "warning"
  | "exceeded"
  | "uncalibrated"
  | "limit_unverified";

export const EXPOSURE_MOCK_STATES: { key: ExposureMockState; label: string }[] = [
  { key: "normal", label: "정상" },
  { key: "warning", label: "경고" },
  { key: "exceeded", label: "초과" },
  { key: "uncalibrated", label: "미교정" },
  { key: "limit_unverified", label: "기준값 미검증" },
];

export const MOCK_NODE_ID = "wearable-01";

// 검증된 기준값 (ppm·min). 8시간 = 480분 기준의 산술 곱이다.
const LIMIT = {
  co2_ppm: 5000 * 480,
  co_ppm: 30 * 480,
  h2s_ppm: 10 * 480,
} as const;

function iso(now: number, offsetSeconds = 0): string {
  return new Date(now + offsetSeconds * 1000).toISOString();
}

/**
 * 상태 하나에 대한 목 메시지.
 *
 * `now` 를 주입받는 이유는 테스트 때문이다. Date.now() 를 안에서 부르면 스냅샷이
 * 매번 달라져서 시간 표기 로직을 검증할 수 없다.
 */
export function mockExposure(
  state: ExposureMockState,
  now: number = Date.now(),
): WorkerExposureMessage {
  const base = {
    type: "worker_exposure" as const,
    worker_id: 7,
    worker_name: "홍길동",
    node_id: MOCK_NODE_ID,
    exposure_id: `mock-${state}`,
    window_source: "assignment" as const,
    timestamp: iso(now),
  };

  switch (state) {
    // 소진율이 낮고 출처도 가깝다. 게이지가 여유 구간에 머무는 기준 화면.
    case "normal":
      return {
        ...base,
        window_start: iso(now, -7200),
        elapsed_s: 7200,
        accumulated_s: 7180,
        data_gap_s: 20,
        trust_level: "high",
        metrics: {
          co2_ppm: dose(0.2, LIMIT.co2_ppm, 480, {
            source_distance_m: 1.1,
            peak_ppm: 1240,
            peak_at: iso(now, -2600),
            alert_level: "normal",
          }),
          co_ppm: dose(0.12, LIMIT.co_ppm, 480, {
            source_distance_m: 1.1,
            peak_ppm: 6.2,
            peak_at: iso(now, -1900),
            alert_level: "normal",
          }),
          h2s_ppm: dose(0.08, LIMIT.h2s_ppm, 480, {
            source_distance_m: 1.1,
            peak_ppm: 0.31,
            peak_at: iso(now, -4100),
            alert_level: "normal",
          }),
          o2_pct: {
            status: "active",
            exposure_source: "wearable_direct",
            o2_deficient_s: 0,
            o2_severe_s: 0,
            o2_enriched_s: 0,
            o2_min_pct: 20.6,
            alert_level: "normal",
          },
        },
      };

    // 출처 노드가 멀어 trust 가 내려간 상태. 소진율은 아직 1.0 미만이다.
    case "warning":
      return {
        ...base,
        window_start: iso(now, -12600),
        elapsed_s: 12600,
        accumulated_s: 11940,
        data_gap_s: 660,
        trust_level: "medium",
        metrics: {
          co2_ppm: dose(0.85, LIMIT.co2_ppm, 480, {
            source_distance_m: 2.4,
            peak_ppm: 4180,
            peak_at: iso(now, -3300),
            twa_15min_ppm: 3960,
            alert_level: "level2_warning",
          }),
          co_ppm: dose(0.62, LIMIT.co_ppm, 480, {
            source_distance_m: 2.4,
            peak_ppm: 21.4,
            peak_at: iso(now, -3100),
            alert_level: "level1_caution",
          }),
          h2s_ppm: dose(0.45, LIMIT.h2s_ppm, 480, {
            source_distance_m: 2.4,
            peak_ppm: 0.94,
            peak_at: iso(now, -5200),
            alert_level: "level1_caution",
          }),
          o2_pct: {
            status: "active",
            exposure_source: "wearable_direct",
            o2_deficient_s: 320,
            o2_severe_s: 0,
            o2_enriched_s: 0,
            o2_min_pct: 19.1,
            alert_level: "level1_caution",
          },
        },
      };

    // 1.0 을 넘긴 상태. 게이지가 100% 에서 멈추면 안 되는 이유가 이 화면이다.
    case "exceeded":
      return {
        ...base,
        window_start: iso(now, -21600),
        elapsed_s: 21600,
        accumulated_s: 20100,
        data_gap_s: 1500,
        trust_level: "low",
        metrics: {
          co2_ppm: dose(1.15, LIMIT.co2_ppm, 480, {
            source_distance_m: 4.8,
            peak_ppm: 6820,
            peak_at: iso(now, -7400),
            twa_15min_ppm: 5210,
            alert_level: "level3_critical",
          }),
          co_ppm: dose(0.9, LIMIT.co_ppm, 480, {
            source_distance_m: 4.8,
            peak_ppm: 44.5,
            peak_at: iso(now, -7100),
            alert_level: "level2_warning",
          }),
          h2s_ppm: dose(1.05, LIMIT.h2s_ppm, 480, {
            source_distance_m: 4.8,
            peak_ppm: 6.1,
            peak_at: iso(now, -6900),
            twa_15min_ppm: 5.4,
            stel_limit_ppm: 5,
            stel_exceeded: true,
            alert_level: "level3_critical",
          }),
          o2_pct: {
            status: "active",
            exposure_source: "wearable_direct",
            o2_deficient_s: 1180,
            o2_severe_s: 240,
            o2_enriched_s: 0,
            o2_min_pct: 15.4,
            alert_level: "level3_critical",
          },
        },
      };

    // MQ 센서 교정 전. CO·H₂S 는 값 자체가 없다 — 0% 로 그리면 안 되는 케이스.
    case "uncalibrated":
      return {
        ...base,
        window_start: iso(now, -3600),
        elapsed_s: 3600,
        accumulated_s: 3580,
        data_gap_s: 20,
        trust_level: "high",
        metrics: {
          co2_ppm: dose(0.31, LIMIT.co2_ppm, 480, {
            source_distance_m: 1.4,
            peak_ppm: 1680,
            peak_at: iso(now, -1200),
            alert_level: "normal",
          }),
          co_ppm: { status: "unavailable", reason: "uncalibrated" },
          h2s_ppm: { status: "unavailable", reason: "uncalibrated" },
          o2_pct: {
            status: "active",
            exposure_source: "wearable_direct",
            o2_deficient_s: 0,
            o2_severe_s: 0,
            o2_enriched_s: 0,
            o2_min_pct: 20.9,
            alert_level: "normal",
          },
        },
      };

    // exposure_limits 미시드 상태 (A2 §3.2). 교정은 됐는데 비교할 기준이 없다.
    case "limit_unverified":
      return {
        ...base,
        window_start: iso(now, -5400),
        elapsed_s: 5400,
        accumulated_s: 5400,
        data_gap_s: 0,
        trust_level: "high",
        metrics: {
          co2_ppm: { status: "unavailable", reason: "limit_unverified" },
          co_ppm: { status: "unavailable", reason: "limit_unverified" },
          h2s_ppm: { status: "unavailable", reason: "limit_unverified" },
          o2_pct: {
            status: "active",
            exposure_source: "wearable_direct",
            o2_deficient_s: 45,
            o2_severe_s: 0,
            o2_enriched_s: 0,
            o2_min_pct: 19.4,
            alert_level: "level1_caution",
          },
        },
      };
  }
}

type DoseExtras = Partial<
  Omit<
    NonNullable<WorkerExposureMessage["metrics"]["co2_ppm"]>,
    "status" | "dose_ppm_min" | "dose_limit_ppm_min" | "dose_fraction" | "twa_8h_ppm"
  >
>;

/**
 * dose / limit / TWA 를 서로 어긋나지 않게 만든다.
 *
 * 손으로 세 숫자를 적으면 반드시 어긋나고, 화면에서는 그게 계산 버그처럼 보인다.
 */
function dose(
  fraction: number,
  limit: number,
  windowMinutes: number,
  extras: DoseExtras = {},
): NonNullable<WorkerExposureMessage["metrics"]["co2_ppm"]> {
  const accumulated = limit * fraction;
  return {
    status: "active",
    exposure_source: "nearest_node",
    source_node_id: "sensor-01",
    dose_ppm_min: accumulated,
    dose_limit_ppm_min: limit,
    dose_fraction: fraction,
    // 전 노드 최댓값 기준. 표시 전용이며 경보 판정에 쓰지 않는다 (ADR-008).
    dose_worst_case_ppm_min: accumulated * 1.18,
    twa_8h_ppm: accumulated / windowMinutes,
    ...extras,
  };
}

interface ExposureMockStore {
  /** 목 모드 사용 여부. 운영 빌드에서는 기본 꺼짐. */
  enabled: boolean;
  state: ExposureMockState;
  /**
   * 목 메시지의 기준 시각.
   *
   * 스토어가 들고 있는 이유는 렌더 순수성 때문이다. useMemo 안에서 Date.now() 를
   * 부르면 렌더가 비순수해져서 리렌더마다 결과가 흔들린다. 시각은 토글이라는
   * **이벤트**가 정하는 값이므로 이벤트 핸들러에서 찍는다.
   */
  seed: number;
  setEnabled: (enabled: boolean) => void;
  setState: (state: ExposureMockState) => void;
}

/**
 * 목 토글은 dashboardStore 에 넣지 않는다.
 *
 * dashboardStore 는 서버가 보낸 것만 담는 곳이다. 목 여부가 거기 섞이면 화면이
 * 보고 있는 값이 실측인지 가짜인지 스토어만 보고는 알 수 없게 된다.
 */
export const useExposureMock = create<ExposureMockStore>((set) => ({
  // 기본 꺼짐. A1 에서는 백엔드가 스텁이라 개발 모드에서 자동으로 켰지만, 이제
  // 적산 서비스가 실제로 돈다 (A3~A5). 목이 기본이면 시연 중에 켜둔 것을 잊고
  // 진짜 경보를 못 보게 된다. 필요할 때 노출량 화면에서 직접 켠다.
  enabled: false,
  state: "normal",
  seed: Date.now(),
  setEnabled: (enabled) => set({ enabled, seed: Date.now() }),
  setState: (state) => set({ state, seed: Date.now() }),
}));
