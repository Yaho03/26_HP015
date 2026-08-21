import { useState } from "react";
import { EventLogScreen, type EventLogFilter } from "../screens/EventLogScreen";
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
  // Screen 1 ④ 의 행을 클릭하면 그 노드·등급으로 필터를 건 채 이력 화면이 열린다.
  // 필터 없이 넘기면 관제사가 방금 본 행을 20건 목록에서 다시 찾아야 한다.
  const [logFilter, setLogFilter] = useState<EventLogFilter>({});

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
          {activeView === "monitoring" ? (
            <MonitoringScreen
              onOpenEventLog={(filter) => {
                setLogFilter(filter);
                onViewChange("event-log");
              }}
            />
          ) : (
            <EventLogScreen initialFilter={logFilter} />
          )}
        </div>
      </div>
    </div>
  );
}
