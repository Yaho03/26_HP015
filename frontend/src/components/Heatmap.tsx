import { useMemo } from "react";
import * as THREE from "three";
import type { AlertLevel, MetricKey } from "../types";
import { classifyValue, gasRamp, idw, type SensorSample } from "../utils/idw";
import { SHIP_FLOOR_HALF_WIDTH_M, SHIP_SPACE, toThreeGroundPosition } from "../utils/coordinates";

interface HeatmapProps {
  sensors: SensorSample[];
  metric: MetricKey;
  bounds?: { minX: number; maxX: number; minY: number; maxY: number };
  resolution?: number;
}

// 격자는 ship-visual 바닥 평면을 덮는다. 경계는 utils/coordinates 가 단일 소스다.
const DEFAULT_BOUNDS = {
  minX: 0,
  maxX: SHIP_SPACE.length_m,
  minY: -SHIP_FLOOR_HALF_WIDTH_M,
  maxY: SHIP_FLOOR_HALF_WIDTH_M,
};

const VOLUME_RESOLUTION = 32;
const VOLUME_LAYERS = 8;
const VOLUME_HEIGHT_M = 6.4;
const SENSOR_CLEAR_RADIUS_M = 2;

export function volumePointStyle(level: AlertLevel): { size: number; opacity: number } {
  if (level === "level3_critical") return { size: 0.42, opacity: 0.54 };
  if (level === "level2_warning") return { size: 0.34, opacity: 0.44 };
  if (level === "level1_caution") return { size: 0.26, opacity: 0.32 };
  return { size: 0.16, opacity: 0.14 };
}

function jitter(seed: number): number {
  const value = Math.sin(seed * 12.9898) * 43758.5453;
  return (value - Math.floor(value)) * 2 - 1;
}

export function verticalConcentrationFactor(heightM: number, sourcePpm: number): number {
  const severity = Math.max(0, Math.min(1, sourcePpm / 5000));
  const spreadHeight = 1.7 + severity * 4.3;
  return Math.exp(-Math.max(0, heightM - 0.5) / spreadHeight);
}

export function buildVolumePositions(
  bounds: { minX: number; maxX: number; minY: number; maxY: number },
  resolution: number,
  layers: number,
  heightM: number,
): Float32Array {
  const cols = resolution + 1;
  const rows = resolution + 1;
  const stepX = (bounds.maxX - bounds.minX) / resolution;
  const stepY = (bounds.maxY - bounds.minY) / resolution;
  const positions = new Float32Array(cols * rows * layers * 3);
  let index = 0;

  for (let layer = 0; layer < layers; layer++) {
    const baseHeight = ((layer + 1) / layers) * heightM;
    for (let row = 0; row < rows; row++) {
      for (let col = 0; col < cols; col++) {
        const seed = layer * rows * cols + row * cols + col + 1;
        const x = Math.max(
          bounds.minX,
          Math.min(bounds.maxX, bounds.minX + col * stepX + jitter(seed) * stepX * 0.34),
        );
        const y = Math.max(
          bounds.minY,
          Math.min(bounds.maxY, bounds.minY + row * stepY + jitter(seed + 17) * stepY * 0.34),
        );
        const height = Math.max(
          0.12,
          Math.min(heightM, baseHeight + jitter(seed + 31) * (heightM / layers) * 0.28),
        );
        const [tx, ty, tz] = toThreeGroundPosition(x, y, height);
        positions[index * 3] = tx;
        positions[index * 3 + 1] = ty;
        positions[index * 3 + 2] = tz;
        index++;
      }
    }
  }
  return positions;
}

export function buildGridIndices(cols: number, rows: number): Uint32Array {
  const indices = new Uint32Array((cols - 1) * (rows - 1) * 6);
  let i = 0;
  for (let r = 0; r < rows - 1; r++) {
    for (let c = 0; c < cols - 1; c++) {
      const topLeft = r * cols + c;
      const topRight = topLeft + 1;
      const bottomLeft = topLeft + cols;
      const bottomRight = bottomLeft + 1;
      indices.set(
        [topLeft, bottomLeft, topRight, topRight, bottomLeft, bottomRight],
        i,
      );
      i += 6;
    }
  }
  return indices;
}

export function Heatmap({
  sensors,
  metric,
  bounds = DEFAULT_BOUNDS,
  resolution = 24,
}: HeatmapProps) {
  const { minX, maxX, minY, maxY } = bounds;
  const stepX = (maxX - minX) / resolution;
  const stepY = (maxY - minY) / resolution;
  const cols = resolution + 1;
  const rows = resolution + 1;
  const total = cols * rows;

  const positions = useMemo(() => {
    const arr = new Float32Array(total * 3);
    let i = 0;
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        // 격자점은 ship-visual (Z-up) 로 계산하고 렌더 직전에 Y-up 으로 변환한다.
        const [tx, ty, tz] = toThreeGroundPosition(minX + stepX * c, minY + stepY * r, 0.16);
        arr[i * 3] = tx;
        arr[i * 3 + 1] = ty;
        arr[i * 3 + 2] = tz;
        i++;
      }
    }
    return arr;
  }, [total, minX, minY, stepX, stepY, rows, cols]);
  const indices = useMemo(() => buildGridIndices(cols, rows), [cols, rows]);
  const volumePositions = useMemo(
    () => buildVolumePositions(bounds, VOLUME_RESOLUTION, VOLUME_LAYERS, VOLUME_HEIGHT_M),
    [bounds],
  );
  const sourceLevel = useMemo(() => {
    if (sensors.length === 0) return "unknown";
    return classifyValue(metric, Math.max(...sensors.map((sensor) => sensor.value)));
  }, [sensors, metric]);
  const pointStyle = volumePointStyle(sourceLevel);

  // 센서 값이 바뀔 때만 격자를 다시 칠한다 (이슈 #126).
  //
  // 예전에는 useFrame 으로 매 프레임 돌았다. 격자 25x25 = 625점을 초당 60번,
  // 즉 초당 37,500회 IDW 를 계산했는데 정작 센서 값은 1초에 한 번 바뀐다.
  const colors = useMemo(() => {
    const arr = new Float32Array(total * 3);
    if (sensors.length === 0) return arr;
    let i = 0;
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        const x = minX + stepX * c;
        const y = minY + stepY * r;
        const value = idw(sensors, x, y);
        // 등급 색 네 가지로만 칠하면 600ppm 과 990ppm 이 같은 초록이 된다 —
        // 분포도가 해야 할 일("어디가 더 짙은가")을 임계값 넘기 전까지 숨기는
        // 셈이다. 색 고정점은 서버 임계값이라 등급 경계는 그대로 읽힌다.
        const rgb = gasRamp(metric, value);
        // 가장 가까운 센서에서 멀수록 보간 신뢰도가 낮다. 값 자체를 바꾸지는
        // 않고 밝기만 낮춰 "측정 근거가 먼 영역"임을 표현한다.
        const nearest = Math.min(...sensors.map((s) => Math.hypot(s.x - x, s.y - y)));
        if (nearest < SENSOR_CLEAR_RADIUS_M) {
          i++;
          continue;
        }
        const confidence = 0.28 + 0.72 * Math.exp(-nearest / 10);
        arr[i * 3] = rgb[0] * confidence;
        arr[i * 3 + 1] = rgb[1] * confidence;
        arr[i * 3 + 2] = rgb[2] * confidence;
        i++;
      }
    }
    return arr;
  }, [total, sensors, metric, rows, cols, minX, minY, stepX, stepY]);

  const volumeColors = useMemo(() => {
    const arr = new Float32Array(volumePositions.length);
    if (sensors.length === 0) return arr;
    const sourcePpm = Math.max(...sensors.map((sensor) => sensor.value));

    for (let i = 0; i < volumePositions.length / 3; i++) {
      const x = volumePositions[i * 3];
      const height = volumePositions[i * 3 + 1];
      const y = -volumePositions[i * 3 + 2];
      const baseValue = idw(sensors, x, y);
      const verticalFactor = verticalConcentrationFactor(height, sourcePpm);
      const estimatedValue = baseValue * verticalFactor;
      const rgb = gasRamp(metric, estimatedValue);
      const nearest = Math.min(...sensors.map((sensor) => Math.hypot(sensor.x - x, sensor.y - y)));
      if (nearest < SENSOR_CLEAR_RADIUS_M) continue;
      const confidence = 0.22 + 0.78 * Math.exp(-nearest / 10);
      const visibility = (0.16 + verticalFactor * 0.84) * confidence;
      arr[i * 3] = rgb[0] * visibility;
      arr[i * 3 + 1] = rgb[1] * visibility;
      arr[i * 3 + 2] = rgb[2] * visibility;
    }
    return arr;
  }, [volumePositions, sensors, metric]);

  return (
    <group>
      <mesh renderOrder={4}>
        <bufferGeometry>
          <bufferAttribute attach="attributes-position" args={[positions, 3]} />
          <bufferAttribute attach="attributes-color" args={[colors, 3]} />
          <bufferAttribute attach="index" args={[indices, 1]} />
        </bufferGeometry>
        <meshBasicMaterial
          vertexColors
          transparent
          opacity={0.2}
          depthWrite={false}
          side={THREE.DoubleSide}
        />
      </mesh>
      <points renderOrder={5}>
        <bufferGeometry>
          <bufferAttribute attach="attributes-position" args={[volumePositions, 3]} />
          <bufferAttribute attach="attributes-color" args={[volumeColors, 3]} />
        </bufferGeometry>
        <pointsMaterial
          size={pointStyle.size}
          vertexColors
          sizeAttenuation
          transparent
          opacity={pointStyle.opacity}
          depthWrite={false}
          blending={THREE.AdditiveBlending}
        />
      </points>
      <points renderOrder={6}>
        <bufferGeometry>
          <bufferAttribute attach="attributes-position" args={[positions, 3]} />
          <bufferAttribute attach="attributes-color" args={[colors, 3]} />
        </bufferGeometry>
        <pointsMaterial
          size={pointStyle.size * 0.9}
          vertexColors
          sizeAttenuation
          transparent
          opacity={pointStyle.opacity}
          depthWrite={false}
        />
      </points>
    </group>
  );
}
