import { useAuthStore } from "../store/authStore";

/**
 * 인증이 필요한 모든 API 호출의 공통 경로 (AUTH-8, 이슈 #138).
 *
 * - credentials: "include" — 세션 쿠키(HttpOnly)를 함께 보낸다. 기본 fetch 는
 *   same-origin 이라도 명시가 안전하다 (vite dev proxy 는 교차 오리진 취급).
 * - CSRF: 상태 변경(POST/PUT/PATCH/DELETE)은 double-submit 토큰 헤더를 붙인다.
 *   서버가 로그인 때 내려준 hp015_csrf 쿠키를 그대로 되돌려 보낸다.
 * - 401 인터셉터: 세션 만료 시 authStore 를 unauthenticated 로 바꾼다.
 *   화면 전환은 App 이 status 로 한다 — 활성 경보 UI 유지 여부는 AUTH-7(#137).
 */
export async function fetchApi<T>(
  path: string,
  init: RequestInit & { csrf?: boolean } = {},
): Promise<T> {
  const { csrf, ...rest } = init;
  const headers = new Headers(rest.headers);
  if (rest.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (csrf) {
    const token = readCookie("hp015_csrf");
    if (token) headers.set("X-CSRF-Token", token);
  }

  const resp = await fetch(path, {
    ...rest,
    headers,
    credentials: "include",
  });

  if (resp.status === 401 && !path.startsWith("/api/auth/login")) {
    useAuthStore.getState().expire();
    throw new UnauthorizedError(path);
  }
  if (!resp.ok) {
    const detail = await safeDetail(resp);
    throw new ApiError(resp.status, detail ?? `${resp.status} ${resp.statusText}`);
  }
  if (resp.status === 204) return undefined as T;
  return (await resp.json()) as T;
}

export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

export class UnauthorizedError extends Error {}

function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
}

async function safeDetail(resp: Response): Promise<string | null> {
  try {
    const body = (await resp.json()) as { detail?: unknown };
    if (typeof body.detail === "string") return body.detail;
  } catch {
    /* 본문 없음 */
  }
  return null;
}
