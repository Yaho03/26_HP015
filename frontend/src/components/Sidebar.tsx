import type { ComponentType } from "react";
import type { AlertLevel, ConnectionStatus } from "../types";
import type { Role } from "../store/authStore";
import { hasRole } from "../store/authStore";
import { IconChart, IconClock, IconCube, IconGauge, IconList, IconSettings } from "./icons";

export type ScreenKey =
  | "monitoring"
  | "twin"
  | "chart"
  | "event-log"
  | "exposure"
  | "settings";

interface MenuItem {
  key: ScreenKey;
  label: string;
  Icon: ComponentType<{ size?: number | string }>;
  minRole?: Role;
}

const MENU: MenuItem[] = [
  { key: "monitoring", label: "모니터링", Icon: IconGauge },
  { key: "twin", label: "3D 트윈", Icon: IconCube },
  { key: "chart", label: "차트", Icon: IconChart },
  { key: "event-log", label: "이벤트 로그", Icon: IconList },
  // 시계 아이콘을 쓰는 이유 — 노출량은 농도가 아니라 농도 × **시간**이다.
  { key: "exposure", label: "노출량", Icon: IconClock },
  { key: "settings", label: "설정", Icon: IconSettings },
];

interface SidebarProps {
  current: ScreenKey;
  onSelect: (key: ScreenKey) => void;
  active_alert_count: number;
  connection: ConnectionStatus;
  overall_level: AlertLevel;
  userRole?: Role;
}

export function Sidebar({
  current,
  onSelect,
  active_alert_count,
  connection,
  overall_level,
  userRole,
}: SidebarProps) {
  const critical = overall_level === "level3_critical";
  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <span className="sidebar-brand-mark">HP015</span>
        <span className="sidebar-brand-sub">console</span>
      </div>
      <nav className="sidebar-nav">
        {MENU.map(({ key, label, Icon, minRole }) => {
          // 역할 게이팅 — 서버 권한이 정본, 이 필터는 UX 다 (AUTH-8).
          if (minRole && !hasRole(userRole, minRole)) return null;
          return (
          <button
            key={key}
            type="button"
            aria-label={label}
            className={
              "sidebar-item" +
              (current === key ? " sidebar-item-active" : "") +
              (critical && key === "monitoring" ? " sidebar-item-critical" : "")
            }
            onClick={() => onSelect(key)}
          >
            <span className="sidebar-item-icon">
              <Icon size={16} />
            </span>
            <span className="sidebar-item-label">{label}</span>
            {key === "monitoring" && active_alert_count > 0 && (
              <span className="sidebar-badge">{active_alert_count}</span>
            )}
          </button>
          );
        })}
      </nav>
      <div className="sidebar-status">
        <StatusDot label="BE" ok={connection.backend_connected} />
        <StatusDot label="MQTT" ok={connection.mqtt_connected} />
        <StatusDot label="WS" ok={connection.websocket_connected} />
      </div>
    </aside>
  );
}

/** Connection state is never colour alone (PRODUCT.md 접근성): the mark, the
 *  word, and the aria-label all carry it. */
function StatusDot({ label, ok }: { label: string; ok: boolean }) {
  const state = ok ? "연결됨" : "끊김";
  return (
    <div className="status-dot" aria-label={`${label} ${state}`}>
      <span className={"status-dot-mark " + (ok ? "status-ok" : "status-bad")} aria-hidden="true" />
      <span className="status-dot-label">{label}</span>
      <span className={"status-dot-state " + (ok ? "status-ok-text" : "status-bad-text")}>{state}</span>
    </div>
  );
}
