import type { ComponentType } from "react";
import type { AlertLevel, WearableState } from "../types";
import type { AssignedWorker } from "../services/api";
import { classifyO2High, classifyO2Low, levelLabel, maxLevel } from "../utils/alerts";
import { useExposure } from "../hooks/useExposure";
import { formatFraction, worstDoseFraction, worstExposureLevel } from "../utils/exposure";
import { LEVEL_ICON } from "./icons";

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
  const Icon = LEVEL_ICON[stripLevel] as ComponentType<{
    size?: number | string;
  }>;

  // 누적 노출량 요약 (11_EXPOSURE_DOSE_SPEC §6.4 — 요약은 웨어러블 영역, 상세는 별도 화면).
  // 줄 전체의 등급(stripLevel)은 건드리지 않는다. 노출량 경보는 자동 해제되지
  // 않으므로(§5.2) 스트립을 승격시키면 윈도우가 끝날 때까지 줄이 계속 붉게 남아
  // 낙상·O₂ 같은 즉시 대응이 필요한 상태를 덮어 버린다.
  const { exposure } = useExposure(node_id);
  const doseFraction = worstDoseFraction(exposure);
  const doseLevel = doseFraction !== null ? worstExposureLevel(exposure) : "unknown";

  return (
    <div
      className={"wstrip is-" + stripLevel + (fall ? " wstrip--fall" : "")}
      aria-label={`${worker ? worker.name : node_id} ${fall ? "낙상 감지" : levelLabel(o2Level)}`}
    >
      <span className="wstrip__who">
        <Icon size={13} />
        {worker ? (
          <>
            <strong>{worker.name}</strong>
            <em>사번 {worker.employee_no}</em>
          </>
        ) : (
          // 밀폐공간에서 "누가 안에 있는지" 모르는 것은 그 자체가 위험 정보다.
          <>
            <strong className="wstrip__who--none">미배정</strong>
            <em>{node_id}</em>
          </>
        )}
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
      {/* 산출 불가를 "0%" 로 그리지 않는다. 측정 못 한 것을 노출 없음으로 보여주면
          안전하다고 오해한다 (11_EXPOSURE_DOSE_SPEC §6.4 MUST). */}
      <span className={"wstrip__fact is-" + doseLevel}>
        <span className="wstrip__label">누적노출</span>
        <strong
          className="wstrip__dose"
          title={
            doseFraction === null
              ? "노출량을 산출할 수 없습니다. 노출이 없다는 뜻이 아닙니다."
              : doseLevel === "unknown"
                ? "산출되지 않은 지표가 있어 이 값은 하한입니다. 상세는 노출량 화면에서 확인합니다."
                : "노출 기준 대비 소진율. 상세는 노출량 화면에서 확인합니다."
          }
        >
          {doseFraction !== null ? formatFraction(doseFraction) : "확인 필요"}
        </strong>
      </span>

      {fall && (
        <span className="wstrip__overlay" role="alert">
          FALL DETECTED
        </span>
      )}
    </div>
  );
}
