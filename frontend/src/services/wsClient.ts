import type { WSMessage } from "../types/ws";

type MessageHandler = (msg: WSMessage) => void;
type StatusHandler = (connected: boolean) => void;

const INITIAL_BACKOFF_MS = 1000;
const MAX_BACKOFF_MS = 30000;
const BACKOFF_MULTIPLIER = 2;

export class WSClient {
  private url: string;
  private socket: WebSocket | null = null;
  private messageHandlers = new Set<MessageHandler>();
  private statusHandlers = new Set<StatusHandler>();
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
    this.socket.onclose = () => {
      this.notifyStatus(false);
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
