import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { WSClient, WS_CLOSE_AUTH_EXPIRED } from "../services/wsClient";

type CloseFn = (ev: { code: number }) => void;

function fakeSocket() {
  const closeListeners: CloseFn[] = [];
  return {
    readyState: 0,
    send: vi.fn(),
    close: vi.fn(),
    set onopen(fn: () => void) {
      void fn;
    },
    set onerror(fn: () => void) {
      void fn;
    },
    set onmessage(fn: (ev: { data: string }) => void) {
      void fn;
    },
    set onclose(fn: CloseFn) {
      closeListeners.push(fn);
    },
    fireClose(code: number) {
      this.readyState = 3;
      for (const fn of closeListeners) fn({ code });
    },
  };
}

describe("WSClient 1008 인증 만료 처리 (#134)", () => {
  let originalWebSocket: typeof WebSocket;

  beforeEach(() => {
    originalWebSocket = globalThis.WebSocket;
    vi.useFakeTimers();
  });

  afterEach(() => {
    globalThis.WebSocket = originalWebSocket;
    vi.useRealTimers();
  });

  function mockWs() {
    const sockets: ReturnType<typeof fakeSocket>[] = [];
    const Ctor = vi.fn(function () {
      const s = fakeSocket();
      sockets.push(s);
      return s;
    }) as unknown as typeof WebSocket;
    globalThis.WebSocket = Ctor;
    return sockets;
  }

  it("close 1008이면 재연결을 시도하지 않는다", () => {
    const sockets = mockWs();

    const client = new WSClient("ws://test/ws");
    const authExpired = vi.fn();
    client.onAuthExpired(authExpired);
    client.connect();

    sockets[0].fireClose(WS_CLOSE_AUTH_EXPIRED);

    expect(authExpired).toHaveBeenCalledOnce();
    // 재연결 타이머가 잡히지 않는다 — 만료 세션 재시도 폭주 방지 (#134 완료 조건)
    vi.advanceTimersByTime(10_000);
    expect(sockets.length).toBe(1);
    client.disconnect();
  });

  it("다른 close code는 지수 백오프로 재연결한다", () => {
    const sockets = mockWs();

    const client = new WSClient("ws://test/ws");
    client.connect();

    sockets[0].fireClose(1006);

    vi.advanceTimersByTime(1000);
    expect(sockets.length).toBe(2);
    client.disconnect();
  });
});
