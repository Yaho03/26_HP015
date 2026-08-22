// 누적 노출량 표시 규약 (FR-701~708).
//
// 화면 두 곳(웨어러블 스트립 요약 ⑤ / 노출량 상세 화면)이 같은 값을 다른 밀도로
// 그린다. 라벨·사유 문구·등급 대응을 여기 한 곳에 두지 않으면 같은 상태가 칸마다
// 다른 말로 표시되고, 관제사가 같은 상태를 다른 상태로 읽는다.
//
// 이 파일은 **표시 전용**이다. 등급 판정은 서버가 보낸 alert_level 을 그대로 쓴다.
// dose_fraction 에서 등급을 역산하지 않는다 — 그건 임계값을 프론트에 하드코딩하는
// 것이고 FR-201 위반이다.

import type { AlertLevel } from "../types";
import type {
  ExposureDoseMetric,
  ExposureO2Metric,
  ExposureTrustLevel,
  ExposureUnavailableReason,
  WorkerExposureMessage,
} from "../types/ws";
import { maxLevel } from "./alerts";

/** 상세 화면이 그리는 순서. CO₂ 가 먼저인 이유는 유일하게 교정된 값이기 때문이다. */
export const EXPOSURE_DOSE_METRICS = [
  { key: "co2_ppm", label: "CO₂" },
  { key: "co_ppm", label: "CO" },
  { key: "h2s_ppm", label: "H₂S" },
] as const;

export type ExposureDoseKey = (typeof EXPOSURE_DOSE_METRICS)[number]["key"];

/**
 * 산출 불가 사유의 한국어 표기.
 *
 * 사유를 "측정 불가" 하나로 뭉뚱그리지 않는다. 교정하면 되는 것과 기준값 검증을
 * 기다려야 하는 것은 현장에서 할 일이 다르다.
 */
export const UNAVAILABLE_LABEL: Record<ExposureUnavailableReason, string> = {
  uncalibrated: "교정 필요",
  limit_unverified: "기준값 미검증",
  no_position: "위치 없음",
  no_source_node: "센서 없음",
  sensor_error: "센서 오류",
};

/** 왜 못 구하는지, 그래서 이 화면을 어떻게 읽어야 하는지. */
export const UNAVAILABLE_HINT: Record<ExposureUnavailableReason, string> = {
  uncalibrated:
    "MQ 센서 교정 전이라 ppm 으로 환산할 수 없습니다. 노출이 없다는 뜻이 아닙니다.",
  limit_unverified:
    "노출 기준값 원문 대조가 끝나지 않아 아직 시드하지 않았습니다. 검증되지 않은 숫자를 안전 기준으로 쓰지 않습니다.",
  no_position: "작업자 위치를 몰라 농도 출처 노드를 정할 수 없습니다.",
  no_source_node: "농도를 가져올 센서 노드가 없습니다.",
  sensor_error: "센서가 오류 상태입니다.",
};

/** O₂ 쪽은 사유 집합이 좁다 (types/ws.ts 참고). */
export const O2_UNAVAILABLE_LABEL: Record<
  NonNullable<ExposureO2Metric["reason"]>,
  string
> = {
  sensor_error: "센서 오류",
  not_connected: "미연결",
  no_position: "위치 없음",
};

export const TRUST_LABEL: Record<ExposureTrustLevel, string> = {
  high: "높음",
  medium: "보통",
  low: "낮음",
};

/**
 * trust_level 이 왜 내려갔는지.
 *
 * 서버가 사유 필드를 따로 주지 않으므로 화면은 "무엇을 의심해야 하는가"만 말한다.
 * 구체적 원인은 source_distance_m 과 data_gap_s 가 함께 보여 준다.
 */
export const TRUST_HINT: Record<ExposureTrustLevel, string> = {
  high: "농도 출처가 가깝고 측정 공백이 거의 없습니다.",
  medium: "농도 출처가 멀거나 측정 공백이 있습니다. 실제 노출은 표시값보다 클 수 있습니다.",
  low: "출처 거리·측정 공백이 커서 추정이 약합니다. 표시값을 하한으로 보십시오.",
};

/**
 * 지표 하나의 등급.
 *
 * 서버가 alert_level 을 안 보냈으면 "unknown" 이다. "normal" 로 떨어뜨리지 않는다 —
 * 판정 못 한 것을 안전하다고 표시하면 실제 위험이 초록으로 보인다 (이슈 #165).
 */
export function doseLevel(metric: ExposureDoseMetric | ExposureO2Metric | undefined): AlertLevel {
  if (!metric || metric.status === "unavailable") return "unknown";
  return metric.alert_level ?? "unknown";
}

/**
 * 메시지 전체에서 가장 높은 등급.
 *
 * 시드를 "unknown" 으로 두면 안 된다. LEVEL_RANK 에서 unknown 은 normal 보다
 * 위라(alerts.ts §LEVEL_RANK) 모든 지표가 정상인 메시지도 영영 unknown 으로
 * 나온다. 실제로 있는 지표만 접고, 지표가 하나도 없을 때만 unknown 이다.
 *
 * 반대로 지표 하나가 unavailable 이면 결과는 unknown 이 된다. 이건 의도한
 * 것이다 — 한 지표라도 판정 못 하면 그 사람을 정상이라 말할 수 없다.
 */
export function worstExposureLevel(msg: WorkerExposureMessage | null): AlertLevel {
  if (!msg) return "unknown";
  const present: AlertLevel[] = [];
  for (const { key } of EXPOSURE_DOSE_METRICS) {
    if (msg.metrics[key]) present.push(doseLevel(msg.metrics[key]));
  }
  if (msg.metrics.o2_pct) present.push(doseLevel(msg.metrics.o2_pct));
  if (present.length === 0) return "unknown";
  return present.reduce(maxLevel);
}

/**
 * 요약 칸에 띄울 대표 소진율 — 활성 지표 중 최댓값.
 *
 * 활성 지표가 하나도 없으면 null 이다. 0 을 돌려주면 호출부가 "0% 노출"로 그리게
 * 되고, 그게 정확히 §6.4 가 금지하는 표시다.
 */
export function worstDoseFraction(msg: WorkerExposureMessage | null): number | null {
  if (!msg) return null;
  let worst: number | null = null;
  for (const { key } of EXPOSURE_DOSE_METRICS) {
    const m = msg.metrics[key];
    if (!m || m.status !== "active") continue;
    const f = m.dose_fraction;
    if (typeof f !== "number") continue;
    if (worst === null || f > worst) worst = f;
  }
  return worst;
}

/** 활성 지표가 하나라도 있는가. 전부 unavailable 이면 화면 문구가 달라진다. */
export function hasActiveDose(msg: WorkerExposureMessage | null): boolean {
  if (!msg) return false;
  return EXPOSURE_DOSE_METRICS.some(({ key }) => msg.metrics[key]?.status === "active");
}

/** 소진율 표기. 1.0 을 넘을 수 있으므로 상한을 두지 않는다. */
export function formatFraction(fraction: number): string {
  return `${Math.round(fraction * 100)}%`;
}

/**
 * 초 → 사람이 읽는 길이.
 *
 * O₂ 는 농도가 아니라 결핍 상태에 있던 **시간**을 누적하므로(§2.4) 이 표기가
 * 노출량 화면 곳곳에서 쓰인다.
 */
export function formatDuration(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}초`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}분`;
  const h = Math.floor(m / 60);
  const rem = m % 60;
  return rem === 0 ? `${h}시간` : `${h}시간 ${rem}분`;
}

/** ppm·min 은 자릿수가 커서 천 단위 구분이 없으면 안 읽힌다. */
export function formatDose(ppmMin: number): string {
  return Math.round(ppmMin).toLocaleString();
}

/**
 * 면책 축약형 (11_EXPOSURE_DOSE_SPEC.md §1.1 필수).
 *
 * 전문이 §1.1 에 있고 이것은 그 축약형이다. 어긋나면 사양서가 정본이다.
 * 네 가지를 반드시 남긴다 — 법정 작업환경측정 대체 불가, 고정 노드 대입 추정값,
 * 기준값의 법적 지위, 최종 판단 주체. 하나라도 빠지면 축약이 아니라 왜곡이다.
 */
export const EXPOSURE_DISCLAIMER =
  "본 노출량은 개인 시료채취를 통한 법정 작업환경측정을 대체하지 않습니다. " +
  "고정 센서 노드의 측정값을 작업자 위치에 대입한 추정값이며, 노출 기준값은 참고 문헌 기반으로 " +
  "특정 국가의 법정 기준을 보증하지 않습니다. 최종 작업 중지 판단은 현장 관리자에게 있습니다.";
