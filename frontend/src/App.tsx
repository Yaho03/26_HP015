import { useEffect, useState } from "react";
import { AlertModal } from "./components/AlertModal";
import { Header } from "./components/Header";
import { Sidebar, type ScreenKey } from "./components/Sidebar";
import { Toaster } from "./components/Toaster";
import { ChartScreen } from "./screens/ChartScreen";
import { LoginScreen } from "./screens/LoginScreen";
import { SettingsScreen } from "./screens/SettingsScreen";
import { TwinScreen } from "./screens/TwinScreen";
import { SafetyWorkspace, type SafetyWorkspaceView } from "./components/SafetyWorkspace";
import { useWebSocket } from "./hooks/useWebSocket";
import { useHealthPoll } from "./hooks/useHealthPoll";
import { useThresholds } from "./hooks/useThresholds";
import { useDashboardStore } from "./store/dashboardStore";
import { useAuthStore } from "./store/authStore";
import { fetchMe } from "./services/authApi";
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
    : "ws://localhost/ws");

type Theme = "dark" | "light";

function App() {
  const [screen, setScreen] = useState<ScreenKey>("monitoring");
  const [theme, setTheme] = useState<Theme>(
    () => (localStorage.getItem("hp015-theme") as Theme | null) ?? "dark",
  );
  const authStatus = useAuthStore((s) => s.status);
  const authUser = useAuthStore((s) => s.user);

  // 앱 부팅 시 세션 확인 — 200이면 저장된 세션으로 복귀, 401이면 LoginScreen
  // (AUTH-8). 미인증 상태에서는 어떤 화면도 데이터를 렌더링하지 않는다.
  useEffect(() => {
    if (authStatus !== "booting") return;
    fetchMe().catch(() => {
      // UnauthorizedError — fetchApi 가 이미 expire() 를 불렀다.
    });
  }, [authStatus]);

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
    // 임계값이 없으면 노드가 하나도 없어도 "정상"이라 말할 수 없다 (이슈 #165).
    // 시드를 unknown 으로 두면 낙상·서버 경보 같은 실제 위험은 rank 상 그대로 이긴다.
    let lv: AlertLevel = s.thresholds.length > 0 ? "normal" : "unknown";
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

  if (authStatus !== "authenticated") {
    return <LoginScreen />;
  }

  return (
    <div className="app">
      <Sidebar
        current={screen}
        onSelect={setScreen}
        active_alert_count={active_alert_count}
        connection={connection}
        overall_level={overall_level}
        userRole={authUser?.role}
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
