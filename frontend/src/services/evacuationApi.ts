import { API_BASE } from "./api";
import type { NavTopology } from "../types/evacuation";
import type { EvacuationRouteMessage } from "../types/ws";

/**
 * 탈출 경로 REST (12_EVACUATION_ROUTE_SPEC §4.2).
 *
 * api.ts 에 합치지 않고 파일을 나눈 이유: 누적 노출량(FR-701)이 같은 파일 끝에
 * 자기 엔드포인트를 붙일 예정이라 양쪽이 같은 자리를 고치게 된다.
 */

/** CSRF double-submit 토큰 (FR-608). 서버가 쿠키로 내려준 값을 헤더에도 싣는다. */
const CSRF_COOKIE = "hp015_csrf";

function csrfToken(): string {
  const hit = document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(`${CSRF_COOKIE}=`));
  return hit ? decodeURIComponent(hit.slice(CSRF_COOKIE.length + 1)) : "";
}

async function readError(resp: Response, fallback: string): Promise<never> {
  let detail = "";
  try {
    const body = (await resp.json()) as { detail?: unknown };
    detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? "");
  } catch {
    // 본문이 JSON 이 아니면 기본 문구로 간다.
  }
  throw new Error(detail || fallback);
}

/**
 * 기능이 꺼져 있으면 서버가 409 를 준다. 이건 오류가 아니라 상태다 —
 * 사유는 /health 가 이미 말하고 화면은 배너로 표시한다. null 로 돌려준다.
 */
export async function fetchTopology(): Promise<NavTopology | null> {
  const resp = await fetch(`${API_BASE}/api/evacuation/topology`);
  if (resp.status === 409) return null;
  if (!resp.ok) await readError(resp, "통행 구조 조회 실패");
  return (await resp.json()) as NavTopology;
}

/**
 * 현재 경로. 아직 계산된 적이 없으면 404 이고, 그건 정상이다 — 작업자가 아직
 * 측위되지 않았을 뿐이다. 이후 갱신은 WebSocket 이 맡는다.
 */
export async function fetchRoute(nodeId: string): Promise<EvacuationRouteMessage | null> {
  const resp = await fetch(`${API_BASE}/api/evacuation/route/${nodeId}`);
  if (resp.status === 404 || resp.status === 409) return null;
  if (!resp.ok) await readError(resp, "경로 조회 실패");
  return (await resp.json()) as EvacuationRouteMessage;
}

/** 출구를 열거나 닫는다 (supervisor+). 감사 로그에 사유가 함께 남는다. */
export async function setExitUsable(
  exitId: string,
  isUsable: boolean,
  reason: string,
): Promise<void> {
  const resp = await fetch(`${API_BASE}/api/evacuation/exits/${exitId}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": csrfToken(),
    },
    body: JSON.stringify({ is_usable: isUsable, reason }),
  });
  if (!resp.ok) await readError(resp, "출구 상태 변경 실패");
}
