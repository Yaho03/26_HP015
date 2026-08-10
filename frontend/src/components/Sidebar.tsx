import type { ConnectionStatus } from "../types";

export type ScreenKey = "monitoring" | "twin" | "chart" | "event-log" | "settings";

interface MenuItem {
  key: ScreenKey;
  label: string;
}

const MENU: MenuItem[] = [
  { key: "monitoring", label: "Monitoring" },
  { key: "twin", label: "3D Twin" },
  { key: "chart", label: "Chart" },
  { key: "event-log", label: "Event Log" },
  { key: "settings", label: "Settings" },
];

interface SidebarProps {
  current: ScreenKey;
  onSelect: (key: ScreenKey) => void;
  active_alert_count: number;
  connection: ConnectionStatus;
}

export function Sidebar({ current, onSelect, active_alert_count, connection }: SidebarProps) {
  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <span className="sidebar-brand-mark">HP015</span>
      </div>
      <nav className="sidebar-nav">
        {MENU.map((item) => (
          <button
            key={item.key}
            type="button"
            className={
              "sidebar-item" + (current === item.key ? " sidebar-item-active" : "")
            }
            onClick={() => onSelect(item.key)}
          >
            <span>{item.label}</span>
            {item.key === "monitoring" && active_alert_count > 0 && (
              <span className="sidebar-badge">{active_alert_count}</span>
            )}
          </button>
        ))}
      </nav>
      <div className="sidebar-status">
        <StatusDot label="BE" ok={connection.backend_connected} />
        <StatusDot label="MQTT" ok={connection.mqtt_connected} />
        <StatusDot label="WS" ok={connection.websocket_connected} />
      </div>
    </aside>
  );
}

function StatusDot({ label, ok }: { label: string; ok: boolean }) {
  return (
    <div className="status-dot">
      <span className={"status-dot-mark " + (ok ? "status-ok" : "status-bad")} />
      <span className="status-dot-label">{label}</span>
    </div>
  );
}
