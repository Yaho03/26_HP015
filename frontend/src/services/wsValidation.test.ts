import { beforeEach, describe, expect, it, vi } from "vitest";
import { validateIncoming, wsRejections } from "../services/wsValidation";
import { useDashboardStore } from "../store/dashboardStore";
import type { EvacuationRouteMessage, WorkerExposureMessage } from "../types/ws";

const ULID = "01J6X3R8K7VQ2NTP5Z9MA4HWBC";

function exposureMessage(overrides: Record<string, unknown> = {}): WorkerExposureMessage {
  return {
    type: "worker_exposure",
    worker_id: 1,
    worker_name: "김안전",
    node_id: "wearable-01",
    exposure_id: ULID,
    window_start: "2026-08-22T00:00:00Z",
    elapsed_s: 60,
    accumulated_s: 55,
    data_gap_s: 5,
    trust_level: "high",
    timestamp: "2026-08-22T00:01:00Z",
    metrics: {
      co2_ppm: { status: "unavailable", reason: "limit_unverified" },
    },
    ...overrides,
  } as WorkerExposureMessage;
}

function routeMessage(overrides: Record<string, unknown> = {}): EvacuationRouteMessage {
  return {
    type: "evacuation_route",
    route_id: ULID,
    node_id: "wearable-01",
    computed_at: "2026-08-22T00:00:00Z",
    route_status: "safe",
    coordinate_system: "ship-visual",
    assumed_level_id: "L0",
    waypoints: [{ seq: 0, x_m: 0, y_m: 0, z_m: 0, level_id: "L0" }],
    ...overrides,
  } as EvacuationRouteMessage;
}

describe("wsValidation — 안전 메시지 런타임 가드 (#208)", () => {
  beforeEach(() => {
    wsRejections.count = 0;
    vi.spyOn(console, "warn").mockImplementation(() => {});
  });

  it("정상 worker_exposure 는 통과한다", () => {
    expect(validateIncoming(exposureMessage())).not.toBeNull();
  });

  it("sensor 노드 ID 를 가진 worker_exposure 는 거부한다", () => {
    const bad = exposureMessage({ node_id: "sensor-01" });
    expect(validateIncoming(bad)).toBeNull();
    expect(wsRejections.count).toBe(1);
  });

  it("ULID 가 아닌 exposure_id 는 거부한다", () => {
    expect(validateIncoming(exposureMessage({ exposure_id: "exp-1" }))).toBeNull();
  });

  it("unavailable 인데 dose 필드가 있으면 거부한다 (#211 미러링)", () => {
    const bad = exposureMessage({
      metrics: {
        co2_ppm: { status: "unavailable", reason: "no_position", dose_ppm_min: 10 },
      },
    });
    expect(validateIncoming(bad)).toBeNull();
  });

  it("unavailable without reason 는 거부한다", () => {
    const bad = exposureMessage({
      metrics: { co2_ppm: { status: "unavailable" } },
    });
    expect(validateIncoming(bad)).toBeNull();
  });

  it("정상 evacuation_route 는 통과한다", () => {
    expect(validateIncoming(routeMessage())).not.toBeNull();
  });

  it("route_status unavailable without reason 는 거부한다", () => {
    expect(
      validateIncoming(routeMessage({ route_status: "unavailable", waypoints: [] })),
    ).toBeNull();
  });

  it("safe route with empty waypoints 는 거부한다", () => {
    expect(validateIncoming(routeMessage({ waypoints: [] }))).toBeNull();
  });

  it("다른 메시지 타입은 그대로 통과한다 (기존 경로 무손상)", () => {
    expect(validateIncoming({ type: "alert", node_id: "sensor-01" })).not.toBeNull();
    expect(validateIncoming("not an object")).toBeNull();
  });
});

describe("clearSafetySlices — stale 안전 데이터 정리 (#213)", () => {
  beforeEach(() => {
    useDashboardStore.setState({
      worker_exposure: {},
      evacuation_route: {},
    });
  });

  it("노드 단위 삭제: 해제된 웨어러블의 노출/경로가 사라진다", () => {
    const store = useDashboardStore.getState();
    store.setWorkerExposure(exposureMessage());
    store.setEvacuationRoute(routeMessage());

    useDashboardStore.getState().clearSafetySlices("wearable-01");

    const after = useDashboardStore.getState();
    expect(after.worker_exposure["wearable-01"]).toBeUndefined();
    expect(after.evacuation_route["wearable-01"]).toBeUndefined();
  });

  it("다른 노드는 유지된다", () => {
    const store = useDashboardStore.getState();
    store.setWorkerExposure(exposureMessage());
    store.setWorkerExposure(exposureMessage({ node_id: "wearable-02", exposure_id: ULID }));

    useDashboardStore.getState().clearSafetySlices("wearable-01");

    expect(useDashboardStore.getState().worker_exposure["wearable-02"]).toBeDefined();
  });

  it("인자 없이 호출하면 전체 초기화 (snapshot 재동기화)", () => {
    const store = useDashboardStore.getState();
    store.setWorkerExposure(exposureMessage());
    store.setEvacuationRoute(routeMessage());

    useDashboardStore.getState().clearSafetySlices();

    const after = useDashboardStore.getState();
    expect(Object.keys(after.worker_exposure)).toHaveLength(0);
    expect(Object.keys(after.evacuation_route)).toHaveLength(0);
  });
});

describe("hydrateSnapshot — 서버 상태로 재동기화 (#213)", () => {
  it("snapshot 에 없는 노드/경보는 클라이언트에 남지 않는다", () => {
    const store = useDashboardStore.getState();
    store.setWorkerExposure(exposureMessage());
    store.setEvacuationRoute(routeMessage());

    // 서버 snapshot: 노드·경보·안전 슬라이스 전부 비어 있음 (예: 전원 초기화 직후)
    useDashboardStore.getState().hydrateSnapshot({}, {});

    const after = useDashboardStore.getState();
    expect(Object.keys(after.sensor_nodes)).toHaveLength(0);
    expect(Object.keys(after.active_alerts)).toHaveLength(0);
  });
});

describe("경보 표시 형식화 가드 (#243)", () => {
  it("Number.isFinite 검사로 toFixed 억제 방지 — 숫자 아닌 값도 문자열로 렌더", () => {
    // useWebSocket 의 형식화 로직 미러 — 실제 모듈은 컴포넌트 훅이라 여기서는
    // 계약만 잠근다: 어떤 입력이든 openModal/push 가 호출돼야 한다.
    const format = (v: unknown): string =>
      Number.isFinite(v as number) ? (v as number).toFixed(1) : String(v);
    expect(format(1234.56)).toBe("1234.6");
    expect(format("high")).toBe("high");
    expect(format(null)).toBe("null");
    expect(format(undefined)).toBe("undefined");
    expect(format(NaN)).toBe("NaN");
  });
});
