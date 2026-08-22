import type { WSMessage } from "../types/ws";

/**
 * 안전 메시지 런타임 가드 (이슈 #208).
 *
 * TS 타입은 컴파일 시점 계약일 뿐이다 — 소켓에서 들어오는 것은 신뢰 경계
 * 밖의 입력이다. 잘못된 worker_exposure/evacuation_route 가 `as WSMessage`
 * 단언을 통과하면 오염된 dose/경로가 그대로 화면에 그려진다.
 *
 * 검증은 스키마(schemas/*.schema.json)의 핵심 불변식을 미러링한다:
 * - node_id 가 ^wearable-\d{2}$ (sensor ID 가 작업자 안전 데이터로 저장되는 것 방지)
 * - route_id/exposure_id 가 ULID 형태 (빈 문자열/증분 카운터로 추적성 약화 방지)
 * - unavailable 상태가 dose 필드를 동반하지 않음 (#211 과 동일 규칙)
 *
 * 거부는 조용히 하지 않는다 — 콘솔 + 카운터로 남긴다. 계측 흐름(#208)이
 * 이 카운터를 노출할 수 있다.
 */

const WEARABLE_ID = /^wearable-\d{2}$/;
const ULID = /^[0-7][0-9A-HJKMNP-TV-Z]{25}$/;

export const wsRejections = { count: 0 };

function reject(why: string, raw: unknown): null {
  wsRejections.count += 1;
  // 무음 금지 (#208) — 개발자 콘솔에 type/사유를 남긴다. 핸들러 예외와 달리
  // 잘못된 입력은 우리 잘못이 아니므로 error 가 아니라 warn 레벨이 맞다.
  console.warn("[ws] message rejected:", why, raw);
  return null;
}

function isObject(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function validateWorkerExposure(msg: Record<string, unknown>): WSMessage | null {
  if (typeof msg.node_id !== "string" || !WEARABLE_ID.test(msg.node_id)) {
    return reject("worker_exposure.node_id must match ^wearable-\\d{2}$", msg.node_id);
  }
  if (typeof msg.exposure_id !== "string" || !ULID.test(msg.exposure_id)) {
    return reject("worker_exposure.exposure_id must be a ULID", msg.exposure_id);
  }
  const metrics = msg.metrics;
  if (!isObject(metrics)) {
    return reject("worker_exposure.metrics must be an object", metrics);
  }
  for (const [metric, m] of Object.entries(metrics)) {
    if (!isObject(m)) {
      return reject(`worker_exposure.metrics.${metric} must be an object`, m);
    }
    if (m.status === "unavailable") {
      // #211 계약 — unavailable 은 dose 필드를 동반하지 않는다.
      const forbidden = [
        "dose_ppm_min",
        "dose_fraction",
        "twa_8h_ppm",
        "twa_15min_ppm",
        "peak_ppm",
        "o2_deficient_s",
        "o2_min_pct",
      ];
      for (const f of forbidden) {
        if (f in m) {
          return reject(`worker_exposure.metrics.${metric}: unavailable carries ${f}`, m);
        }
      }
      if (typeof m.reason !== "string") {
        return reject(`worker_exposure.metrics.${metric}: unavailable requires reason`, m);
      }
    }
  }
  return msg as unknown as WSMessage;
}

function validateEvacuationRoute(msg: Record<string, unknown>): WSMessage | null {
  if (typeof msg.node_id !== "string" || !WEARABLE_ID.test(msg.node_id)) {
    return reject("evacuation_route.node_id must match ^wearable-\\d{2}$", msg.node_id);
  }
  if (typeof msg.route_id !== "string" || !ULID.test(msg.route_id)) {
    return reject("evacuation_route.route_id must be a ULID", msg.route_id);
  }
  const status = msg.route_status;
  if (typeof status !== "string") {
    return reject("evacuation_route.route_status missing", msg);
  }
  const waypoints = msg.waypoints;
  if (!Array.isArray(waypoints)) {
    return reject("evacuation_route.waypoints must be an array", waypoints);
  }
  if (status === "unavailable") {
    if (typeof msg.unavailable_reason !== "string") {
      return reject("evacuation_route: unavailable requires unavailable_reason", msg);
    }
  } else if (waypoints.length === 0) {
    // #211 — safe/degraded/no_safe_route 는 그릴 수 있는 경로를 실어야 한다.
    return reject(`evacuation_route: ${status} requires non-empty waypoints`, msg);
  }
  return msg as unknown as WSMessage;
}

/**
 * 안전 메시지 검증 게이트. 통과하면 원본을, 실패하면 null.
 * 나머지 타입은 기존대로 통과시킨다 — 이 게이트는 안전 데이터에만 붙는다.
 */
export function validateIncoming(raw: unknown): WSMessage | null {
  if (!isObject(raw)) {
    return reject("message must be an object", raw);
  }
  const type = raw.type;
  if (type === "worker_exposure") return validateWorkerExposure(raw);
  if (type === "evacuation_route") return validateEvacuationRoute(raw);
  return raw as unknown as WSMessage;
}
