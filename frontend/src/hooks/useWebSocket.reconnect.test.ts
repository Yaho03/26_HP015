/**
 * useWebSocket 재인증 재연결 (#242).
 *
 * 훅은 React 환경이라 여기선 계약을 직접 검증한다: 세션 만료(1008) 후
 * 재로그인하면 useWebSocket 이 새 WSClient 를 만들어 connect 한다 —
 * 1008 에서 shouldReconnect=false 가 된 옛 클라이언트를 재사용하지 않는다.
 * 소스 수준 단언 + wsClient 동작 단언으로 잠근다.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

describe("useWebSocket 재인증 재연결 (#242)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });
  it("훅이 authStatus 를 의존성으로 두고 authenticated 에서만 연결한다", () => {
    const src = readFileSync(resolve(__dirname, "useWebSocket.ts"), "utf-8");
    // authStatus 게이트 — 미인증 시 연결 없음
    expect(src).toContain('authStatus !== "authenticated"');
    // effect 의존성에 authStatus — 재로그인 시 effect 재실행(새 클라이언트)
    expect(src).toMatch(/\[url, setConnectionStatus, expire, authStatus\]/);
  });

  it("1008 후 타이머는 잡히지 않는다 — 재연결은 외부에서 새로 시작해야 한다", async () => {
    const { WSClient: C, WS_CLOSE_AUTH_EXPIRED: CODE } = await import("../services/wsClient");
    const sockets: { fireClose: (code: number) => void }[] = [];
    const Ctor = vi.fn(function () {
      const s = {
        readyState: 0,
        send: vi.fn(),
        close: vi.fn(),
        set onopen(_: unknown) {},
        set onerror(_: unknown) {},
        set onmessage(_: unknown) {},
        set onclose(fn: (ev: { code: number }) => void) {
          (this as { _close?: (ev: { code: number }) => void })._close = fn;
        },
        fireClose(code: number) {
          ((this as { _close?: (ev: { code: number }) => void })._close ?? (() => {}))({ code });
        },
      };
      sockets.push(s as never);
      return s;
    });
    vi.stubGlobal("WebSocket", Ctor as unknown as typeof WebSocket);

    const client = new C("ws://test/ws");
    client.connect();
    expect(sockets.length).toBe(1);

    (sockets[0] as unknown as { fireClose: (c: number) => void }).fireClose(CODE);
    // 폭주 방지(#134): 1008 뒤에는 백오프 타이머가 잡히지 않는다.
    // 재연결은 useWebSocket 의 authStatus 전환(재로그인)이 새로 시작한다.
    vi.advanceTimersByTime(10_000);
    expect(sockets.length).toBe(1);
    client.disconnect();
    vi.unstubAllGlobals();
  });
});
