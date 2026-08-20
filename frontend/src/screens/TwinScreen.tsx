import { useMemo, useState } from "react";
import { EvacuationPanel } from "../components/EvacuationPanel";
import { TwinScene } from "../components/TwinScene";
import { useDashboardStore } from "../store/dashboardStore";
import { MOCK_ROUTE_LABELS, MOCK_ROUTES, MOCK_TOPOLOGY, type MockRouteKey } from "../mocks/evacuation";
import type { MetricKey } from "../types";
import type { RouteOverlay } from "../types/evacuation";
import { nodeAlertLevel } from "../utils/alerts";
import type { SensorSample } from "../utils/idw";
import {
  displayPositionFor,
  SENSOR_SHIP_POSITIONS as SENSOR_POSITIONS,
  shouldMapToShip,
  UNIFORM_PRESET,
  type MappingPreset,
} from "../utils/coordinates";

const HEATMAP_METRIC: MetricKey = "co2_ppm";

export function TwinPanel({
  preset = UNIFORM_PRESET,
  compact = false,
  escapeRoute = null,
}: {
  preset?: MappingPreset;
  /** 모니터링 화면에 곁들이는 축소 표시. 제목·도움말을 접고 캔버스를 낮춘다. */
  compact?: boolean;
  /**
   * 탈출 경로 (FR-804). **TRUE SCALE 프리셋에서만 넘긴다** — FILL 은 축마다
   * 배율이 달라 경로 형상이 왜곡된다 (ADR-010, §2.4).
   */
  escapeRoute?: RouteOverlay | null;
}) {
  const nodes = useDashboardStore((s) => s.sensor_nodes);
  const wearable = useDashboardStore((s) => s.wearable);
  const connectionStatus = useDashboardStore((s) => s.connection_status);
  const sceneNodes = Object.values(nodes)
    .filter((n) => n.node_id in SENSOR_POSITIONS)
    .map((n) => ({
      id: n.node_id,
      x: SENSOR_POSITIONS[n.node_id].x,
      y: SENSOR_POSITIONS[n.node_id].y,
      // 판정은 alerts.ts 한 곳에서만 한다 (PRD FR-204, 이슈 #114/#165).
      // 예전에는 여기에 임계값이 복사돼 있어 서버에서 값을 바꿔도 트윈 화면만
      // 옛 기준으로 칠해졌고, 임계값 미로딩 구간에도 정상으로 보였다.
      level: nodeAlertLevel(n),
    }));

  // 실측 좌표(position_raw)만 입력으로 쓴다. 이미 ship-visual 인 값에는 매핑을
  // 적용하지 않아 중복 변환이 생기지 않는다.
  const displayPosition = displayPositionFor(
    wearable?.position_raw,
    wearable?.source_coordinate_system,
    preset,
  );

  const wearableMarker = displayPosition
    ? {
        x: displayPosition.x_m,
        y: displayPosition.y_m,
        z: displayPosition.z_m,
        fall_detected: wearable?.fall_detected ?? false,
      }
    : null;

  const sourceModes = new Set(
    Object.values(nodes)
      .map((node) => node.source_mode)
      .filter((mode): mode is "live" | "simulation" => Boolean(mode)),
  );
  if (wearable?.source_mode) sourceModes.add(wearable.source_mode);
  const sourceLabel = sourceModes.size === 1
    ? sourceModes.has("simulation") ? "SIM" : "LIVE"
    : sourceModes.size > 1 ? "MIXED" : connectionStatus.websocket_connected ? "LIVE" : "대기";
  const sourceCoordinate = wearable?.source_coordinate_system ?? "demo-local";
  const isMapped = shouldMapToShip(wearable?.source_coordinate_system);

  const heatmapSamples: SensorSample[] = useMemo(() => {
    return Object.values(nodes)
      .filter((n) => n.node_id in SENSOR_POSITIONS)
      .map((n) => {
        const reading = n.readings[HEATMAP_METRIC];
        const pos = SENSOR_POSITIONS[n.node_id];
        return {
          x: pos.x,
          y: pos.y,
          value: reading ? reading.value : 0,
        };
      })
      .filter((s) => s.value > 0);
  }, [nodes]);

  const heatmapData = heatmapSamples.length > 0
    ? { samples: heatmapSamples, metric: HEATMAP_METRIC }
    : null;

  return (
      <section className={"panel twin-panel" + (compact ? " twin-panel--compact" : "")}>
        {!compact && (
          <div className="twin-heading">
            <div>
              <p className="twin-kicker">OPERATE / SHIP VISUAL MODEL</p>
              <h2 className="panel-title">
                3D Digital Twin <span className="twin-count">{sceneNodes.length} sensors</span>
              </h2>
            </div>
            <div className="twin-state-line" aria-label="트윈 데이터 상태">
              <span className="twin-state-label">DATA</span>
              <span className="twin-state-badge twin-state-badge--data">{sourceLabel}</span>
              {wearableMarker && <span className="twin-state-badge">WEARABLE TRACKING</span>}
              {heatmapData && <span className="twin-state-badge">IDW ACTIVE</span>}
            </div>
          </div>
        )}
        <div className="twin-coordinate-strip" aria-label="트윈 좌표 및 비율 매핑 상태">
          <span className="twin-coordinate-item">
            <span className="twin-coordinate-label">SOURCE</span>
            <strong>{sourceCoordinate}</strong>
          </span>
          <span className="twin-coordinate-arrow" aria-hidden="true">→</span>
          <span className="twin-coordinate-item twin-coordinate-item--target">
            <span className="twin-coordinate-label">DISPLAY</span>
            <strong>ship-visual</strong>
          </span>
          <span className="twin-mapping-badge">
            {isMapped ? preset.label : "1:1 MODEL"}
          </span>
        </div>
        <TwinScene
          nodes={sceneNodes}
          wearable={wearableMarker}
          heatmap={heatmapData}
          escapeRoute={escapeRoute}
        />
        {!compact && (
          <p className="twin-help">
            마우스 드래그로 회전, 휠로 확대/축소. 센서 노드 색상=위험도, 청록 구체=웨어러블,
            바닥 점=CO₂ 농도 IDW 보간. 표시 좌표는 실측값을 비율 매핑한 추정 위치다.
          </p>
        )}
      </section>
  );
}

/**
 * 목 데이터 토글.
 *
 * 개발 빌드에서만 뜬다. 백엔드 없이 UI 를 확인하는 경로가 있어야 시연 리허설과
 * 디버깅이 되고, 시연 직전에 백엔드가 죽어도 화면은 계속 보여줄 수 있다 (B4).
 */
function MockRouteToggle({
  value,
  onChange,
}: {
  value: MockRouteKey | null;
  onChange: (next: MockRouteKey | null) => void;
}) {
  const keys: (MockRouteKey | null)[] = [null, "safe", "degraded", "no_safe_route", "unavailable"];
  return (
    <div className="evac__mock">
      <span className="evac__mock-label">MOCK</span>
      {keys.map((k) => (
        <button
          key={k ?? "live"}
          type="button"
          className="evac__mock-btn"
          aria-pressed={value === k}
          onClick={() => onChange(k)}
        >
          {k === null ? "라이브" : MOCK_ROUTE_LABELS[k]}
        </button>
      ))}
    </div>
  );
}

export function TwinScreen() {
  const routes = useDashboardStore((s) => s.evacuation_route);

  // 개발 빌드는 목을 기본값으로 켠다. 백엔드가 아직 경로를 보내지 않는 단계라
  // 라이브가 기본이면 화면이 늘 비어 UI 를 확인할 수 없다.
  const [mockKey, setMockKey] = useState<MockRouteKey | null>(
    import.meta.env.DEV ? "safe" : null,
  );

  // MVP 는 작업자 1명이다 (§7 한계 #5). 여러 명으로 늘어나면 여기서 선택 UI 가
  // 필요해진다 — 지금 임의로 고르는 것을 감추지 않으려고 주석을 남긴다.
  const liveRoute = Object.values(routes)[0] ?? null;
  const route = mockKey ? MOCK_ROUTES[mockKey] : liveRoute;

  const overlay: RouteOverlay | null = route
    ? {
        route_status: route.route_status,
        waypoints: route.waypoints,
        target_exit_id: route.target_exit_id,
      }
    : null;

  return (
    <div className="screen twin-screen">
      {/* 상세 화면은 형상비를 보존한다. 정사각 보행이 정사각으로 보여야 한다.
          경로도 이 프리셋에서만 그린다 (§2.4). */}
      <TwinPanel preset={UNIFORM_PRESET} escapeRoute={overlay} />
      <EvacuationPanel route={route} topology={MOCK_TOPOLOGY} mock={mockKey !== null}>
        {import.meta.env.DEV && <MockRouteToggle value={mockKey} onChange={setMockKey} />}
      </EvacuationPanel>
    </div>
  );
}
