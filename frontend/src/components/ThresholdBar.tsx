import { memo } from "react";
import { thresholdApproach } from "../utils/alerts";

/**
 * 임계값 대비 근접도 바.
 *
 * 블록 6칸으로 끊어 그린다. 연속 막대보다 원거리에서 "몇 칸 남았나"가 빨리 읽히고,
 * 관제 화면은 정밀 판독이 아니라 훑기용이다.
 *
 * 세 가지 상태를 구분한다.
 *   1. 채워진 바   — 서버 임계값 대비 현재값
 *   2. 판정 불가   — 임계값 미수신 또는 그 지표에 규칙 없음 → 빗금, 채우지 않음
 *   3. 미교정      — 값이 ppm 이 아니라 Rs/R0 저항비라 ppm 임계값과 비교 불가
 *
 * 2·3 을 빈 바(=여유 있음)로 그리면 모르는 상태가 안전하게 보인다 (이슈 #165).
 */
interface ThresholdBarProps {
  metric: string;
  value: number | null;
  /**
   * 미교정 MQ 센서. ppm 임계값과 단위가 달라 비교 자체가 성립하지 않는다.
   * 임의의 Rs/R0 만점 눈금을 만드는 것은 임계값 하드코딩이므로 하지 않는다 (FR-201).
   */
  uncalibrated?: boolean;
  /** 접근성 라벨용 지표 이름. */
  label: string;
}

const SEGMENTS = 6;

export const ThresholdBar = memo(function ThresholdBar({
  metric,
  value,
  uncalibrated = false,
  label,
}: ThresholdBarProps) {
  const approach = value === null || uncalibrated ? null : thresholdApproach(metric, value);

  if (!approach) {
    return (
      <span
        className="tbar tbar--indeterminate"
        role="img"
        aria-label={`${label} 임계값 대비 판정 불가`}
        title={uncalibrated ? "미교정 — ppm 임계값과 비교할 수 없음" : "임계값 없음"}
      >
        {Array.from({ length: SEGMENTS }, (_, i) => (
          <i key={i} className="tbar__seg" />
        ))}
      </span>
    );
  }

  const filled = Math.max(1, Math.ceil(approach.ratio * SEGMENTS));
  const pct = Math.round(approach.ratio * 100);

  return (
    <span
      className={"tbar is-" + approach.level}
      role="img"
      aria-label={`${label} ${approach.enter} 대비 ${pct}%`}
      title={`다음 임계값 ${approach.enter} 대비 ${pct}%`}
    >
      {Array.from({ length: SEGMENTS }, (_, i) => (
        <i key={i} className={"tbar__seg" + (i < filled ? " tbar__seg--on" : "")} />
      ))}
    </span>
  );
});
