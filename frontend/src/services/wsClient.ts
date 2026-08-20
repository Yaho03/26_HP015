import type { WSMessage } from "../types/ws";

type MessageHandler = (msg: WSMessage) => void;
type StatusHandler = (connected: boolean) => void;
type AuthExpiredHandler = () => void;

const INITIAL_BACKOFF_MS = 1000;
const MAX_BACKOFF_MS = 30000;
const BACKOFF_MULTIPLIER = 2;

// 서버가 세션 없음/만료로 닫을 때 쓰는 close code (backend websocket.py 와 계약).
// 1008 은 재연결 대상이 아니다 — 로그인 상태 갱신으로 전환한다 (AUTH-4/#134).
export const WS_CLOSE_AUTH_EXPIRED = 1008;

export class WSClient {
  private url: string;
  private socket: WebSocket | null = null;
  private messageHandlers = new Set<MessageHandler>();
  private statusHandlers = new Set<StatusHandler>();
  private authExpiredHandlers = new Set<AuthExpiredHandler>();
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private backoffMs = INITIAL_BACKOFF_MS;
  private shouldReconnect = true;

  constructor(url: string) {
    this.url = url;
  }

  connect(): void {
    this.shouldReconnect = true;
    this.open();
  }

  private open(): void {
    try {
      this.socket = new WebSocket(this.url);
    } catch {
      this.scheduleReconnect();
      return;
    }
    this.socket.onopen = () => {
      this.backoffMs = INITIAL_BACKOFF_MS;
      this.notifyStatus(true);
    };
    this.socket.onclose = (ev: CloseEvent) => {
      this.notifyStatus(false);
      if (ev.code === WS_CLOSE_AUTH_EXPIRED) {
        // 만료 세션이 초당 수 번 재연결을 시도하는 폭주를 막는다 —
        // 인증 거부는 재시도로 해결되지 않는다.
        this.shouldReconnect = false;
        for (const h of this.authExpiredHandlers) h();
        return;
      }
      if (this.shouldReconnect) this.scheduleReconnect();
    };
    this.socket.onerror = () => {
      this.socket?.close();
    };
    this.socket.onmessage = (event) => this.handleMessage(event.data);
  }

  private handleMessage(raw: string): void {
    let parsed: WSMessage;
    try {
      parsed = JSON.parse(raw) as WSMessage;
    } catch {
      return;
    }
    for (const h of this.messageHandlers) {
      try {
        h(parsed);
      } catch {
        // handler 에러가 다른 handler 실행을 막지 않도록
      }
    }
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer) return;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.open();
      this.backoffMs = Math.min(this.backoffMs * BACKOFF_MULTIPLIER, MAX_BACKOFF_MS);
    }, this.backoffMs);
  }

  onMessage(handler: MessageHandler): () => void {
    this.messageHandlers.add(handler);
    return () => this.messageHandlers.delete(handler);
  }

  onStatusChange(handler: StatusHandler): () => void {
    this.statusHandlers.add(handler);
    return () => this.statusHandlers.delete(handler);
  }

  onAuthExpired(handler: AuthExpiredHandler): () => void {
    this.authExpiredHandlers.add(handler);
    return () => this.authExpiredHandlers.delete(handler);
  }

  private notifyStatus(connected: boolean): void {
    for (const h of this.statusHandlers) h(connected);
  }

  send(payload: unknown): void {
    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(payload));
    }
  }

  disconnect(): void {
    this.shouldReconnect = false;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.socket) {
      this.socket.onclose = null;
      this.socket.close();
      this.socket = null;
    }
    this.notifyStatus(false);
  }
}
