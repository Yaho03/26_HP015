import { useEffect, useMemo, useRef } from "react";
import type { BufferAttribute, BufferGeometry } from "three";
import type { MetricKey } from "../types";
import { classifyValue, idw, LEVEL_RGB, type SensorSample } from "../utils/idw";
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
        const [tx, ty, tz] = toThreeGroundPosition(minX + stepX * c, minY + stepY * r, 0.05);
        arr[i * 3] = tx;
        arr[i * 3 + 1] = ty;
        arr[i * 3 + 2] = tz;
        i++;
      }
    }
    return arr;
  }, [total, minX, minY, stepX, stepY, rows, cols]);

  const colorAttrRef = useRef<BufferAttribute>(null);
  const geomRef = useRef<BufferGeometry>(null);

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
        const value = idw(sensors, minX + stepX * c, minY + stepY * r);
        const rgb = LEVEL_RGB[classifyValue(metric, value)];
        arr[i * 3] = rgb[0];
        arr[i * 3 + 1] = rgb[1];
        arr[i * 3 + 2] = rgb[2];
        i++;
      }
    }
    return arr;
  }, [total, sensors, metric, rows, cols, minX, minY, stepX, stepY]);

  // 버퍼가 새로 만들어졌음을 GPU 에 알린다.
  useEffect(() => {
    if (colorAttrRef.current) colorAttrRef.current.needsUpdate = true;
  }, [colors]);

  return (
    <points>
      <bufferGeometry ref={geomRef}>
        <bufferAttribute attach="attributes-position" args={[positions, 3]} />
        <bufferAttribute ref={colorAttrRef} attach="attributes-color" args={[colors, 3]} />
      </bufferGeometry>
      <pointsMaterial size={0.4} vertexColors sizeAttenuation transparent opacity={0.85} />
    </points>
  );
}
