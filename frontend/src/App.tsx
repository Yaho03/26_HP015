import { useState } from "react";
import { AlertModal } from "./components/AlertModal";
import { Header } from "./components/Header";
import { Sidebar, type ScreenKey } from "./components/Sidebar";
import { Toaster } from "./components/Toaster";
import { ChartScreen } from "./screens/ChartScreen";
import { EventLogScreen } from "./screens/EventLogScreen";
import { MonitoringScreen } from "./screens/MonitoringScreen";
import { SettingsScreen } from "./screens/SettingsScreen";
import { TwinScreen } from "./screens/TwinScreen";
import { useWebSocket } from "./hooks/useWebSocket";
import { useDashboardStore } from "./store/dashboardStore";

const TITLES: Record<ScreenKey, string> = {
  monitoring: "Monitoring",
  twin: "3D Digital Twin",
  chart: "Time-series Chart",
  "event-log": "Event Log",
  settings: "Settings",
};

const WS_URL =
  (import.meta.env.VITE_WS_URL as string | undefined) ??
  `ws://${typeof window !== "undefined" ? window.location.hostname : "localhost"}:8000/ws`;

function App() {
  const [screen, setScreen] = useState<ScreenKey>("monitoring");
  const active_alert_count = useDashboardStore(
    (s) => Object.values(s.active_alerts).filter((a) => a.status === "active").length,
  );
  const connection = useDashboardStore((s) => s.connection_status);

  useWebSocket(WS_URL);

  return (
    <div className="app">
      <Sidebar
        current={screen}
        onSelect={setScreen}
        active_alert_count={active_alert_count}
        connection={connection}
      />
      <div className="app-main">
        <Header title={TITLES[screen]} />
        <main className="app-content">
          {screen === "monitoring" && <MonitoringScreen />}
          {screen === "twin" && <TwinScreen />}
          {screen === "chart" && <ChartScreen />}
          {screen === "event-log" && <EventLogScreen />}
          {screen === "settings" && <SettingsScreen />}
        </main>
      </div>
      <Toaster />
      <AlertModal />
    </div>
  );
}

export default App;
