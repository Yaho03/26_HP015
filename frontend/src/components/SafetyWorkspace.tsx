import { EventLogScreen } from "../screens/EventLogScreen";
import { MonitoringScreen } from "../screens/MonitoringScreen";
import { IconGauge, IconList } from "./icons";

export type SafetyWorkspaceView = "monitoring" | "event-log";

interface SafetyWorkspaceProps {
  activeView: SafetyWorkspaceView;
  onViewChange: (view: SafetyWorkspaceView) => void;
}

const TABS: { key: SafetyWorkspaceView; label: string; Icon: typeof IconGauge }[] = [
  { key: "monitoring", label: "실시간 모니터링", Icon: IconGauge },
  { key: "event-log", label: "사고 이력 로그", Icon: IconList },
];

export function SafetyWorkspace({ activeView, onViewChange }: SafetyWorkspaceProps) {
  return (
    <div className="safety-workspace">
      <nav className="safety-tabs" aria-label="안전 관리 화면">
        {TABS.map(({ key, label, Icon }) => (
          <button
            key={key}
            type="button"
            className={"safety-tab" + (activeView === key ? " safety-tab--active" : "")}
            aria-current={activeView === key ? "page" : undefined}
            onClick={() => onViewChange(key)}
          >
            <Icon size={15} />
            <span>{label}</span>
          </button>
        ))}
      </nav>

      {/* keyed view: CSS replaces only the workspace content, keeping the shell still */}
      <div className="safety-workspace__stage">
        <div key={activeView} className="safety-workspace__view">
          {activeView === "monitoring" ? <MonitoringScreen /> : <EventLogScreen />}
        </div>
      </div>
    </div>
  );
}
