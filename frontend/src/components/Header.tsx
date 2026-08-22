import { useEffect, useState } from "react";
import type { AlertLevel, ConnectionStatus } from "../types";
import { levelLabel } from "../utils/alerts";
import { IconMoon, IconSun } from "./icons";

interface HeaderProps {
  title: string;
  overall_level: AlertLevel;
  connection: ConnectionStatus;
  theme: "dark" | "light";
  onToggleTheme: () => void;
}

export function Header({ title, overall_level, connection, theme, onToggleTheme }: HeaderProps) {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  const connState = connection.websocket_connected ? "connected" : "disconnected";
  const connLabel = connection.websocket_connected ? "연결됨" : "연결 끊김";

  return (
    <header className="topbar">
      <h1 className="topbar-title">{title}</h1>
      <div className="topbar-spacer" />

      <div className="readout">
        <span className="readout-cell">
          <span className="legend">전체 위험</span>
          <span className={"readout-value is-lv is-" + overall_level}>
            <span className="readout-mark" />
            {levelLabel(overall_level)}
          </span>
        </span>
        <span className="readout-cell">
          <span className="legend">링크</span>
          <span
            className={
              "readout-value is-lv " +
              (connState === "connected" ? "is-normal" : "is-level3_critical")
            }
          >
            <span className="readout-mark" />
            {connLabel}
          </span>
        </span>
        <span className="readout-cell">
          <span className="legend">UTC</span>
          <span className="readout-value">
            {now.toLocaleTimeString("en-GB", { hour12: false })}
          </span>
        </span>
      </div>

      <button
        type="button"
        className="theme-toggle"
        onClick={onToggleTheme}
        title={theme === "dark" ? "밝은 모드로" : "어두운 모드로"}
        aria-label="테마 전환"
      >
        {theme === "dark" ? <IconSun size={15} /> : <IconMoon size={15} />}
      </button>
    </header>
  );
}
