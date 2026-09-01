// 누적 노출량 소진 예상 (⑤ 작업자 칸).
//
// `dose_fraction` 0.42 는 "허용량의 42% 를 썼다" 는 뜻인데, 그 숫자만으로는
// 위험한지 알 수 없다. 출근 30분 만의 42% 는 심각하고, 퇴근 30분 전의 42% 는
// 여유다. 같은 값이 정반대를 뜻한다.
//
// 그래서 "지금 속도로 계속 마시면 언제 100% 가 되는가" 를 한 줄 덧붙인다.
// **"42%" 는 상태 보고고, "27분 뒤" 는 행동을 유발한다** — 교대를 당길지
// 환기를 돌릴지 판단할 수 있게 된다.
//
// 이 값은 경보가 아니다. 서버가 보낸 alert_level 을 바꾸지 않고, dose_fraction
// 에서 등급을 역산하지도 않는다 (그건 FR-201 위반이다 — utils/exposure.ts 참고).

import type { ExposureDoseMetric } from "../types/ws";

/**
 * 이보다 멀면 숫자 대신 "여유" 로 쓴다.
 *
 * 노출 기준 자체가 8시간 기준이라 그 너머의 외삽은 근거가 없다. "13시간 뒤
 * 도달" 같은 문구는 정밀해 보이지만 실제로는 아무것도 말하지 않는다.
 */
export const DOSE_HORIZON_MIN = 480;

export interface DoseProjection {
  /** 한도(=1.0)까지 남은 분. */
  minutes: number;
  /** 적산 속도 (ppm·min/분). 참고용. */
  ratePpm: number;
}

/**
 * 한도 도달까지 남은 시간.
 *
 * 속도는 `twa_15min_ppm`(최근 15분 시간가중평균)을 쓴다. dose 는 농도 × 시간으로
 * 쌓이므로 ppm 값이 곧 분당 적산 속도다. 그 필드가 없으면 윈도우 전체 평균
 * (dose / 적산시간)으로 물러선다 — 최근 추세는 못 보지만 없는 것보다 낫다.
 *
 * null 을 돌려주는 경우:
 *   - 지표가 unavailable — 산출 불가를 "여유" 로 그리면 안 된다
 *   - 필요한 필드가 없다
 *   - 속도가 0 이하 — 안 마시고 있으면 도달하지 않는다
 *   - 이미 한도를 넘었다 — "몇 분 뒤" 가 아니라 이미 벌어진 일이다
 *   - 8시간보다 멀다 — 호출부가 "여유" 로 그린다
 *
 * @param accumulatedS 실제로 적산에 반영된 초. 측정 공백은 빠져 있다.
 */
export function doseProjection(
  metric: ExposureDoseMetric | undefined,
  accumulatedS: number,
): DoseProjection | null {
  if (!metric || metric.status !== "active") return null;

  const dose = metric.dose_ppm_min;
  const limit = metric.dose_limit_ppm_min;
  if (typeof dose !== "number" || typeof limit !== "number" || limit <= 0) return null;

  const remaining = limit - dose;
  // 이미 넘었다. 남은 시간을 음수로 말하지 않는다.
  if (remaining <= 0) return null;

  let rate = typeof metric.twa_15min_ppm === "number" ? metric.twa_15min_ppm : null;
  if (rate === null) {
    const minutes = accumulatedS / 60;
    rate = minutes > 0 ? dose / minutes : null;
  }
  if (rate === null || !Number.isFinite(rate) || rate <= 0) return null;

  const minutes = remaining / rate;
  if (!Number.isFinite(minutes) || minutes <= 0) return null;
  if (minutes > DOSE_HORIZON_MIN) return null;

  return { minutes, ratePpm: rate };
}

/** "27분 뒤" · 1시간이 넘으면 시간 단위로. */
export function formatDoseEta(minutes: number): string {
  const m = Math.round(minutes);
  if (m < 60) return `${m}분 뒤 한도 도달`;
  const h = Math.floor(m / 60);
  const rem = m % 60;
  return rem === 0 ? `${h}시간 뒤 한도 도달` : `${h}시간 ${rem}분 뒤 한도 도달`;
}
