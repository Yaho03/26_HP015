import type { WearableState } from "../types";
import type { AssignedWorker } from "../services/api";
import { classifyO2High, classifyO2Low, levelLabel, maxLevel } from "../utils/alerts";

interface WearableCardProps {
  node_id: string;
  wearable: WearableState | null;
  /** 이 웨어러블을 착용 중인 작업자 (이슈 #136). 미배정이면 null. */
  worker?: AssignedWorker | null;
}

/** 착용자 표시. 밀폐공간에서 "누가 안에 있는지" 모르는 것은 그 자체가 위험 정보다. */
function WearerLine({ node_id, worker }: { node_id: string; worker?: AssignedWorker | null }) {
  if (!worker) {
    return (
      <div className="wearable__wearer wearable__wearer--none">
        <span className="wearable__wearer-name">미배정</span>
        <span className="wearable__wearer-meta">{node_id} · 착용자를 등록하세요</span>
      </div>
    );
  }
  return (
    <div className="wearable__wearer">
      <span className="wearable__wearer-name">{worker.name}</span>
      <span className="wearable__wearer-meta">
        {worker.employee_no}
        {worker.emergency_contact ? ` · ${worker.emergency_contact}` : ""}
      </span>
    </div>
  );
}

function batteryClass(pct: number | null): string {
  if (pct === null) return "";
  if (pct < 20) return "bat-low";
  if (pct < 50) return "bat-mid";
  return "bat-ok";
}

/** Location quality band (10_UI_FLOW §3.3). Pending until UWB lands (#121). */
function quality(q: WearableState["location_quality"]): { text: string; cls: string } {
  if (!q) return { text: "대기", cls: "pending" };
  if (q.quality_score >= 0.8) return { text: "GOOD", cls: "q-good" };
  if (q.quality_score >= 0.5) return { text: "FAIR", cls: "q-fair" };
  return { text: "POOR", cls: "q-poor" };
}

export function WearableCard({ node_id, wearable, worker }: WearableCardProps) {
  if (!wearable) {
    return (
      <div className="wearable-card is-unknown" aria-label={node_id}>
        <WearerLine node_id={node_id} worker={worker} />
        <div className="wearable__o2">
          <span className="wearable__o2-value">—</span>
          <span className="wearable__o2-label">O₂ %</span>
        </div>
        <p className="pending">웨어러블 연결 대기 중</p>
        <span className="wearable__id">{node_id}</span>
      </div>
    );
  }

  const o2 = wearable.o2_pct;
  // O₂ 값이 없으면 판정 불가다 (이슈 #165). 측정 못 한 것을 정상이라 하면 안 된다.
  const o2Level =
    o2 !== null ? maxLevel(classifyO2Low(o2), classifyO2High(o2)) : "unknown";
  const fall = wearable.fall_detected;
  const q = quality(wearable.location_quality);
  // 운영자에게는 실측 좌표를 보여준다. 화면 매핑값은 3D 트윈 렌더에만 쓴다.
  const pos = wearable.position_raw;

  return (
    <div
      className={"wearable-card is-" + o2Level + (fall ? " wearable-card--fall" : "")}
      aria-label={`${worker ? worker.name : node_id} ${fall ? "낙상 감지" : levelLabel(o2Level)}`}
    >
      <WearerLine node_id={node_id} worker={worker} />
      <div className="wearable__o2">
        <span className="wearable__o2-value">{o2 !== null ? o2.toFixed(1) : "—"}</span>
        <span className="wearable__o2-label">O₂ % · 응답 지연 ≤15초</span>
      </div>

      <div className="wearable__facts">
        <div className="fact">
          <span className="fact__label">위치</span>
          <span className="fact__value">
            {pos ? `(${pos.x_m.toFixed(2)}, ${pos.y_m.toFixed(2)})` : <span className="pending">대기</span>}
          </span>
        </div>
        <div className="fact">
          <span className="fact__label">위치품질</span>
          <span className={"fact__value " + q.cls}>{q.text}</span>
        </div>
        <div className="fact">
          <span className="fact__label">배터리</span>
          <span className={"fact__value " + batteryClass(wearable.battery_pct)}>
            {wearable.battery_pct !== null ? `${wearable.battery_pct}%` : "—"}
          </span>
        </div>
        <div className="fact">
          <span className="fact__label">낙상</span>
          <span className="fact__value">
            {fall ? <span className="fall-flag">FALL DETECTED</span> : "정상"}
          </span>
        </div>
      </div>

      <span className="wearable__id">{node_id}</span>
    </div>
  );
}
