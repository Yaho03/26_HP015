import { Canvas, useFrame } from "@react-three/fiber";
import { Html, OrbitControls } from "@react-three/drei";
import { Suspense, useRef, useState } from "react";
import type { AlertLevel, MetricKey } from "../types";
import type { Group } from "three";
import { Heatmap } from "./Heatmap";
import type { SensorSample } from "../utils/idw";

interface TwinSceneProps {
  nodes?: { id: string; x: number; y: number; level: AlertLevel }[];
  wearable?: { x: number; y: number; z: number; fall_detected?: boolean } | null;
  heatmap?: { samples: SensorSample[]; metric: MetricKey } | null;
}

const LEVEL_COLOR: Record<AlertLevel, string> = {
  normal: "#10b981",
  level1_caution: "#facc15",
  level2_warning: "#fb923c",
  level3_critical: "#ef4444",
};

const LEVEL_LABEL: Record<AlertLevel, string> = {
  normal: "정상",
  level1_caution: "L1",
  level2_warning: "L2",
  level3_critical: "L3",
};

function WorkspaceFloor() {
  return (
    <mesh rotation={[-Math.PI / 2, 0, 0]} position={[1.25, 0, 1.0]} receiveShadow>
      <planeGeometry args={[2.5, 2.0]} />
      <meshStandardMaterial color="#1c2230" />
    </mesh>
  );
}

function WorkspaceWalls() {
  const wallMat = <meshStandardMaterial color="#2a3142" />;
  return (
    <group>
      <mesh position={[1.25, 0.5, 0]} castShadow>{wallMat}<boxGeometry args={[2.5, 1.0, 0.05]} /></mesh>
      <mesh position={[1.25, 0.5, 2.0]} castShadow>{wallMat}<boxGeometry args={[2.5, 1.0, 0.05]} /></mesh>
      <mesh position={[0, 0.5, 1.0]} castShadow>{wallMat}<boxGeometry args={[0.05, 1.0, 2.0]} /></mesh>
      <mesh position={[2.5, 0.5, 1.0]} castShadow>{wallMat}<boxGeometry args={[0.05, 1.0, 2.0]} /></mesh>
    </group>
  );
}

const HAZARD_RADIUS_M = 0.5;

function HazardZone({ level }: { level: AlertLevel }) {
  const color = LEVEL_COLOR[level];
  return (
    <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.005, 0]} receiveShadow>
      <ringGeometry args={[HAZARD_RADIUS_M - 0.02, HAZARD_RADIUS_M, 32]} />
      <meshStandardMaterial
        color={color}
        transparent
        opacity={0.55}
        emissive={color}
        emissiveIntensity={0.4}
        side={2}
      />
    </mesh>
  );
}

function SensorMarker({ id, x, y, level }: { id: string; x: number; y: number; level: AlertLevel }) {
  const color = LEVEL_COLOR[level];
  const isDanger = level !== "normal";
  const showHazard = level === "level2_warning" || level === "level3_critical";
  const groupRef = useRef<Group>(null);
  const [hovered, setHovered] = useState(false);

  useFrame((state) => {
    if (!groupRef.current || !isDanger) return;
    const t = state.clock.getElapsedTime();
    const pulse = 1 + Math.sin(t * 4) * 0.12;
    groupRef.current.scale.setScalar(pulse);
  });

  return (
    <group position={[x, 0.15, y]}>
      {showHazard && <HazardZone level={level} />}
      <group
        ref={groupRef}
        onPointerOver={(e) => {
          e.stopPropagation();
          setHovered(true);
        }}
        onPointerOut={() => setHovered(false)}
      >
        <mesh castShadow>
          <cylinderGeometry args={[0.08, 0.08, 0.3, 16]} />
          <meshStandardMaterial
            color={color}
            emissive={color}
            emissiveIntensity={isDanger ? 0.6 : 0.2}
          />
        </mesh>
        <mesh position={[0, 0.25, 0]}>
          <sphereGeometry args={[hovered ? 0.09 : 0.06, 16, 16]} />
          <meshStandardMaterial color={color} emissive={color} emissiveIntensity={0.7} />
        </mesh>
      </group>
      <Html position={[0, 0.55, 0]} center distanceFactor={6}>
        <div className={"twin-node-label twin-node-" + level}>
          <span className="twin-node-id">{id}</span>
          {isDanger && <span className="twin-node-level">{LEVEL_LABEL[level]}</span>}
        </div>
      </Html>
    </group>
  );
}

function WearableMarker({ x, y, z, fall_detected }: { x: number; y: number; z: number; fall_detected: boolean }) {
  const color = fall_detected ? "#ef4444" : "#06b6d4";
  const sphereRef = useRef<Group>(null);

  useFrame((state) => {
    if (!sphereRef.current) return;
    const t = state.clock.getElapsedTime();
    const bob = Math.sin(t * 2) * 0.04;
    sphereRef.current.position.y = 0.4 + bob;
  });

  return (
    <group position={[x, z, y]} ref={sphereRef}>
      <mesh castShadow>
        <sphereGeometry args={[0.07, 16, 16]} />
        <meshStandardMaterial color={color} emissive={color} emissiveIntensity={0.7} />
      </mesh>
      <pointLight position={[0, 0.2, 0]} color={color} intensity={fall_detected ? 1.5 : 0.6} distance={1.0} />
      <Html position={[0, 0.2, 0]} center distanceFactor={6}>
        <div className={"twin-node-label " + (fall_detected ? "twin-node-level3_critical" : "twin-wearable")}>
          <span className="twin-node-id">wearable</span>
          {fall_detected && <span className="twin-node-level">낙하</span>}
        </div>
      </Html>
    </group>
  );
}

function SceneContent({
  nodes,
  wearable,
  heatmap,
}: {
  nodes: NonNullable<TwinSceneProps["nodes"]>;
  wearable: TwinSceneProps["wearable"];
  heatmap: TwinSceneProps["heatmap"];
}) {
  return (
    <>
      <ambientLight intensity={0.4} />
      <directionalLight position={[3, 5, 3]} intensity={0.8} castShadow />
      <directionalLight position={[-3, 4, -2]} intensity={0.3} />
      <WorkspaceFloor />
      <WorkspaceWalls />
      {heatmap && heatmap.samples.length > 0 && (
        <Heatmap sensors={heatmap.samples} metric={heatmap.metric} />
      )}
      {nodes.map((n) => (
        <SensorMarker key={n.id} id={n.id} x={n.x} y={n.y} level={n.level} />
      ))}
      {wearable && (
        <WearableMarker x={wearable.x} y={wearable.y} z={wearable.z} fall_detected={!!wearable.fall_detected} />
      )}
      <OrbitControls
        target={[1.25, 0, 1.0]}
        minDistance={2}
        maxDistance={8}
        maxPolarAngle={Math.PI / 2.1}
      />
    </>
  );
}

export function TwinScene({ nodes = [], wearable = null, heatmap = null }: TwinSceneProps) {
  return (
    <div className="twin-canvas">
      <Canvas
        camera={{ position: [3, 3, 4], fov: 50 }}
        shadows
        gl={{ antialias: true }}
      >
        <color attach="background" args={["#0b0e14"]} />
        <Suspense fallback={null}>
          <SceneContent nodes={nodes} wearable={wearable} heatmap={heatmap} />
        </Suspense>
      </Canvas>
    </div>
  );
}
