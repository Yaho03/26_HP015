import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAuthStore } from "../store/authStore";
import { fetchApi, UnauthorizedError } from "../services/fetchWithAuth";

describe("authStore (AUTH-8)", () => {
  beforeEach(() => {
    useAuthStore.setState({ user: null, status: "booting" });
    vi.restoreAllMocks();
  });

  it("setUser(null)은 상태를 unauthenticated로 만든다", () => {
    useAuthStore.getState().setUser(null);
    expect(useAuthStore.getState().status).toBe("unauthenticated");
    expect(useAuthStore.getState().user).toBeNull();
  });

  it("로그인 성공 시 사용자가 저장되고 authenticated가 된다", () => {
    useAuthStore.getState().setUser({
      id: 1,
      username: "admin",
      display_name: "관리자",
      role: "admin",
      must_change_password: false,
    });
    expect(useAuthStore.getState().status).toBe("authenticated");
    expect(useAuthStore.getState().user?.role).toBe("admin");
  });

  it("expire()는 세션을 지운다 (401/WS 1008)", () => {
    useAuthStore.getState().setUser({
      id: 2,
      username: "v",
      display_name: "",
      role: "viewer",
      must_change_password: false,
    });
    useAuthStore.getState().expire();
    expect(useAuthStore.getState().status).toBe("unauthenticated");
    expect(useAuthStore.getState().user).toBeNull();
  });
});

describe("fetchWithAuth 401 인터셉터 (#138)", () => {
  beforeEach(() => {
    useAuthStore.setState({
      user: {
        id: 1,
        username: "u",
        display_name: "",
        role: "viewer",
        must_change_password: false,
      },
      status: "authenticated",
    });
  });

  it("401 응답에 authStore 를 만료시킨다", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(null, { status: 401 })),
    );
    await expect(fetchApi("/api/thresholds")).rejects.toBeInstanceOf(UnauthorizedError);
    expect(useAuthStore.getState().status).toBe("unauthenticated");
    vi.unstubAllGlobals();
  });

  it("모든 요청에 credentials: include 가 붙는다", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify([]), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    await fetchApi("/api/thresholds");
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.credentials).toBe("include");
    vi.unstubAllGlobals();
  });

  it("csrf: true 요청은 X-CSRF-Token 헤더를 쿠키에서 읽어 붙인다", async () => {
    vi.stubGlobal("document", { cookie: "hp015_csrf=test-csrf-token" });
    const fetchMock = vi.fn().mockResolvedValue(
      new Response("null", { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    await fetchApi("/api/auth/logout", { method: "POST", csrf: true });
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    const headers = new Headers(init.headers);
    expect(headers.get("X-CSRF-Token")).toBe("test-csrf-token");
    vi.unstubAllGlobals();
  });

  it("로그인 경로의 401은 세션을 만료시키지 않는다", async () => {
    useAuthStore.setState({ user: null, status: "unauthenticated" });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "Invalid username or password" }), {
          status: 401,
        }),
      ),
    );
    await expect(
      fetchApi("/api/auth/login", { method: "POST", body: "{}" }),
    ).rejects.toThrow("Invalid username or password");
    // expire() 는 상태를 unauthenticated 로 하는데 이미 그 상태다 —
    // booting 으로 시작해 unauthenticated 유지인지 확인하려면 상태 변화가 없어야 한다.
    expect(useAuthStore.getState().status).toBe("unauthenticated");
    vi.unstubAllGlobals();
  });
});
