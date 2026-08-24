import type { AlertLevel, MetricKey } from "../types";
import type { RouteOverlay } from "../types/evacuation";
import type { SensorSample } from "../utils/idw";
import { TwinScene } from "./TwinScene";

interface TwinHeatmapPanelProps {
  nodes: { id: string; x: number; y: number; level: AlertLevel }[];
  wearable: { x: number; y: number; z: number; fall_detected?: boolean } | null;
  samples: SensorSample[];
  metric: MetricKey;
  /** 온라인 노드 수. 보간 근거 표시와 부족 경고에 함께 쓴다. */
  onlineCount: number;
  sourceLabel: "LIVE" | "SIM" | "대기";
  /** 작업자 좌표가 실측(demo-local)에서 매핑됐는지. */
  mapped: boolean;
  /**
   * 경고(L2) 이상에서만 넘어온다. 평상시 경로를 상시 그리면 선이 배경이 되어,
   * 정작 대피해야 할 때 그 선이 눈에 띄지 않는다.
   */
  escapeRoute?: RouteOverlay | null;
  /** ③ 카드에서 고른 노드. 카메라가 그쪽을 향한다. */
  focusNodeId?: string | null;
}

/**
 * IDW 보간은 최소 3점이 있어야 면을 만든다. 2점 이하는 선형 보간이라
 * 화물창 전체 분포를 대표하지 못한다 (10_UI_FLOW §4.6).
 */
const MIN_NODES_FOR_IDW = 3;

/**
 * ① 디지털 트윈 히트맵.
 *
 * 별도의 2D 평면도를 그리지 않고 3D 트윈을 사선 탑뷰로 크롭해 쓴다. 평면도와
 * 트윈이 따로 있으면 두 그림의 노드 위치가 서로 어긋나는 순간 어느 쪽이 맞는지
 * 알 수 없게 된다.
 */
export function TwinHeatmapPanel({
  nodes,
  wearable,
  samples,
  metric,
  onlineCount,
  sourceLabel,
  mapped,
  escapeRoute = null,
  focusNodeId = null,
}: TwinHeatmapPanelProps) {
  const insufficient = onlineCount < MIN_NODES_FOR_IDW;

  return (
    <section className="panel-1" aria-label="디지털 트윈 히트맵">
      <div className="panel-1__stage">
        <TwinScene
          mode="plan"
          showModeToggle={false}
          interactive={false}
          nodes={nodes}
          wearable={wearable}
          heatmap={insufficient ? null : { samples, metric }}
          // 이 칸도 이제 TRUE SCALE(UNIFORM) 이라 경로를 그릴 수 있다. FILL
          // 프리셋일 때는 축마다 배율이 달라(x 24배 / y 6.5배) 경로 형상이
          // 왜곡됐고, 왜곡된 그림에서 "가장 가까운 출구" 를 눈으로 고르면 틀린
          // 답이 나왔다 (ADR-010, 12_EVACUATION §2.4).
          escapeRoute={escapeRoute}
          focusNodeId={focusNodeId}
        />

        {insufficient && (
          // 보간을 못 하는 상태를 조용히 빈 화면으로 두면 "가스가 없다"로 읽힌다.
          <div className="panel-1__insufficient" role="status">
            <strong>Insufficient data for interpolation</strong>
            <span>
              온라인 노드 {onlineCount} / 최소 {MIN_NODES_FOR_IDW} 필요
            </span>
          </div>
        )}
      </div>

      {/* PRD FR-402 MUST — 추정값임을 화면에서 떼어놓지 않는다. */}
      <footer className="panel-1__foot">
        <span className="panel-1__disclaimer">
          Estimated concentration based on IDW interpolation
        </span>
        <span className="panel-1__basis">Interpolation based on {onlineCount} sensors</span>
        <span className={"panel-1__badge" + (sourceLabel === "SIM" ? " panel-1__badge--sim" : "")}>
          {sourceLabel}
        </span>
        <span className="panel-1__coords">
          {mapped ? "demo-local → ship-visual" : "ship-visual"}
        </span>
      </footer>
    </section>
  );
}
