import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { Html, OrbitControls } from "@react-three/drei";
import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import type { OrbitControls as OrbitControlsImpl } from "three-stdlib";
import type { AlertLevel, MetricKey } from "../types";
import type { Group } from "three";
import { Heatmap } from "./Heatmap";
import type { SensorSample } from "../utils/idw";
import { toThreeGroundPosition, toThreePosition } from "../utils/coordinates";

// ── Types ─────────────────────────────────────────────────────
interface TwinSceneProps {
  nodes?: { id: string; x: number; y: number; level: AlertLevel }[];
  wearable?: { x: number; y: number; z: number; fall_detected?: boolean } | null;
  heatmap?: { samples: SensorSample[]; metric: MetricKey } | null;
}

const LEVEL_COLOR: Record<AlertLevel, string> = {
  normal: "#10b981", level1_caution: "#facc15",
  level2_warning: "#fb923c", level3_critical: "#ef4444",
};
const LEVEL_LABEL: Record<AlertLevel, string> = {
  normal: "정상", level1_caution: "L1",
  level2_warning: "L2", level3_critical: "L3",
};

// ── Dimensions (real ship scale) ──────────────────────────────
const TL   = 60;   // length x: 0→60 m
const THW  = 10;   // half-width at the side shell z: -10→+10 (total 20 m)
const TH   = 14;   // height y: 0→14 m
const BH   = 5.5;  // top of the hopper slope
const TS   = 9.0;  // topside knuckle — wall starts leaning inboard here
const TTW  = 4.8;  // half-width at the tank top
const FHW  = 6.5;  // flat floor half-width
const NSEG = 14;   // hopper curve segments
const PAINT_Y   = 7.4;  // height of the oxide-red / topside-blue coat boundary
const DOT_Y     = 11.6; // marker dots, up on the topside slope
const BRACKET_Y = 7.8;  // wall fittings, on the vertical side shell
const LABEL_Y   = 8.1;  // stencilled markings

type CamMode = "overview" | "inside";
const CAMS: Record<CamMode, { pos: [number,number,number]; tgt: [number,number,number] }> = {
  // Frame the hold interior so floor data, heatmap, and worker markers share
  // the first viewport instead of appearing as a distant ship silhouette.
  overview: { pos: [TL*0.5, 17, -40], tgt: [TL*0.5, TH*0.3, 0] },
  inside:   { pos: [2,    TH*0.6, 0.2     ], tgt: [TL*0.85, TH*0.42, 0] },
};

function cameraPosition(mode: CamMode, aspect: number): [number, number, number] {
  if (mode === "inside") return CAMS.inside.pos;

  // Fit the 60 m ship length to the viewport. Narrow screens need more
  // distance; wide screens can move in close enough to read the overlays.
  const verticalFov = (60 * Math.PI) / 180;
  const horizontalFov = 2 * Math.atan(Math.tan(verticalFov / 2) * Math.max(aspect, 0.5));
  const fitDistance = TL / (2 * Math.tan(horizontalFov / 2));
  const distance = Math.max(36, fitDistance * 1.12);
  const targetY = CAMS.overview.tgt[1];
  return [TL * 0.5, targetY + distance * 0.45, -distance];
}

// ── Painted-steel textures ────────────────────────────────────
// Sampled off the reference photos: sprayed anticorrosive coating over steel.
// No panel grid — real tank walls read as continuous surfaces with fine spray
// grain, broad soft blotching, faint weld seams and vertical run-off streaks.
const BLUE: [number, number, number] = [34, 51, 96];   // topside coating
const RED:  [number, number, number] = [84, 36, 31];   // oxide/holding primer

const TEX = 1024;
function canvas2d(): [HTMLCanvasElement, CanvasRenderingContext2D] {
  const cv = document.createElement("canvas");
  cv.width = cv.height = TEX;
  return [cv, cv.getContext("2d")!];
}

/** Coating map. redFrac = fraction of the height (from v=0) painted oxide red. */
function makeCoatMap(redFrac: number, repX: number, repY: number): THREE.CanvasTexture {
  const [cv, cx] = canvas2d();

  // Flat base coats. v=0 is the bottom of the surface, so red fills the bottom.
  const split = Math.round(TEX * (1 - redFrac));
  cx.fillStyle = `rgb(${BLUE.join(",")})`;
  cx.fillRect(0, 0, TEX, split);
  cx.fillStyle = `rgb(${RED.join(",")})`;
  cx.fillRect(0, split, TEX, TEX - split);

  // Ragged brush edge where the two coats meet
  if (redFrac > 0 && redFrac < 1) {
    cx.fillStyle = `rgb(${RED.join(",")})`;
    for (let x = 0; x < TEX; x += 8) {
      const w = 8 + Math.random() * 6;
      cx.fillRect(x, split - Math.random() * 5, w, 6);
    }
  }

  // Uneven coat thickness — many small mottles, not a few big blobs
  for (let i = 0; i < 260; i++) {
    const x = Math.random() * TEX, y = Math.random() * TEX;
    const r = 18 + Math.random() * 70;
    const g = cx.createRadialGradient(x, y, 0, x, y, r);
    const dark = Math.random() > 0.4;
    g.addColorStop(0, dark ? "rgba(0,0,0,0.10)" : "rgba(255,255,255,0.028)");
    g.addColorStop(1, "rgba(0,0,0,0)");
    cx.fillStyle = g;
    cx.fillRect(x - r, y - r, r * 2, r * 2);
  }

  // Vertical run-off streaks
  for (let i = 0; i < 60; i++) {
    const x = Math.random() * TEX;
    const y0 = Math.random() * TEX * 0.7;
    const g = cx.createLinearGradient(0, y0, 0, y0 + 120 + Math.random() * 380);
    g.addColorStop(0, "rgba(0,0,0,0.10)");
    g.addColorStop(1, "rgba(0,0,0,0)");
    cx.fillStyle = g;
    cx.fillRect(x, y0, 1 + Math.random() * 3, TEX);
  }

  // Faint horizontal weld seams — barely-there, never a drawn grid
  for (let y = 150; y < TEX; y += 150 + Math.random() * 60) {
    cx.fillStyle = "rgba(0,0,0,0.10)";
    cx.fillRect(0, y, TEX, 1.5);
    cx.fillStyle = "rgba(255,255,255,0.03)";
    cx.fillRect(0, y + 1.5, TEX, 1);
  }

  // Fine spray grain over everything — this is what reads as painted steel
  const img = cx.getImageData(0, 0, TEX, TEX);
  const d = img.data;
  for (let i = 0; i < d.length; i += 4) {
    const n = (Math.random() - 0.5) * 34;
    d[i]     = Math.max(0, Math.min(255, d[i]     + n));
    d[i + 1] = Math.max(0, Math.min(255, d[i + 1] + n));
    d[i + 2] = Math.max(0, Math.min(255, d[i + 2] + n));
  }
  cx.putImageData(img, 0, 0);

  const t = new THREE.CanvasTexture(cv);
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.repeat.set(repX, repY);
  t.anisotropy = 8;
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

/** Grain height map, so grazing light actually catches the coating texture. */
function makeGrainBump(repX: number, repY: number): THREE.CanvasTexture {
  const [cv, cx] = canvas2d();
  const img = cx.createImageData(TEX, TEX);
  const d = img.data;
  for (let i = 0; i < d.length; i += 4) {
    const v = 110 + Math.random() * 76;
    d[i] = d[i + 1] = d[i + 2] = v;
    d[i + 3] = 255;
  }
  cx.putImageData(img, 0, 0);
  const t = new THREE.CanvasTexture(cv);
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.repeat.set(repX, repY);
  return t;
}

// ── Materials (memoized outside component to avoid recreation) ─
let _mats: ReturnType<typeof buildMats> | null = null;
function buildMats() {
  const bump = makeGrainBump(24, 12);
  // Matte coating: no specular sheen, no metallic response.
  const coat = { roughness: 0.97, metalness: 0.0, bumpMap: bump, bumpScale: 0.05,
                 side: THREE.DoubleSide } as const;
  return {
    // Side shell: blue topside coat above the oxide-red band. The band edge is
    // placed by arc length along the section, so it follows the hull curve.
    wall: new THREE.MeshStandardMaterial({ ...coat, map: makeCoatMap(vAt(PAINT_Y), 7, 1) }),
    // Bulkheads are mapped by height, not arc length.
    bulkhead: new THREE.MeshStandardMaterial({ ...coat, map: makeCoatMap(PAINT_Y / TH, 2, 1) }),
    // Bilge curve and tank top: all oxide red.
    red: new THREE.MeshStandardMaterial({ ...coat, map: makeCoatMap(1, 8, 2) }),
    // Tank top / deck beams — near black, matte, in the photos
    dark: new THREE.MeshStandardMaterial({
      color: "#0d0e11", roughness: 0.99, metalness: 0.0,
      bumpMap: bump, bumpScale: 0.04, side: THREE.DoubleSide,
    }),
    // Bare structural steel (brackets, fittings)
    steel: new THREE.MeshStandardMaterial({
      color: "#20232a", roughness: 0.62, metalness: 0.65,
    }),
    // Keel sump — same coating, worn darker
    keel: new THREE.MeshStandardMaterial({
      color: "#5c2a23", roughness: 0.95, metalness: 0.0,
      bumpMap: bump, bumpScale: 0.05,
    }),
  };
}
function getMats() {
  if (!_mats) _mats = buildMats();
  return _mats;
}

// ── Hull section profile ──────────────────────────────────────
// One continuous curve from the floor edge to the tank top, the way a bulk
// carrier hold is actually shaped: hopper slope → vertical side shell →
// topside tank slope leaning back in overhead. Because it is a single curved
// surface, the painted coat boundary sweeps across it instead of reading as a
// straight line on a flat wall.
interface Station { z: number; y: number; ny: number; nz: number; s: number }

function buildProfile(): Station[] {
  const pts: [number, number][] = [];
  // Hopper: quarter ellipse (FHW,0) → (THW,BH)
  for (let i = 0; i <= NSEG; i++) {
    const t = (Math.PI / 2) * (i / NSEG);
    pts.push([FHW + (THW - FHW) * Math.sin(t), BH * (1 - Math.cos(t))]);
  }
  // Side shell: straight up (THW,BH) → (THW,TS)
  for (let i = 1; i <= 4; i++) pts.push([THW, BH + (TS - BH) * (i / 4)]);
  // Topside slope: eased curve (THW,TS) → (TTW,TH), knuckle at the bottom
  for (let i = 1; i <= 8; i++) {
    const u = i / 8;
    pts.push([THW - (THW - TTW) * (1 - Math.cos(u * Math.PI / 2)), TS + (TH - TS) * u]);
  }

  // Inward normals from central differences, so every knuckle shades smoothly.
  let acc = 0;
  return pts.map(([z, y], i) => {
    const p = pts[Math.max(0, i - 1)], n = pts[Math.min(pts.length - 1, i + 1)];
    const dz = n[0] - p[0], dy = n[1] - p[1];
    const l = Math.hypot(dy, dz) || 1;
    if (i > 0) acc += Math.hypot(z - pts[i - 1][0], y - pts[i - 1][1]);
    return { z, y, ny: -dz / l, nz: dy / l, s: acc };
  });
}
const PROFILE = buildProfile();
const ARC = PROFILE[PROFILE.length - 1].s;

/** Half-width of the hold at height y — details must sit on the curve. */
function zAt(y: number): number {
  for (let i = 1; i < PROFILE.length; i++) {
    if (PROFILE[i].y >= y) {
      const a = PROFILE[i - 1], b = PROFILE[i];
      const f = (y - a.y) / (b.y - a.y || 1);
      return a.z + (b.z - a.z) * f;
    }
  }
  return PROFILE[PROFILE.length - 1].z;
}

/** Arc-length fraction at height y, i.e. where a paint band lands in v. */
function vAt(y: number): number {
  for (let i = 1; i < PROFILE.length; i++) {
    if (PROFILE[i].y >= y) {
      const a = PROFILE[i - 1], b = PROFILE[i];
      const f = (y - a.y) / (b.y - a.y || 1);
      return (a.s + (b.s - a.s) * f) / ARC;
    }
  }
  return 1;
}

// ── Longitudinal taper ────────────────────────────────────────
// A hold is not a straight box: it keeps its full beam amidships and narrows
// toward the ends. That taper is why the coat boundary and the knuckles sweep
// across the reference photos in long curves instead of running dead level.
const NX = 56;
function beam(x: number): number {
  const t = Math.abs(2 * x / TL - 1);   // 0 amidships → 1 at the ends
  return 1 - 0.40 * Math.pow(t, 2.2);
}

// ── Side shell: the profile lofted along the tapered length ────
// Indexed grid + computeVertexNormals, so the taper is shaded correctly
// instead of needing hand-derived normals for a doubly-curved surface.
function buildSideGeo(sign: 1 | -1): THREE.BufferGeometry {
  const rows = PROFILE.length, cols = NX + 1;
  const pos = new Float32Array(rows * cols * 3);
  const uv  = new Float32Array(rows * cols * 2);
  for (let i = 0; i < rows; i++) {
    const p = PROFILE[i];
    for (let j = 0; j < cols; j++) {
      const x = (TL * j) / NX, k = i * cols + j;
      pos[k*3] = x; pos[k*3+1] = p.y; pos[k*3+2] = sign * p.z * beam(x);
      uv[k*2] = x / TL; uv[k*2+1] = p.s / ARC;
    }
  }
  // Mirroring z flips handedness, so the port side needs reversed winding —
  // otherwise its interior faces are back faces and DoubleSide inverts their
  // shading normal, leaving the whole side unlit.
  const idx: number[] = [];
  for (let i = 0; i < rows - 1; i++) {
    for (let j = 0; j < cols - 1; j++) {
      const a = i*cols + j, b = a + 1, c = a + cols, d = c + 1;
      if (sign === 1) idx.push(a, b, d, a, d, c);
      else            idx.push(a, d, b, a, c, d);
    }
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  geo.setAttribute("uv",       new THREE.BufferAttribute(uv,  2));
  geo.setIndex(idx);
  geo.computeVertexNormals();
  return geo;
}

// ── Tank top plating, tapered to match ────────────────────────
function buildFloorGeo(): THREE.BufferGeometry {
  const pos: number[] = [], uv: number[] = [], idx: number[] = [];
  for (let j = 0; j <= NX; j++) {
    const x = (TL * j) / NX, w = FHW * beam(x);
    pos.push(x, 0, -w, x, 0, w);
    uv.push(x / TL, 0, x / TL, 1);
  }
  for (let j = 0; j < NX; j++) {
    const a = j*2, b = a + 1, c = a + 2, d = a + 3;
    idx.push(a, c, d, a, d, b);
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  geo.setAttribute("uv",       new THREE.Float32BufferAttribute(uv,  2));
  geo.setIndex(idx);
  geo.computeVertexNormals();
  return geo;
}

// ── Bulkhead: the same section, filled in ─────────────────────
function buildEndWall(xPos: number, nx: number): THREE.BufferGeometry {
  const pos: number[] = [], nor: number[] = [], uv: number[] = [];
  const bw = beam(xPos);
  const addTri = (...vs: [number, number, number][]) => {
    for (const [px, py, pz] of vs) {
      pos.push(px, py, pz); nor.push(nx, 0, 0);
      uv.push((pz + THW) / (THW * 2), py / TH);
    }
  };
  // Fan each side of the section back to the centreline
  for (const s of [1, -1] as const) {
    for (let i = 0; i < PROFILE.length - 1; i++) {
      const a = PROFILE[i], b = PROFILE[i + 1];
      addTri([xPos, a.y, s * a.z * bw], [xPos, a.y, 0], [xPos, b.y, s * b.z * bw]);
      addTri([xPos, a.y, 0], [xPos, b.y, 0], [xPos, b.y, s * b.z * bw]);
    }
  }
  // Flat floor strip between the two hopper toes
  const fw = FHW * bw;
  addTri([xPos, 0, -fw], [xPos, 0, fw], [xPos, 0.01, fw]);
  addTri([xPos, 0, -fw], [xPos, 0.01, fw], [xPos, 0.01, -fw]);

  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  geo.setAttribute("normal",   new THREE.Float32BufferAttribute(nor, 3));
  geo.setAttribute("uv",       new THREE.Float32BufferAttribute(uv,  2));
  return geo;
}

// ── Cargo Hold geometry + details ────────────────────────────────
function CargoHold({ cutaway }: { cutaway: boolean }) {
  const mats = useMemo(() => getMats(), []);
  const sideS = useMemo(() => buildSideGeo(1),  []);
  const sideP = useMemo(() => buildSideGeo(-1), []);
  const floor = useMemo(() => buildFloorGeo(), []);
  const front = useMemo(() => buildEndWall(0,   1), []);
  const back  = useMemo(() => buildEndWall(TL, -1), []);

  return (
    <group>
      {/* ── Tank top plating (flat floor of the hold) ── */}
      <mesh geometry={floor} material={mats.red} />

      {/* ── Side shells: hopper → side → topside slope, one surface each.
             The port side is sectioned away in the cutaway view. ── */}
      <mesh geometry={sideS} material={mats.wall} />
      {!cutaway && <mesh geometry={sideP} material={mats.wall} />}

      {/* ── Cut edge along the sectioned port side ── */}
      {cutaway && (
        <mesh position={[TL/2, 0.11, -FHW]} material={mats.steel}>
          <boxGeometry args={[TL, 0.22, 0.3]} />
        </mesh>
      )}

      {/* ── End walls ── */}
      <mesh geometry={front} material={mats.bulkhead} />
      <mesh geometry={back}  material={mats.bulkhead} />

      {/* ── Deck transverses spanning the tank-top opening ──
             In cutaway they stop at the section plane instead of spanning fully. */}
      {Array.from({ length: Math.floor(TL/5) - 1 }, (_, i) => (i+1)*5).map(x => (
        <group key={x} position={[x, TH, cutaway ? (TTW - FHW)/2 : 0]}>
          <mesh material={mats.dark}>
            <boxGeometry args={[0.5, 0.7, cutaway ? TTW + FHW : TTW*2]} />
          </mesh>
          {/* I-beam flanges */}
          <mesh position={[0, -0.35, 0]} material={mats.steel}>
            <boxGeometry args={[0.6, 0.12, (cutaway ? TTW + FHW : TTW*2) + 0.2]} />
          </mesh>
        </group>
      ))}

      {/* ── Hatch coaming rail along each top edge ── */}
      <mesh position={[TL/2, TH - 0.1, TTW - 0.06]} material={mats.steel}>
        <boxGeometry args={[TL, 0.2, 0.12]} />
      </mesh>
      {!cutaway && (
        <mesh position={[TL/2, TH - 0.1, -TTW + 0.06]} material={mats.steel}>
          <boxGeometry args={[TL, 0.2, 0.12]} />
        </mesh>
      )}
    </group>
  );
}

// ── Hold Details ────────────────────────────────────────────────
function HoldDetails({ cutaway }: { cutaway: boolean }) {
  const mats = useMemo(() => getMats(), []);

  // Alternating red/white dot markers along top of walls
  const dots = useMemo(() => {
    const result: { x: number; z: number; red: boolean }[] = [];
    for (let x = 4; x <= TL - 4; x += 3) {
      const zw = zAt(DOT_Y) * beam(x) - 0.06;
      const red = Math.round(x / 3) % 2 === 0;
      result.push({ x, z:  zw, red });
      if (!cutaway) result.push({ x, z: -zw, red: !red });
    }
    return result;
  }, [cutaway]);

  // Wall bracket/sensor fixture positions
  const brackets = useMemo(() => {
    const result: { x: number; z: number }[] = [];
    for (let x = 7; x < TL; x += 7) {
      const zw = zAt(BRACKET_Y) * beam(x) - 0.1;
      result.push({ x, z:  zw });
      if (!cutaway) result.push({ x, z: -zw });
    }
    return result;
  }, [cutaway]);

  // Ship wall text labels ("TUG", "OUT", "No.1", etc.) — starboard only in cutaway
  const allLabels = ["TUG", "OUT", "No.1", "TUG", "OUT", "No.2"];
  const allLabelX  = [8, 18, 28, 38, 48, 55];
  const labelIdx = allLabelX
    .map((_, i) => i)
    .filter(i => !cutaway || i % 2 === 1);

  return (
    <group>
      {/* Keel sump ball */}
      <mesh position={[TL/2, 0.6, 0]} material={mats.keel}>
        <sphereGeometry args={[0.65, 20, 14]} />
      </mesh>

      {/* Floor center channel (dark strip) */}
      <mesh rotation={[-Math.PI/2, 0, 0]} position={[TL/2, 0.006, 0]}>
        <planeGeometry args={[TL, 1.2]} />
        <meshStandardMaterial color="#3a0808" roughness={0.98} />
      </mesh>

      {/* Floor hatch markings */}
      {[10, 20, 30, 40, 50].map(x => (
        <mesh key={x} rotation={[-Math.PI/2, 0, 0]} position={[x, 0.007, 0]}>
          <planeGeometry args={[2.5, 1.8]} />
          <meshStandardMaterial color="#2a0606" roughness={0.97} />
        </mesh>
      ))}

      {/* Dot markers */}
      {dots.map((d, i) => (
        <mesh key={i} position={[d.x, DOT_Y, d.z]}>
          <sphereGeometry args={[0.14, 10, 10]} />
          <meshStandardMaterial
            color={d.red ? "#cc1111" : "#dddddd"}
            roughness={0.35} metalness={0.3}
            emissive={d.red ? "#440000" : "#111111"} emissiveIntensity={0.2}
          />
        </mesh>
      ))}

      {/* Bracket fixtures */}
      {brackets.map((b, i) => (
        <group key={i} position={[b.x, BRACKET_Y, b.z]}>
          <mesh material={mats.steel}>
            <boxGeometry args={[0.5, 0.08, 0.06]} />
          </mesh>
          <mesh position={[0, -0.2, 0]} material={mats.steel}>
            <boxGeometry args={[0.06, 0.35, 0.06]} />
          </mesh>
          <mesh position={[0, -0.38, 0]}>
            <cylinderGeometry args={[0.07, 0.07, 0.14, 8]} />
            <meshStandardMaterial color="#1a1c22" roughness={0.5} metalness={0.6} />
          </mesh>
        </group>
      ))}

      {/* Wall text HTML labels */}
      {labelIdx.map(i => (
        <Html
          key={i}
          position={[allLabelX[i], LABEL_Y, (i % 2 === 0 ? -1 : 1) * (zAt(LABEL_Y) * beam(allLabelX[i]) - 0.2)]}
          center
          style={{
            color: "rgba(255,255,255,0.55)",
            fontSize: "11px",
            fontFamily: "monospace",
            letterSpacing: "2px",
            pointerEvents: "none",
            whiteSpace: "nowrap",
          }}
        >
          {allLabels[i]}
        </Html>
      ))}

      {/* Manhole hatch ring at front bulkhead */}
      <mesh position={[0.02, BH*0.6, 0]} rotation={[0, Math.PI/2, 0]}>
        <ringGeometry args={[0.8, 1.3, 20]} />
        <meshStandardMaterial color="#2a2d35" roughness={0.75} metalness={0.5} />
      </mesh>
      <mesh position={[0.01, BH*0.6, 0]} rotation={[0, Math.PI/2, 0]}>
        <circleGeometry args={[0.78, 20]} />
        <meshStandardMaterial color="#090a0d" roughness={0.95} />
      </mesh>

      {/* Back bulkhead manhole */}
      <mesh position={[TL - 0.02, BH*0.6, 0]} rotation={[0, -Math.PI/2, 0]}>
        <ringGeometry args={[0.8, 1.3, 20]} />
        <meshStandardMaterial color="#2a2d35" roughness={0.75} metalness={0.5} />
      </mesh>
    </group>
  );
}

// ── Camera controller ──────────────────────────────────────────
function CameraController({
  mode,
  controlsRef,
}: {
  mode: CamMode;
  controlsRef: { current: OrbitControlsImpl | null };
}) {
  const { camera, invalidate, gl, scene } = useThree();
  const sceneControls = useThree((state) => state.controls) as OrbitControlsImpl | null;
  const appliedMode = useRef<CamMode | null>(null);

  // Apply after OrbitControls has mounted, then repeat on the next frame so
  // entering the twin screen never leaves the controls aimed at the origin.
  useEffect(() => {
    const tgt = CAMS[mode].tgt;
    appliedMode.current = null;
    const applyCamera = () => {
      const controls = controlsRef.current ?? sceneControls;
      const aspect = camera instanceof THREE.PerspectiveCamera ? camera.aspect : 1;
      const pos = cameraPosition(mode, aspect);
      camera.position.set(...pos);
      if (controls) {
        controls.target.set(...tgt);
        controls.update();
      }
      camera.lookAt(...tgt);
      invalidate();
      // Draw this view immediately. invalidate() only queues a frame, and some
      // hosts (embedded/background views) never deliver a requestAnimationFrame
      // tick, which would otherwise leave the canvas blank.
      gl.render(scene, camera);
    };

    applyCamera();
    const frame = requestAnimationFrame(applyCamera);
    return () => cancelAnimationFrame(frame);
  }, [mode, camera, invalidate, gl, scene, sceneControls, controlsRef]);

  useFrame(() => {
    if (appliedMode.current === mode) return;
    const controls = controlsRef.current ?? sceneControls;
    if (!controls) return;
    const tgt = CAMS[mode].tgt;
    const aspect = camera instanceof THREE.PerspectiveCamera ? camera.aspect : 1;
    const pos = cameraPosition(mode, aspect);
    controls.target.set(...tgt);
    camera.position.set(...pos);
    camera.lookAt(...tgt);
    controls.update();
    appliedMode.current = mode;
  });

  return null;
}

// ── Hazard / Sensor markers (unchanged logic) ──────────────────
const HAZARD_R = 3.0;
function HazardZone({ level }: { level: AlertLevel }) {
  const color = LEVEL_COLOR[level];
  return (
    <mesh rotation={[-Math.PI/2, 0, 0]} position={[0, 0.06, 0]}>
      <ringGeometry args={[HAZARD_R - 0.18, HAZARD_R, 48]} />
      <meshStandardMaterial color={color} transparent opacity={0.6}
        emissive={color} emissiveIntensity={0.5} side={2} />
    </mesh>
  );
}

function SensorMarker({ id, x, y, level }: { id: string; x: number; y: number; level: AlertLevel }) {
  const color = LEVEL_COLOR[level];
  const isDanger = level !== "normal";
  const showHazard = level === "level2_warning" || level === "level3_critical";
  const groupRef = useRef<Group>(null);
  const [hov, setHov] = useState(false);
  useFrame(s => {
    if (!groupRef.current || !isDanger) return;
    groupRef.current.scale.setScalar(1 + Math.sin(s.clock.getElapsedTime() * 4) * 0.12);
  });
  return (
    <group position={toThreeGroundPosition(x, y, 0.9)}>
      {showHazard && <HazardZone level={level} />}
      <group ref={groupRef}
        onPointerOver={e => { e.stopPropagation(); setHov(true); }}
        onPointerOut={() => setHov(false)}>
        <mesh>
          <cylinderGeometry args={[0.22, 0.22, 1.7, 16]} />
          <meshStandardMaterial color={color} emissive={color} emissiveIntensity={isDanger ? 0.7 : 0.25} />
        </mesh>
        <mesh position={[0, 1.15, 0]}>
          <sphereGeometry args={[hov ? 0.5 : 0.34, 16, 16]} />
          <meshStandardMaterial color={color} emissive={color} emissiveIntensity={0.8} />
        </mesh>
        <pointLight position={[0, 1.15, 0]} color={color}
          intensity={isDanger ? 6 : 2} distance={7} />
      </group>
      <Html position={[0, 2.4, 0]} center distanceFactor={30}>
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
  const ref = useRef<Group>(null);
  useFrame(s => {
    if (ref.current) ref.current.position.y = 1.7 + Math.sin(s.clock.getElapsedTime() * 2) * 0.2;
  });
  return (
    <group position={toThreePosition({ x_m: x, y_m: y, z_m: z })} ref={ref}>
      <mesh>
        <sphereGeometry args={[0.4, 16, 16]} />
        <meshStandardMaterial color={color} emissive={color} emissiveIntensity={0.8} />
      </mesh>
      <pointLight color={color} intensity={fall_detected ? 12 : 5} distance={9} />
      <Html position={[0, 1.2, 0]} center distanceFactor={30}>
        <div className={"twin-node-label " + (fall_detected ? "twin-node-level3_critical" : "twin-wearable")}>
          <span className="twin-node-id">wearable</span>
          {fall_detected && <span className="twin-node-level">낙하</span>}
        </div>
      </Html>
    </group>
  );
}

// ── Scene content ──────────────────────────────────────────────
function SceneContent({
  nodes, wearable, heatmap, mode,
}: {
  nodes: NonNullable<TwinSceneProps["nodes"]>;
  wearable: TwinSceneProps["wearable"];
  heatmap: TwinSceneProps["heatmap"];
  mode: CamMode;
}) {
  const cutaway = mode === "overview";
  const controlsRef = useRef<OrbitControlsImpl>(null);
  return (
    <>
      {/* The photos are lit from low down: light pools on the bilge and the
          lower wall and falls off to a pitch-black tank top. Keep ambient
          minimal so that falloff survives. */}
      <ambientLight intensity={cutaway ? 0.8 : 0.07} />

      {/* Depth falloff down the hold — the far end goes black, as in the photos */}
      {!cutaway && <fog attach="fog" args={["#04050a", 10, 62]} />}

      {/* Cutaway view: daylight spilling in across the sectioned side */}
      {cutaway && (
        <>
          <directionalLight position={[TL*0.3, TH*2.2, -TH*2]} intensity={1.5} color="#e2e9ff" />
          <directionalLight position={[TL*0.8, TH*1.2, TH*1.5]} intensity={0.45} color="#7d90c4" />
        </>
      )}

      {/* Working lights sitting low, as in the reference: the coating is lit
          from below so the topside blue falls off into darkness toward the
          tank top rather than being evenly washed. */}
      {[8, 20, 32, 44, 56].map(x => (
        <pointLight key={x} position={[x, BH * 1.35, 0]}
          intensity={210} distance={28} decay={2} color="#cfd9f2" />
      ))}

      {/* Faint bounce off the coated walls, keeps corners from going pure black */}
      {[12, 36].map(x => (
        <pointLight key={x} position={[x, BH * 0.7, 0]}
          intensity={55} distance={22} decay={2} color="#8f6153" />
      ))}

      <CargoHold cutaway={cutaway} />
      <HoldDetails cutaway={cutaway} />

      {heatmap && heatmap.samples.length > 0 && (
        <Heatmap sensors={heatmap.samples} metric={heatmap.metric} />
      )}
      {nodes.map(n => (
        <SensorMarker key={n.id} id={n.id} x={n.x} y={n.y} level={n.level} />
      ))}
      {wearable && (
        <WearableMarker x={wearable.x} y={wearable.y} z={wearable.z}
          fall_detected={!!wearable.fall_detected} />
      )}
      <OrbitControls
        ref={controlsRef}
        makeDefault
        target={CAMS[mode].tgt}
        minDistance={2}
        maxDistance={160}
        maxPolarAngle={Math.PI * 0.9}
      />
      <CameraController mode={mode} controlsRef={controlsRef} />
      <ReleaseContextOnUnmount />
    </>
  );
}

/**
 * 언마운트 시 WebGL 컨텍스트를 반납한다.
 *
 * 모니터링 화면(축소 트윈)과 트윈 화면이 각각 Canvas 를 만들므로, 화면을 전환하면
 * 이전 컨텍스트가 살아 있는 채로 새 컨텍스트를 요청하게 된다. 브라우저의 동시
 * 컨텍스트 한도는 넉넉하지 않아서 반납해 두는 편이 안전하다.
 */
function ReleaseContextOnUnmount() {
  const { gl } = useThree();
  useEffect(
    () => () => {
      // 탭이 백그라운드로 가면 브라우저가 먼저 컨텍스트를 회수한다.
      // 그 상태에서 forceContextLoss() 를 부르면 INVALID_OPERATION 이 찍힌다.
      const ctx = gl.getContext();
      if (ctx && !ctx.isContextLost()) gl.forceContextLoss();
      gl.dispose();
    },
    [gl],
  );
  return null;
}

// ── TwinScene (exported) ───────────────────────────────────────
export function TwinScene({ nodes = [], wearable = null, heatmap = null }: TwinSceneProps) {
  const [mode, setMode] = useState<CamMode>("overview");
  return (
    <div className="twin-canvas" style={{ position: "relative" }}>
      {/* Camera mode toggle */}
      <div style={{
        position: "absolute", top: 8, right: 10, zIndex: 10,
        display: "flex", gap: 6,
      }}>
        {(["overview", "inside"] as CamMode[]).map(m => (
          <button
            key={m}
            onClick={() => setMode(m)}
            style={{
              padding: "3px 10px", fontSize: 11, borderRadius: 4, cursor: "pointer",
              background: mode === m ? "#3b82f6" : "#1e2436",
              color: "#fff", border: "1px solid " + (mode === m ? "#3b82f6" : "#374151"),
            }}
          >
            {m === "overview" ? "전체 뷰" : "내부 시점"}
          </button>
        ))}
      </div>

      <Canvas
        camera={{ position: CAMS.overview.pos, fov: 60 }}
        frameloop="always"
        gl={{ antialias: true }}
      >
        <color attach="background" args={["#07090e"]} />
        <SceneContent nodes={nodes} wearable={wearable}
          heatmap={heatmap} mode={mode} />
      </Canvas>
    </div>
  );
}
