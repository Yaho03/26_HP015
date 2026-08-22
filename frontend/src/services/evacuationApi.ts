import type { NavTopology } from "../types/evacuation";
import type { EvacuationRouteMessage } from "../types/ws";
import { ApiError, fetchApi } from "./fetchWithAuth";

/**
 * 탈출 경로 REST (12_EVACUATION_ROUTE_SPEC §4.2).
 *
 * api.ts 에 합치지 않고 파일을 나눈 이유: 누적 노출량(FR-701)이 같은 파일 끝에
 * 자기 엔드포인트를 붙일 예정이라 양쪽이 같은 자리를 고칠 수 있다.
 *
 * 모든 호출은 fetchWithAuth 를 탄다 — 세션 쿠키(credentials), 상태 변경의
 * X-CSRF-Token 헤더, 401 인터셉터(세션 만료 → 로그인 오버레이)가 공통 경로다.
 */

/**
 * 기능이 꺼져 있으면 서버가 409 를 준다. 이건 오류가 아니라 상태다 —
 * 사유는 /health 가 이미 말하고 화면은 배너로 표시한다. null 로 돌려준다.
 */
export async function fetchTopology(): Promise<NavTopology | null> {
  try {
    return await fetchApi<NavTopology>("/api/evacuation/topology");
  } catch (err) {
    if (err instanceof ApiError && err.status === 409) return null;
    throw err;
  }
}

/**
 * 현재 경로. 아직 계산된 적이 없으면 404 이고, 그건 정상이다 — 작업자가 아직
 * 측위되지 않았을 뿐이다. 이후 갱신은 WebSocket 이 맡는다.
 */
export async function fetchRoute(nodeId: string): Promise<EvacuationRouteMessage | null> {
  try {
    return await fetchApi<EvacuationRouteMessage>(`/api/evacuation/route/${nodeId}`);
  } catch (err) {
    if (err instanceof ApiError && (err.status === 404 || err.status === 409)) return null;
    throw err;
  }
}

/** 출구를 열거나 닫는다 (supervisor+). 감사 로그에 사유가 함께 남는다. */
export async function setExitUsable(
  exitId: string,
  isUsable: boolean,
  reason: string,
): Promise<void> {
  await fetchApi<void>(`/api/evacuation/exits/${exitId}`, {
    method: "PATCH",
    csrf: true,
    body: JSON.stringify({ is_usable: isUsable, reason }),
  });
}
