import { useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import type { BufferAttribute, BufferGeometry } from "three";
import type { MetricKey } from "../types";
import {
  classifyValue,
  idw,
  LEVEL_RGB,
  type SensorSample,
} from "../utils/idw";

interface HeatmapProps {
  sensors: SensorSample[];
  metric: MetricKey;
  bounds?: { minX: number; maxX: number; minY: number; maxY: number };
  resolution?: number;
}

const DEFAULT_BOUNDS = { minX: 0, maxX: 2.5, minY: 0, maxY: 2.0 };

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
        arr[i * 3] = minX + stepX * c;
        arr[i * 3 + 1] = 0.012;
        arr[i * 3 + 2] = minY + stepY * r;
        i++;
      }
    }
    return arr;
  }, [total, minX, minY, stepX, stepY, rows, cols]);

  const colors = useMemo(() => new Float32Array(total * 3), [total]);
  const colorAttrRef = useRef<BufferAttribute>(null);
  const geomRef = useRef<BufferGeometry>(null);

  useFrame(() => {
    if (sensors.length === 0) return;
    const colorAttr = colorAttrRef.current;
    if (!colorAttr) return;
    const arr = colorAttr.array as Float32Array;
    let i = 0;
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        const x = minX + stepX * c;
        const y = minY + stepY * r;
        const v = idw(sensors, x, y);
        const level = classifyValue(metric, v);
        const rgb = LEVEL_RGB[level];
        arr[i * 3] = rgb[0];
        arr[i * 3 + 1] = rgb[1];
        arr[i * 3 + 2] = rgb[2];
        i++;
      }
    }
    colorAttr.needsUpdate = true;
  });

  return (
    <points>
      <bufferGeometry ref={geomRef}>
        <bufferAttribute
          attach="attributes-position"
          args={[positions, 3]}
        />
        <bufferAttribute
          ref={colorAttrRef}
          attach="attributes-color"
          args={[colors, 3]}
        />
      </bufferGeometry>
      <pointsMaterial size={0.06} vertexColors sizeAttenuation transparent opacity={0.85} />
    </points>
  );
}
