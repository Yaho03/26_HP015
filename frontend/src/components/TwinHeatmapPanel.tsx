import type { AlertLevel, MetricKey } from "../types";
import type { RouteOverlay } from "../types/evacuation";
import type { SensorSample } from "../utils/idw";
import { thresholdLinesFor } from "../utils/alerts";
import { metaFor } from "../utils/metrics";
import { TwinScene } from "./TwinScene";

interface TwinHeatmapPanelProps {
  nodes: { id: string; x: number; y: number; level: AlertLevel }[];
  wearable: { x: number; y: number; z: number; fall_detected?: boolean } | null;
  wearables?: { id: string; x: number; y: number; z: number; fall_detected?: boolean }[];
  samples: SensorSample[];
  metric: MetricKey;
  availableMetrics?: MetricKey[];
  onMetricChange?: (metric: MetricKey) => void;
  /** 주의 이상 가스가 있을 때만 분포를 그린다. */
  distributionEnabled?: boolean;
  /** 메인 트윈에서는 자동 선택된 원인 가스만 보여준다. */
  showMetricControls?: boolean;
  /** 온라인 노드 수. 보간 근거 표시와 부족 경고에 함께 쓴다. */
  onlineCount: number;
  staleCount?: number;
  sourceLabel: "LIVE" | "SIM" | "대기";
  /** 작업자 좌표가 실측(demo-local)에서 매핑됐는지. */
  mapped: boolean;
  /**
   * 경고(L2) 이상에서만 넘어온다. 평상시 경로를 상시 그리면 선이 배경이 되어,
   * 정작 대피해야 할 때 그 선이 눈에 띄지 않는다.
   */
  escapeRoute?: RouteOverlay | null;
  escapeRoutes?: { id: string; route: RouteOverlay }[];
  /** ③ 카드에서 고른 노드. 카메라가 그쪽을 향한다. */
  focusNodeId?: string | null;
  focusWearableId?: string | null;
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
  wearables = [],
  samples,
  metric,
  availableMetrics = ["co2_ppm"],
  onMetricChange,
  distributionEnabled = true,
  showMetricControls = true,
  onlineCount,
  staleCount = 0,
  sourceLabel,
  mapped,
  escapeRoute = null,
  escapeRoutes = [],
  focusNodeId = null,
  focusWearableId = null,
}: TwinHeatmapPanelProps) {
  const insufficient = distributionEnabled && onlineCount < MIN_NODES_FOR_IDW;
  const thresholds = thresholdLinesFor(metric).slice().reverse();
  const legendMax = thresholds.at(-1)?.value ?? 0;
  const metricMeta = metaFor(metric);
  const metricButtons: { key: MetricKey; label: string }[] = [
    { key: "co2_ppm", label: "CO₂" },
    { key: "co_ppm", label: "CO" },
    { key: "h2s_ppm", label: "H₂S" },
  ];

  return (
    <section className="panel-1" aria-label="디지털 트윈 히트맵">
      <div className="panel-1__stage">
        {distributionEnabled && (
          <div className="panel-1__toolbar" aria-label="분포 지표">
            <span className="panel-1__tool-label">원인 가스</span>
            {!showMetricControls ? (
              <span className="panel-1__metric is-active" aria-label={`현재 원인 가스 ${metricMeta?.label ?? metric}`}>
                {metricMeta?.label ?? metric}
              </span>
            ) : (
              metricButtons.map((item) => {
                const available = availableMetrics.includes(item.key);
                return (
                  <button
                    key={item.key}
                    type="button"
                    className={"panel-1__metric" + (metric === item.key ? " is-active" : "")}
                    disabled={!available}
                    title={available ? `${item.label} 분포 보기` : "센서 교정 후 사용"}
                    aria-pressed={metric === item.key}
                    onClick={() => available && onMetricChange?.(item.key)}
                  >
                    {item.label}
                    {!available && <em>교정 필요</em>}
                  </button>
                );
              })
            )}
          </div>
        )}
        <TwinScene
          mode="plan"
          showModeToggle={false}
          interactive={false}
          nodes={nodes}
          wearable={wearable}
          wearables={wearables}
          heatmap={distributionEnabled && !insufficient ? { samples, metric } : null}
          // 이 칸도 이제 TRUE SCALE(UNIFORM) 이라 경로를 그릴 수 있다. FILL
          // 프리셋일 때는 축마다 배율이 달라(x 24배 / y 6.5배) 경로 형상이
          // 왜곡됐고, 왜곡된 그림에서 "가장 가까운 출구" 를 눈으로 고르면 틀린
          // 답이 나왔다 (ADR-010, 12_EVACUATION §2.4).
          escapeRoute={escapeRoute}
          escapeRoutes={escapeRoutes}
          focusNodeId={focusNodeId}
          focusWearableId={focusWearableId}
        />

        {distributionEnabled && !insufficient && legendMax > 0 && (
          <div className="panel-1__legend" aria-label={`${metricMeta?.label ?? metric} 농도 색상 범례`}>
            <div className="panel-1__legend-head">
              <strong>{metricMeta?.label ?? metric}</strong>
              <span>{metricMeta?.unit ?? ""} · 3D 추정 분포</span>
            </div>
            <span className="panel-1__legend-ramp" aria-hidden="true" />
            <span className="panel-1__legend-confidence">
              IDW 평면값을 높이 방향으로 확장 · 센서에서 멀수록 흐리게 표시
            </span>
            <div className="panel-1__legend-scale">
              <span>0</span>
              {thresholds.map((line) => (
                <span key={line.level}>{line.value.toLocaleString("ko-KR")}</span>
              ))}
            </div>
          </div>
        )}

        {insufficient && (
          // 보간을 못 하는 상태를 조용히 빈 화면으로 두면 "가스가 없다"로 읽힌다.
          <div className="panel-1__insufficient" role="status">
            <strong>현재 분포 산출 불가</strong>
            <span>
              최신 데이터 {onlineCount}개 / 최소 {MIN_NODES_FOR_IDW}개 필요
              {staleCount > 0 ? ` · 오래된 값 ${staleCount}개 제외` : ""}
            </span>
          </div>
        )}

      </div>

      {/* PRD FR-402 MUST — 추정값임을 화면에서 떼어놓지 않는다. */}
      <footer className="panel-1__foot">
        {distributionEnabled && (
          <>
            <span className="panel-1__disclaimer">
              Sensor-based 3D estimated concentration · not height-measured
            </span>
            <span className="panel-1__basis">Interpolation based on {onlineCount} sensors</span>
          </>
        )}
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
