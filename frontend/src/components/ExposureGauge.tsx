import { memo, useId } from "react";
import type { ExposureDoseMetric, ExposureTrustLevel } from "../types/ws";
import {
  doseLevel,
  formatDose,
  formatFraction,
  TRUST_HINT,
  UNAVAILABLE_HINT,
  UNAVAILABLE_LABEL,
} from "../utils/exposure";

/**
 * 누적 노출량 게이지.
 *
 * 세 가지를 반드시 구분해서 그린다.
 *
 *   1. 활성      — 소진율만큼 채운 호. 등급색은 서버 alert_level 을 따른다
 *   2. 산출 불가 — 빗금 트랙 + 사유 문구. **절대 0% 로 그리지 않는다.** 측정 못 한
 *                  것을 "노출 없음"으로 보여주면 안전하다고 오해한다 (§6.4)
 *   3. 초과      — 1.0 을 넘으면 안쪽에 두 번째 호가 돈다. 누적값은 100% 에서
 *                  멈추지 않으므로 게이지가 꽉 찬 상태로 수렴해 버리면, 110% 와
 *                  300% 가 같은 그림이 된다
 *
 * trust_level 이 high 가 아니면 채운 호 위에 빗금을 덮는다. 값은 보여주되 "이
 * 숫자를 그대로 믿지 말라"는 신호를 같은 자리에서 준다.
 */
interface ExposureGaugeProps {
  label: string;
  metric: ExposureDoseMetric | undefined;
  trust: ExposureTrustLevel;
  /** 눈금과 수치를 줄인 축소판. 카드 안에 여러 개 늘어놓을 때 쓴다. */
  compact?: boolean;
}

const CX = 50;
const CY = 50;
const R = 38;
const R_OVER = 28;
const START = 135;
const SWEEP = 270;

/** 게이지 눈금. 임계값이 아니라 **읽기 보조선**이다 — 판정은 서버 alert_level 이 한다. */
const TICKS = [0.5, 0.8, 1.0];

function polar(r: number, deg: number): [number, number] {
  const rad = (deg * Math.PI) / 180;
  return [CX + r * Math.cos(rad), CY + r * Math.sin(rad)];
}

function arc(r: number, fromDeg: number, toDeg: number): string {
  const [x1, y1] = polar(r, fromDeg);
  const [x2, y2] = polar(r, toDeg);
  const large = toDeg - fromDeg > 180 ? 1 : 0;
  return `M${x1.toFixed(2)} ${y1.toFixed(2)} A${r} ${r} 0 ${large} 1 ${x2.toFixed(2)} ${y2.toFixed(2)}`;
}

export const ExposureGauge = memo(function ExposureGauge({
  label,
  metric,
  trust,
  compact = false,
}: ExposureGaugeProps) {
  const uid = useId();
  const hatchId = `hatch-${uid}`;
  const level = doseLevel(metric);
  const unavailable = !metric || metric.status === "unavailable";
  const reason = metric?.status === "unavailable" ? metric.reason : undefined;

  const fraction = metric?.status === "active" ? (metric.dose_fraction ?? null) : null;
  const exceeded = fraction !== null && fraction > 1;
  const suspect = trust !== "high";

  const mainTo = START + SWEEP * Math.min(fraction ?? 0, 1);
  // 초과분도 한 바퀴로 잘라 그린다. 300% 를 세 바퀴 돌리면 읽을 수 없다 —
  // 정확한 배수는 옆의 수치가 말하고, 호는 "넘쳤다"만 전달한다.
  const overTo = START + SWEEP * Math.min(Math.max((fraction ?? 0) - 1, 0), 1);

  const ariaLabel = unavailable
    ? `${label} 누적 노출량 산출 불가 — ${reason ? UNAVAILABLE_LABEL[reason] : "사유 없음"}`
    : `${label} 누적 노출량 기준 대비 ${formatFraction(fraction ?? 0)}${exceeded ? " 초과" : ""}`;

  return (
    <figure
      className={
        "egauge is-" +
        level +
        (compact ? " egauge--compact" : "") +
        (unavailable ? " egauge--na" : "") +
        (exceeded ? " egauge--over" : "")
      }
    >
      {/* 링과 캡션을 한 상자에 묶는다. 캡션을 음수 마진으로 끌어올리면 폰트
          높이가 바뀔 때마다 중심이 어긋난다 — 여기서는 inset:0 으로 정중앙이다. */}
      <div className="egauge__ring">
        <svg className="egauge__svg" viewBox="0 0 100 100" role="img" aria-label={ariaLabel}>
          <defs>
            <pattern
              id={hatchId}
              width="6"
              height="6"
              patternUnits="userSpaceOnUse"
              patternTransform="rotate(45)"
            >
              <rect width="3" height="6" fill="currentColor" opacity="0.55" />
            </pattern>
          </defs>

          <path className="egauge__track" d={arc(R, START, START + SWEEP)} />

          {/* 산출 불가는 빈 트랙이 아니라 빗금이다. 빈 트랙은 "여유 있음"으로 읽힌다. */}
          {unavailable && (
            <path
              className="egauge__na-arc"
              d={arc(R, START, START + SWEEP)}
              stroke={`url(#${hatchId})`}
            />
          )}

          {!unavailable && fraction !== null && fraction > 0 && (
            <>
              <path className="egauge__value" d={arc(R, START, mainTo)} />
              {suspect && (
                <path
                  className="egauge__suspect"
                  d={arc(R, START, mainTo)}
                  stroke={`url(#${hatchId})`}
                />
              )}
            </>
          )}

          {exceeded && <path className="egauge__over" d={arc(R_OVER, START, overTo)} />}

          {TICKS.map((t) => {
            const deg = START + SWEEP * t;
            const [x1, y1] = polar(R - 7, deg);
            const [x2, y2] = polar(R + 5, deg);
            return (
              <line
                key={t}
                className={"egauge__tick" + (t === 1 ? " egauge__tick--limit" : "")}
                x1={x1}
                y1={y1}
                x2={x2}
                y2={y2}
              />
            );
          })}
        </svg>

        <figcaption className="egauge__cap">
          <span className="egauge__label">{label}</span>
          {unavailable ? (
            <strong
              className="egauge__na-text"
              title={reason ? UNAVAILABLE_HINT[reason] : undefined}
            >
              {reason ? UNAVAILABLE_LABEL[reason] : "산출 불가"}
            </strong>
          ) : (
            <strong className="egauge__pct">{formatFraction(fraction ?? 0)}</strong>
          )}
        </figcaption>
      </div>

      {exceeded && <span className="egauge__badge">기준 초과</span>}
      {!unavailable && suspect && (
        <span className="egauge__trust" title={TRUST_HINT[trust]}>
          추정 약함
        </span>
      )}

      {!compact && !unavailable && (
        <dl className="egauge__facts">
          <div>
            <dt>누적</dt>
            <dd>
              {metric?.dose_ppm_min != null ? formatDose(metric.dose_ppm_min) : "—"}
              <em>ppm·min</em>
            </dd>
          </div>
          <div>
            <dt>기준</dt>
            <dd>
              {metric?.dose_limit_ppm_min != null ? formatDose(metric.dose_limit_ppm_min) : "—"}
              <em>ppm·min</em>
            </dd>
          </div>
        </dl>
      )}
    </figure>
  );
});
