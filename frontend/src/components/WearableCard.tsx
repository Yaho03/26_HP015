import type { WearableState } from "../types";
import { classifyO2High, classifyO2Low, levelLabel, maxLevel } from "../utils/alerts";

interface WearableCardProps {
  node_id: string;
  wearable: WearableState | null;
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

export function WearableCard({ node_id, wearable }: WearableCardProps) {
  if (!wearable) {
    return (
      <div className="wearable-card is-normal" aria-label={node_id}>
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
  const o2Level =
    o2 !== null ? maxLevel(classifyO2Low(o2), classifyO2High(o2)) : "normal";
  const fall = wearable.fall_detected;
  const q = quality(wearable.location_quality);
  // 운영자에게는 실측 좌표를 보여준다. 화면 매핑값은 3D 트윈 렌더에만 쓴다.
  const pos = wearable.position_raw;

  return (
    <div
      className={"wearable-card is-" + o2Level + (fall ? " wearable-card--fall" : "")}
      aria-label={`${node_id} ${fall ? "낙상 감지" : levelLabel(o2Level)}`}
    >
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
