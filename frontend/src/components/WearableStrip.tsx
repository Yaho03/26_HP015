import type { ComponentType } from "react";
import type { AlertLevel, WearableState } from "../types";
import type { AssignedWorker } from "../services/api";
import { classifyO2High, classifyO2Low, levelLabel, maxLevel } from "../utils/alerts";
import { useExposure } from "../hooks/useExposure";
import {
  doseLevel,
  EXPOSURE_DOSE_METRICS,
  formatDuration,
  formatFraction,
  TRUST_LABEL,
  type ExposureDoseKey,
} from "../utils/exposure";
import { doseProjection, formatDoseEta } from "../utils/doseProjection";
import { LEVEL_ICON } from "./icons";
import type { WorkerExposureMessage } from "../types/ws";

interface WearableStripProps {
  node_id: string;
  wearable: WearableState | null;
  worker: AssignedWorker | null;
}

/** 위치 품질 구간 (10_UI_FLOW §3.3). UWB 미연동이면 "대기". */
function quality(q: WearableState["location_quality"]): {
  text: string;
  cls: string;
} {
  if (!q) return { text: "대기", cls: "wstrip__q--pending" };
  if (q.quality_score >= 0.8)
    return { text: `GOOD (${q.anchor_count} anchor)`, cls: "wstrip__q--good" };
  if (q.quality_score >= 0.5)
    return { text: `FAIR (${q.anchor_count} anchor)`, cls: "wstrip__q--fair" };
  return { text: `POOR (${q.anchor_count} anchor)`, cls: "wstrip__q--poor" };
}

function batteryClass(pct: number | null): string {
  if (pct === null) return "";
  if (pct < 20) return "bat-low";
  if (pct < 50) return "bat-mid";
  return "bat-ok";
}

/**
 * 웨어러블 상태 스트립.
 *
 * 2×2 안에 5번째 칸으로 끼워넣지 않는다. 웨어러블은 고정 계측점이 아니라
 * **사람**이고, 축이 다르다 (O₂·심박·낙상 vs CO₂·CO·H₂S). 같은 격자에 넣으면
 * 센서 노드와 같은 종류의 것으로 읽혀서 비교 대상이 아닌 값끼리 비교하게 된다.
 */
export function WearableStrip({ node_id, wearable, worker }: WearableStripProps) {
  const o2 = wearable?.o2_pct ?? null;
  // 값이 없으면 판정 불가다 (이슈 #165). 측정 못 한 것을 정상이라 하면 안 된다.
  const o2Level: AlertLevel =
    o2 !== null ? maxLevel(classifyO2Low(o2), classifyO2High(o2)) : "unknown";
  const fall = wearable?.fall_detected ?? false;
  // 낙상 또는 O₂ 이상이면 줄 전체가 승격된다 (§3.3).
  const stripLevel: AlertLevel = fall ? "level3_critical" : o2Level;
  const q = quality(wearable?.location_quality);
  // 이 슬롯이 지금 값을 보내고 있는가. 보고가 없는 슬롯을 "대기" 로 두어야
  // 두 명이 들어갔는데 한 명만 보이는 상황을 화면에서 알아챈다.
  const tracking = !!wearable && wearable.connection_status === "online";
  const Icon = LEVEL_ICON[stripLevel] as ComponentType<{
    size?: number | string;
  }>;

  // 누적 노출량 요약 (11_EXPOSURE_DOSE_SPEC §6.4 — 요약은 웨어러블 영역, 상세는 별도 화면).
  // 줄 전체의 등급(stripLevel)은 건드리지 않는다. 노출량 경보는 자동 해제되지
  // 않으므로(§5.2) 스트립을 승격시키면 윈도우가 끝날 때까지 줄이 계속 붉게 남아
  // 낙상·O₂ 같은 즉시 대응이 필요한 상태를 덮어 버린다.
  const { exposure } = useExposure(node_id);
  // 가장 많이 소진된 지표. **자리를 바꾸지 않고 이 칸만 강조한다** — 순위대로
  // 재정렬하면 "CO₂ 는 항상 맨 왼쪽" 이라는 공간 기억이 깨져서, 볼 때마다 라벨을
  // 다시 읽어야 한다. 경계에서 순위가 흔들리면 표가 초 단위로 뒤바뀌기도 한다.
  const worstKey = worstDoseKey(exposure);

  return (
    <>
    <div
      className={"wstrip is-" + stripLevel + (fall ? " wstrip--fall" : "")}
      aria-label={`${worker ? worker.name : node_id} ${fall ? "낙상 감지" : levelLabel(o2Level)}`}
    >
      <span className="wstrip__who">
        <Icon size={13} />
        {worker ? (
          <>
            <strong>{worker.name}</strong>
            {/* 착용 중인 웨어러블. 대피 지시는 사람 이름으로 하지만, 값이
                이상할 때 현장에서 확인해야 하는 것은 이 장비다. */}
            <em className="wstrip__device">{node_id}</em>
          </>
        ) : (
          // 밀폐공간에서 "누가 안에 있는지" 모르는 것은 그 자체가 위험 정보다.
          <>
            <strong className="wstrip__who--none">미배정</strong>
            <em className="wstrip__device">{node_id}</em>
          </>
        )}
      </span>

      {/* 측정 중인지부터 밝힌다. 아래 숫자들이 지금 값인지 멈춘 값인지를
          가르는 정보라 다른 항목보다 앞에 온다. */}
      <span className={"wstrip__track" + (tracking ? " is-live" : "")}>
        <span className="wstrip__track-dot" aria-hidden="true" />
        {tracking ? "측정중" : "대기"}
      </span>

      <span className="wstrip__fact">
        <span className="wstrip__label">O₂</span>
        <strong>{o2 !== null ? `${o2.toFixed(1)}%` : "—"}</strong>
      </span>
      <span className="wstrip__fact">
        <span className="wstrip__label">심박</span>
        <strong>
          {wearable?.heart_rate !== null && wearable?.heart_rate !== undefined
            ? wearable.heart_rate
            : "—"}
        </strong>
      </span>
      <span className="wstrip__fact">
        <span className="wstrip__label">낙상</span>
        <strong className={fall ? "wstrip__fall" : ""}>{fall ? "감지" : "정상"}</strong>
      </span>
      <span className="wstrip__fact">
        <span className="wstrip__label">배터리</span>
        <strong className={batteryClass(wearable?.battery_pct ?? null)}>
          {wearable?.battery_pct !== null && wearable?.battery_pct !== undefined
            ? `${wearable.battery_pct}%`
            : "—"}
        </strong>
      </span>
      <span className="wstrip__fact">
        <span className="wstrip__label">위치품질</span>
        <strong className={q.cls}>{q.text}</strong>
      </span>
      {exposure && (
        <span className="wstrip__fact">
          <span className="wstrip__label">진입</span>
          <strong>{formatClock(exposure.window_start)}</strong>
        </span>
      )}
      {exposure && (
        <span className="wstrip__fact">
          <span className="wstrip__label">경과</span>
          <strong>{formatDuration(exposure.elapsed_s)}</strong>
        </span>
      )}
      {exposure && (
        <span className="wstrip__fact">
          <span className="wstrip__label">신뢰도</span>
          <strong className={"wstrip__trust is-" + exposure.trust_level}>
            {TRUST_LABEL[exposure.trust_level]}
          </strong>
        </span>
      )}

      {fall && (
        <span className="wstrip__overlay" role="alert">
          FALL DETECTED
        </span>
      )}
    </div>

    <ExposureDoseRow exposure={exposure} worstKey={worstKey} />
    </>
  );
}

/** 소진율이 가장 높은 지표. 활성 지표가 없으면 null. */
function worstDoseKey(msg: WorkerExposureMessage | null): ExposureDoseKey | null {
  if (!msg) return null;
  let key: ExposureDoseKey | null = null;
  let worst = -1;
  for (const { key: k } of EXPOSURE_DOSE_METRICS) {
    const m = msg.metrics[k];
    if (!m || m.status !== "active") continue;
    const f = m.dose_fraction;
    if (typeof f !== "number") continue;
    if (f > worst) {
      worst = f;
      key = k;
    }
  }
  return key;
}

function formatClock(iso: string): string {
  return new Date(iso).toLocaleTimeString("ko-KR", {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
  });
}

/**
 * ⑤ 누적 가스 4종.
 *
 * **자리는 고정이다.** CO₂ · CO · H₂S · O₂ 순서를 바꾸지 않는다 — 위험한 순서로
 * 재정렬하면 직관적으로는 맞아 보이지만, 관제사는 "CO₂ 는 항상 맨 왼쪽" 이라는
 * 공간 기억으로 읽는다. 자리가 움직이면 매번 라벨을 다시 읽어야 하고, 경계에서
 * 순위가 진동하면 표가 초 단위로 뒤바뀐다. 대신 가장 위험한 칸만 강조한다.
 *
 * O₂ 는 몸에 쌓이지 않는다. 결핍 상태에 있던 **시간**을 누적하므로(§2.4) 소진율
 * 바가 아니라 시간 세 줄로 그린다. 같은 모양으로 그리면 다른 개념이 같은 것으로
 * 읽힌다.
 */
export function ExposureDoseRow({
  exposure,
  worstKey,
}: {
  exposure: WorkerExposureMessage | null;
  worstKey: ExposureDoseKey | null;
}) {
  const o2 = exposure?.metrics.o2_pct;

  return (
    <div className="dose-row" aria-label="누적 노출량 4종">
      {EXPOSURE_DOSE_METRICS.map(({ key, label }) => {
        const m = exposure?.metrics[key];
        const level = doseLevel(m);
        const active = m?.status === "active";
        const fraction = active && typeof m.dose_fraction === "number" ? m.dose_fraction : null;
        const isWorst = key === worstKey;
        // 소진 예상은 가장 위험한 한 칸에만 붙인다. 네 칸 전부에 붙이면 글자가
        // 많아져 오히려 안 읽힌다.
        const eta = isWorst ? doseProjection(m, exposure?.accumulated_s ?? 0) : null;

        return (
          <div
            key={key}
            className={
              "dose-cell is-" + level + (isWorst ? " dose-cell--worst" : "")
            }
          >
            <div className="dose-cell__head">
              <span className="dose-cell__label">{label}</span>
              {isWorst && <span className="dose-cell__flag">주요인</span>}
              <span className="dose-cell__pct">
                {/* 산출 불가를 0% 로 그리지 않는다 (§6.4 MUST) — 측정 못 한 것을
                    노출 없음으로 보여주면 안전하다고 오해한다. */}
                {fraction !== null ? formatFraction(fraction) : "—"}
              </span>
            </div>
            <div className="dose-cell__track" aria-hidden="true">
              {fraction !== null && (
                <span
                  className="dose-cell__fill"
                  style={{ width: `${Math.min(100, fraction * 100)}%` }}
                />
              )}
            </div>
            <div className="dose-cell__note">
              {fraction === null
                ? "산출 불가"
                : eta
                  ? formatDoseEta(eta.minutes)
                  : isWorst
                    ? "여유"
                    : ""}
            </div>
          </div>
        );
      })}

      <div className={"dose-cell dose-cell--o2 is-" + doseLevel(o2)}>
        <div className="dose-cell__head">
          <span className="dose-cell__label">O₂</span>
          <span className="dose-cell__pct">
            {o2?.status === "active" && typeof o2.o2_min_pct === "number"
              ? `최저 ${o2.o2_min_pct.toFixed(1)}%`
              : "—"}
          </span>
        </div>
        {/* 농도가 아니라 노출 시간이다. 바로 그리면 소진율로 읽힌다. */}
        <dl className="dose-cell__times">
          <div>
            <dt>결핍</dt>
            <dd>{o2?.status === "active" ? formatDuration(o2.o2_deficient_s ?? 0) : "—"}</dd>
          </div>
          <div>
            <dt>심각</dt>
            <dd>{o2?.status === "active" ? formatDuration(o2.o2_severe_s ?? 0) : "—"}</dd>
          </div>
          <div>
            <dt>과다</dt>
            <dd>{o2?.status === "active" ? formatDuration(o2.o2_enriched_s ?? 0) : "—"}</dd>
          </div>
        </dl>
      </div>
    </div>
  );
}
