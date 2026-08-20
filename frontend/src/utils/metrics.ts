// 센서 노드 지표의 표시 메타와 교정 상태 판정.
//
// 화면 여러 곳(② 위험 상세 / ③ 요약 카드 / ⑤ 노드별 표)이 같은 지표를 다른 밀도로
// 그린다. 라벨·단위·자릿수·교정 대응 관계를 여기 한 곳에 두지 않으면 칸마다 조금씩
// 다른 표기가 생기고, 관제사가 같은 값을 다른 값으로 읽는다.

import type { CalibrationKey, CalibrationState, MetricKey, SensorNodeState } from "../types";
import type { TrendMetric } from "../store/dashboardStore";

export interface MetricMeta {
  key: TrendMetric;
  label: string;
  unit: string;
  /** 교정이 필요한 지표면 그 교정 상태 키. 없으면 교정 개념이 없는 지표다. */
  calibration?: CalibrationKey;
  /**
   * 질식 유발 가스인가. 이 시스템의 질식 가스는 CO₂(단순질식+독성),
   * CO·H₂S(화학적 질식), O₂ 결핍 4종이다. 온도·습도·가스저항은 질식과 무관하므로
   * 정상 상태 카드(③)에 띄우지 않는다.
   */
  asphyxiant: boolean;
  decimals: number;
  /** 표시 단위로 환산. 가스저항만 Ω → kΩ 로 줄여 읽는다. */
  scale?: number;
}

/** 센서 노드가 보내는 6종. O₂ 는 웨어러블에만 있어 여기 없다. */
export const NODE_METRICS: readonly MetricMeta[] = [
  { key: "co2_ppm", label: "CO₂", unit: "ppm", asphyxiant: true, decimals: 0 },
  {
    key: "co_ppm",
    label: "CO",
    unit: "ppm",
    calibration: "co_calibration_status",
    asphyxiant: true,
    decimals: 1,
  },
  {
    key: "h2s_ppm",
    label: "H₂S",
    unit: "ppm",
    calibration: "h2s_calibration_status",
    asphyxiant: true,
    decimals: 2,
  },
  {
    key: "temperature_c",
    label: "온도",
    unit: "℃",
    asphyxiant: false,
    decimals: 1,
  },
  {
    key: "humidity_pct",
    label: "습도",
    unit: "%",
    asphyxiant: false,
    decimals: 0,
  },
  {
    key: "gas_resistance_ohm",
    label: "가스저항",
    unit: "kΩ",
    asphyxiant: false,
    decimals: 1,
    scale: 1 / 1000,
  },
];

export const ASPHYXIANT_METRICS = NODE_METRICS.filter((m) => m.asphyxiant);

export function metaFor(key: MetricKey): MetricMeta | undefined {
  return NODE_METRICS.find((m) => m.key === key);
}

/** 표시 문자열. 단위는 붙이지 않는다 — 호출부가 라벨과 함께 배치한다. */
export function formatMetricValue(meta: MetricMeta, value: number): string {
  const scaled = value * (meta.scale ?? 1);
  return meta.decimals === 0 ? Math.round(scaled).toLocaleString() : scaled.toFixed(meta.decimals);
}

export function calibrationOf(
  node: SensorNodeState | null,
  meta: MetricMeta,
): CalibrationState | null {
  if (!meta.calibration) return null;
  return node?.calibration_status?.[meta.calibration] ?? "not_started";
}

/**
 * 미교정 MQ 센서가 보내는 값은 ppm 이 아니라 Rs/R0 저항비다.
 * 이 값을 ppm 처럼 크게 띄우면 오독을 부르므로, 호출부는 이 판정으로
 * 수치 표시 방식을 바꾼다 (③ 은 아예 수치를 숨기고 상태 칩만 띄운다).
 */
export function isUncalibrated(node: SensorNodeState | null, meta: MetricMeta): boolean {
  const cal = calibrationOf(node, meta);
  return cal !== null && cal !== "done";
}

/** ③ 카드의 상태 칩. 등급을 매길 수 있는 상태인지부터 갈라 낸다. */
export type MetricChipState = "graded" | "uncal" | "warm" | "err" | "na";

export function metricChipState(node: SensorNodeState | null, meta: MetricMeta): MetricChipState {
  if (!node?.readings[meta.key]) return "na";
  switch (calibrationOf(node, meta)) {
    case null:
    case "done":
      return "graded";
    case "in_progress":
      return "warm";
    case "error":
      return "err";
    default:
      return "uncal";
  }
}

export const CHIP_LABEL: Record<Exclude<MetricChipState, "graded">, string> = {
  uncal: "UNCAL",
  warm: "WARM",
  err: "ERR",
  na: "N/A",
};

/** 값의 단위 표기. 미교정이면 ppm 이 아니라 Rs/R0 이라고 밝힌다. */
export function unitFor(node: SensorNodeState | null, meta: MetricMeta): string {
  return isUncalibrated(node, meta) ? "Rs/R0" : meta.unit;
}
