import { useEffect, useState } from "react";
import { AlertModal } from "./components/AlertModal";
import { Header } from "./components/Header";
import { Sidebar, type ScreenKey } from "./components/Sidebar";
import { Toaster } from "./components/Toaster";
import { ChartScreen } from "./screens/ChartScreen";
import { SettingsScreen } from "./screens/SettingsScreen";
import { TwinScreen } from "./screens/TwinScreen";
import { SafetyWorkspace, type SafetyWorkspaceView } from "./components/SafetyWorkspace";
import { useWebSocket } from "./hooks/useWebSocket";
import { useHealthPoll } from "./hooks/useHealthPoll";
import { useThresholds } from "./hooks/useThresholds";
import { useDashboardStore } from "./store/dashboardStore";
import { classifyO2High, classifyO2Low, maxLevel, nodeAlertLevel } from "./utils/alerts";
import type { AlertLevel } from "./types";

const TITLES: Record<ScreenKey, string> = {
  monitoring: "실시간 모니터링",
  twin: "3D 디지털 트윈",
  chart: "시계열 차트",
  "event-log": "이벤트 로그",
  settings: "설정",
};

// 상대 경로 기본값 — 현재 오리진의 /ws로 접속 (nginx/vite dev proxy가 백엔드로
// 프록시). :8000 직접 접속은 CORS/배포 환경에서 실패하므로 쓰지 않는다 (이슈 #105).
const WS_URL =
  (import.meta.env.VITE_WS_URL as string | undefined) ??
  (typeof window !== "undefined"
    ? `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}/ws`
    : "ws://localhost:8000/ws");

type Theme = "dark" | "light";

function App() {
  const [screen, setScreen] = useState<ScreenKey>("monitoring");
  const [theme, setTheme] = useState<Theme>(
    () => (localStorage.getItem("hp015-theme") as Theme | null) ?? "dark",
  );

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("hp015-theme", theme);
  }, [theme]);

  const active_alert_count = useDashboardStore(
    (s) => Object.values(s.active_alerts).filter((a) => a.status === "active").length,
  );
  const connection = useDashboardStore((s) => s.connection_status);

  // Overall risk (TopBar pill + SideNav critical blink) — spec 10_UI_FLOW §2.1.
  const overall_level = useDashboardStore((s): AlertLevel => {
    let lv: AlertLevel = "normal";
    for (const n of Object.values(s.sensor_nodes)) lv = maxLevel(lv, nodeAlertLevel(n));
    const w = s.wearable;
    if (w) {
      if (w.fall_detected) lv = maxLevel(lv, "level3_critical");
      if (w.o2_pct !== null)
        lv = maxLevel(lv, maxLevel(classifyO2Low(w.o2_pct), classifyO2High(w.o2_pct)));
    }
    return lv;
  });

  useWebSocket(WS_URL);
  useHealthPoll();
  useThresholds();

  return (
    <div className="app">
      <Sidebar
        current={screen}
        onSelect={setScreen}
        active_alert_count={active_alert_count}
        connection={connection}
        overall_level={overall_level}
      />
      <div className="app-main">
        <Header
          title={TITLES[screen]}
          overall_level={overall_level}
          connection={connection}
          theme={theme}
          onToggleTheme={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
        />
        <main className="app-content">
          {(screen === "monitoring" || screen === "event-log") && (
            <SafetyWorkspace
              activeView={screen as SafetyWorkspaceView}
              onViewChange={setScreen}
            />
          )}
          {screen === "twin" && <TwinScreen />}
          {screen === "chart" && <ChartScreen />}
          {screen === "settings" && <SettingsScreen />}
        </main>
      </div>
      <Toaster />
      <AlertModal />
    </div>
  );
}

export default App;
