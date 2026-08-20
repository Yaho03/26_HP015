import { useMemo } from "react";
import type { AlertLevel, MetricKey, Position3D } from "../types";
import { classifyValue, idw, LEVEL_RGB, type SensorSample } from "../utils/idw";
import {
  SHIP_FLOOR_HALF_WIDTH_M,
  SHIP_SPACE,
  shipFloorHalfWidthAt,
  type MappingPreset,
} from "../utils/coordinates";

// 화물창 바닥 평면도. 관제 화면은 원거리에서 훑어야 하므로(PRODUCT.md 원칙 3)
// 원근이 있는 3D 대신 위에서 내려다본 도면으로 위치와 가스 분포를 함께 보인다.
// 3D 트윈은 상세 화면(Screen 2) 소관이다.

const PLAN_W = SHIP_SPACE.length_m;              // 60m
const PLAN_H = SHIP_FLOOR_HALF_WIDTH_M * 2;      // 13m
const CELL_M = 1.5;
const OUTLINE_STEPS = 48;

/** ship-visual y → SVG y. +y(starboard)가 화면 위로 가도록 뒤집는다. */
function sy(y_m: number): number {
  return SHIP_FLOOR_HALF_WIDTH_M - y_m;
}

function rgb([r, g, b]: [number, number, number]): string {
  return `rgb(${Math.round(r * 255)} ${Math.round(g * 255)} ${Math.round(b * 255)})`;
}

/** 테이퍼를 따라간 바닥 외곽선. */
function floorOutline(): string {
  const top: string[] = [];
  const bottom: string[] = [];
  for (let i = 0; i <= OUTLINE_STEPS; i++) {
    const x = (PLAN_W * i) / OUTLINE_STEPS;
    const half = shipFloorHalfWidthAt(x);
    top.push(`${x.toFixed(2)},${sy(half).toFixed(2)}`);
    bottom.push(`${x.toFixed(2)},${sy(-half).toFixed(2)}`);
  }
  return `M${top.join(" L")} L${bottom.reverse().join(" L")} Z`;
}

interface SpacePlanProps {
  sensors: { id: string; x: number; y: number; level: AlertLevel }[];
  samples: SensorSample[];
  metric: MetricKey;
  worker: Position3D | null;
  /** 작업자 좌표를 어느 사각형에 매핑했는지 — 계측 구역을 도면에 표시한다. */
  preset: MappingPreset;
}

export function SpacePlan({ sensors, samples, metric, worker, preset }: SpacePlanProps) {
  // 값이 바뀔 때만 다시 계산한다. 3D 히트맵처럼 매 프레임 돌지 않는다.
  const cells = useMemo(() => {
    if (samples.length === 0) return [];
    const out: { x: number; y: number; level: AlertLevel }[] = [];
    for (let x = 0; x < PLAN_W; x += CELL_M) {
      const cx = x + CELL_M / 2;
      const half = shipFloorHalfWidthAt(cx);
      for (let y = -SHIP_FLOOR_HALF_WIDTH_M; y < SHIP_FLOOR_HALF_WIDTH_M; y += CELL_M) {
        const cy = y + CELL_M / 2;
        if (Math.abs(cy) > half) continue;   // 테이퍼 밖은 그리지 않는다
        out.push({ x, y, level: classifyValue(metric, idw(samples, cx, cy)) });
      }
    }
    return out;
  }, [samples, metric]);

  const outline = useMemo(() => floorOutline(), []);
  const zone = preset.target;

  return (
    <figure className="space-plan">
      <svg
        className="space-plan__svg"
        viewBox={`-1 -1 ${PLAN_W + 2} ${PLAN_H + 2}`}
        preserveAspectRatio="xMidYMid meet"
        role="img"
        aria-label="화물창 바닥 평면도 — 센서 위치, 작업자 위치, CO₂ 농도 보간 분포"
      >
        <path className="space-plan__hull" d={outline} />

        <g className="space-plan__heat">
          {cells.map((c) => (
            <rect
              key={`${c.x}-${c.y}`}
              x={c.x}
              y={sy(c.y + CELL_M)}
              width={CELL_M}
              height={CELL_M}
              fill={rgb(LEVEL_RGB[c.level])}
            />
          ))}
        </g>

        {/* 계측 구역 — 축소 실험 장비가 화물창 어디에 대응하는지.
            바닥 전체를 덮는 프리셋에서는 외곽선과 겹쳐 정보가 없으므로 그리지 않는다. */}
        {zone.width_m < PLAN_W && (
          <rect
            className="space-plan__zone"
            x={zone.min_x_m}
            y={sy(zone.min_y_m + zone.depth_m)}
            width={zone.width_m}
            height={zone.depth_m}
          />
        )}

        {sensors.map((s) => (
          <g key={s.id} className={"space-plan__sensor is-" + s.level}>
            <circle cx={s.x} cy={sy(s.y)} r={1.15} />
            <text
              x={s.x}
              y={sy(s.y) < PLAN_H / 2 ? sy(s.y) + 3 : sy(s.y) - 1.9}
            >
              {s.id.replace("sensor-", "S")}
            </text>
          </g>
        ))}

        {worker && (
          <g className="space-plan__worker">
            <circle cx={worker.x_m} cy={sy(worker.y_m)} r={1.5} />
            <circle className="space-plan__worker-dot" cx={worker.x_m} cy={sy(worker.y_m)} r={0.7} />
          </g>
        )}
      </svg>
      {/* PRD FR-402 MUST — IDW 추정면임을 화면에 명시한다. */}
      <figcaption className="space-plan__caption">
        Estimated concentration surface based on IDW interpolation
      </figcaption>
    </figure>
  );
}
