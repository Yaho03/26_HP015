import { useCallback, useEffect, useMemo, useState } from "react";
import { DemoControlPanel } from "../components/DemoControlPanel";
import { EvacuationTopologyPanel } from "../components/EvacuationTopologyPanel";
import { WorkerRoster } from "../components/WorkerRoster";
import { UserAdmin } from "../components/UserAdmin";
import { hasRole, useAuthStore, type Role } from "../store/authStore";
import { useThresholds } from "../hooks/useThresholds";
import {
  fetchHealth,
  fetchMetrics,
  fetchThresholds,
  updateThreshold,
  type HealthStatus,
  type Threshold,
  type ThresholdDirection,
  type ThresholdLevel,
} from "../services/api";

type SettingsTab = "thresholds" | "workers" | "hazards" | "topology" | "system" | "demo" | "users";
type RowStatus = { key: string; tone: "success" | "error"; message: string } | null;

interface MetricMeta {
  key: string;
  label: string;
  unit: string;
  description: string;
}

interface ThresholdDraft {
  direction: ThresholdDirection;
  enter_threshold: string;
  exit_threshold: string;
  enter_for_ms: string;
  exit_for_ms: string;
}

const METRICS: MetricMeta[] = [
  { key: "co2_ppm", label: "CO₂", unit: "ppm", description: "이산화탄소" },
  { key: "co_ppm", label: "CO", unit: "ppm", description: "일산화탄소" },
  { key: "h2s_ppm", label: "H₂S", unit: "ppm", description: "황화수소" },
  { key: "temperature_c", label: "온도", unit: "°C", description: "환경 온도" },
  { key: "o2_low", label: "O₂ 저농도", unit: "%", description: "산소 결핍" },
  { key: "o2_high", label: "O₂ 고농도", unit: "%", description: "산소 과잉" },
];

const LEVELS: { key: ThresholdLevel; label: string }[] = [
  { key: "level1_caution", label: "L1 주의" },
  { key: "level2_warning", label: "L2 경고" },
  { key: "level3_critical", label: "L3 위험" },
];

const TAB_ITEMS: { key: SettingsTab; label: string; hint: string; minRole?: Role }[] = [
  { key: "thresholds", label: "임계값", hint: "ALERT RULES" },
  // 작업자 명부 변경은 supervisor 이상 (FR-606). 탭 자체를 숨긴다 —
  // 서버가 403 으로 막지만 권한 없는 사용자에게 메뉴를 보여줄 이유가 없다.
  { key: "workers", label: "작업자", hint: "WORKER REGISTRY", minRole: "supervisor" },
  { key: "hazards", label: "위험 구역", hint: "ZONE PROFILE" },
  { key: "topology", label: "통행 구조", hint: "EGRESS TOPOLOGY" },
  { key: "system", label: "시스템", hint: "HEALTH & METRICS" },
  { key: "users", label: "사용자", hint: "ACCOUNTS", minRole: "admin" },
  { key: "demo", label: "데모 제어", hint: "SCENARIO INJECTION", minRole: "admin" },
];

function rowKey(metric: string, level: ThresholdLevel): string {
  return `${metric}:${level}`;
}

function toDraft(threshold: Threshold): ThresholdDraft {
  return {
    direction: threshold.direction,
    enter_threshold: String(threshold.enter_threshold),
    exit_threshold: String(threshold.exit_threshold),
    enter_for_ms: String(threshold.enter_for_ms),
    exit_for_ms: String(threshold.exit_for_ms),
  };
}

function formatUpdatedAt(value: string | null): string {
  if (!value) return "서버 기록 없음";
  return new Date(value).toLocaleString("ko-KR", { hour12: false });
}

export function SettingsScreen() {
  const [tab, setTab] = useState<SettingsTab>("thresholds");
  const userRole = useAuthStore((s) => s.user?.role);
  const { reload: reloadThresholds } = useThresholds();
  const [thresholds, setThresholds] = useState<Threshold[]>([]);
  const [drafts, setDrafts] = useState<Record<string, ThresholdDraft>>({});
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [metrics, setMetrics] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [rowStatus, setRowStatus] = useState<RowStatus>(null);
  const [savingKey, setSavingKey] = useState<string | null>(null);
  const [hazardRadius, setHazardRadius] = useState("0.5");
  const [hazardLevel, setHazardLevel] = useState<ThresholdLevel>("level2_warning");

  const loadSettings = useCallback(async () => {
    setRefreshing(true);
    setError(null);
    const [thresholdResult, healthResult, metricsResult] = await Promise.allSettled([
      fetchThresholds(),
      fetchHealth(),
      fetchMetrics(),
    ]);

    if (thresholdResult.status === "fulfilled") {
      setThresholds(thresholdResult.value);
      setDrafts(
        Object.fromEntries(
          thresholdResult.value.map((threshold) => [
            rowKey(threshold.metric, threshold.level),
            toDraft(threshold),
          ]),
        ),
      );
    } else {
      setError("임계값을 불러오지 못했습니다. 백엔드 연결 상태를 확인하세요.");
    }
    if (healthResult.status === "fulfilled") setHealth(healthResult.value);
    if (metricsResult.status === "fulfilled") setMetrics(metricsResult.value);
    setLoading(false);
    setRefreshing(false);
  }, []);

  useEffect(() => {
    void loadSettings();
  }, [loadSettings]);

  const thresholdGroups = useMemo(
    () =>
      METRICS.map((metric) => ({
        metric,
        rows: LEVELS.map((level) =>
          thresholds.find(
            (threshold) => threshold.metric === metric.key && threshold.level === level.key,
          ),
        ).filter((threshold): threshold is Threshold => threshold !== undefined),
      })).filter(({ rows }) => rows.length > 0),
    [thresholds],
  );

  function updateDraft(
    metric: string,
    level: ThresholdLevel,
    field: keyof ThresholdDraft,
    value: string,
  ) {
    const key = rowKey(metric, level);
    setDrafts((current) => ({ ...current, [key]: { ...current[key], [field]: value } }));
    setRowStatus(null);
  }

  async function saveRow(threshold: Threshold) {
    const key = rowKey(threshold.metric, threshold.level);
    const draft = drafts[key];
    if (!draft) return;
    const enterThreshold = Number(draft.enter_threshold);
    const exitThreshold = Number(draft.exit_threshold);
    const enterForMs = Number(draft.enter_for_ms);
    const exitForMs = Number(draft.exit_for_ms);
    if (
      !draft.enter_threshold.trim() ||
      !draft.exit_threshold.trim() ||
      !Number.isFinite(enterThreshold) ||
      !Number.isFinite(exitThreshold) ||
      !Number.isInteger(enterForMs) ||
      !Number.isInteger(exitForMs) ||
      enterForMs < 0 ||
      exitForMs < 0
    ) {
      setRowStatus({ key, tone: "error", message: "값과 지속 시간(ms)을 확인하세요." });
      return;
    }

    setSavingKey(key);
    setRowStatus(null);
    try {
      const saved = await updateThreshold(threshold.metric, threshold.level, {
        direction: draft.direction,
        enter_threshold: enterThreshold,
        exit_threshold: exitThreshold,
        enter_for_ms: enterForMs,
        exit_for_ms: exitForMs,
      });
      setThresholds((current) =>
        current.map((item) => (rowKey(item.metric, item.level) === key ? saved : item)),
      );
      setDrafts((current) => ({ ...current, [key]: toDraft(saved) }));
      // 대시보드 등급 판정도 새 값을 쓰게 한다 (이슈 #114). 이게 없으면 경보
      // 엔진만 바뀌고 화면 색은 옛 기준으로 남는다.
      void reloadThresholds();
      setRowStatus({ key, tone: "success", message: "저장됨 · 경보 엔진과 대시보드에 반영" });
    } catch {
      setRowStatus({ key, tone: "error", message: "저장 실패 · 백엔드 연결을 확인하세요." });
    } finally {
      setSavingKey(null);
    }
  }

  function resetRow(threshold: Threshold) {
    const key = rowKey(threshold.metric, threshold.level);
    setDrafts((current) => ({ ...current, [key]: toDraft(threshold) }));
    setRowStatus(null);
  }

  return (
    <div className="settings-screen">
      <div className="settings-heading">
        <div>
          <p className="settings-kicker">CONFIGURE / CONTROL PLANE</p>
          <h2 className="settings-title">운영 설정</h2>
          <p className="settings-subtitle">경보 판정 기준과 시스템 상태를 확인합니다.</p>
        </div>
        <div className="settings-heading-actions">
          <span
            className={
              health?.status === "ok" ? "settings-health settings-health--ok" : "settings-health"
            }
          >
            <span className="settings-health-dot" />
            {health?.status === "ok" ? "BACKEND READY" : "BACKEND CHECK"}
          </span>
          <button
            type="button"
            className="settings-refresh"
            onClick={() => void loadSettings()}
            disabled={refreshing}
          >
            {refreshing ? "확인 중…" : "↻ 새로고침"}
          </button>
        </div>
      </div>

      <div className="settings-tabs" role="tablist" aria-label="설정 메뉴">
        {TAB_ITEMS.map((item) => {
          if (item.minRole && !hasRole(userRole, item.minRole)) return null;
          return (
            <button
              key={item.key}
              type="button"
              role="tab"
              aria-selected={tab === item.key}
              className={"settings-tab" + (tab === item.key ? " settings-tab--active" : "")}
              onClick={() => setTab(item.key)}
            >
              <span className="settings-tab-hint">{item.hint}</span>
              <span>{item.label}</span>
            </button>
          );
        })}
      </div>

      {tab === "topology" && <EvacuationTopologyPanel />}

      {tab === "thresholds" && (
        <section className="settings-section" aria-labelledby="thresholds-title">
          <div className="settings-section-heading">
            <div>
              <p className="settings-section-kicker">FR-201 / SERVER-MANAGED</p>
              <h3 id="thresholds-title">임계값 정책</h3>
            </div>
            <span className="settings-source">DB SOURCE · {thresholds.length} ROWS</span>
          </div>
          <div className="settings-notice settings-notice--info">
            <strong>Hysteresis 적용</strong>
            <span>진입값과 해제값을 분리해 경보가 임계값 부근에서 반복되지 않도록 합니다.</span>
          </div>
          {loading && <p className="settings-state">서버 임계값을 불러오는 중입니다…</p>}
          {!loading && error && <p className="settings-state settings-state--error">{error}</p>}
          {!loading && !error && thresholdGroups.length === 0 && (
            <p className="settings-state">
              표시할 임계값이 없습니다. 백엔드 초기 데이터를 확인하세요.
            </p>
          )}
          <div className="threshold-groups">
            {thresholdGroups.map(({ metric, rows }) => (
              <article className="threshold-group" key={metric.key}>
                <header className="threshold-group-head">
                  <div>
                    <h4>
                      {metric.label} <span>{metric.description}</span>
                    </h4>
                    <p>
                      판정 방향:{" "}
                      {rows[0]?.direction === "below" ? "기준값 이하 진입" : "기준값 이상 진입"}
                    </p>
                  </div>
                  <span className="threshold-unit">{metric.unit}</span>
                </header>
                <div className="threshold-table-wrap">
                  <table className="threshold-table">
                    <thead>
                      <tr>
                        <th scope="col">등급</th>
                        <th scope="col">진입값</th>
                        <th scope="col">진입 지속</th>
                        <th scope="col">해제값</th>
                        <th scope="col">해제 지속</th>
                        <th scope="col">
                          <span className="sr-only">행 작업</span>
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((threshold) => {
                        const key = rowKey(threshold.metric, threshold.level);
                        const draft = drafts[key] ?? toDraft(threshold);
                        const status = rowStatus?.key === key ? rowStatus : null;
                        return (
                          <tr key={key}>
                            <th scope="row">
                              <span
                                className={`threshold-level threshold-level--${threshold.level}`}
                              >
                                {LEVELS.find((level) => level.key === threshold.level)?.label}
                              </span>
                            </th>
                            <td>
                              <input
                                aria-label={`${metric.label} ${threshold.level} 진입값`}
                                type="number"
                                value={draft.enter_threshold}
                                onChange={(event) =>
                                  updateDraft(
                                    threshold.metric,
                                    threshold.level,
                                    "enter_threshold",
                                    event.target.value,
                                  )
                                }
                              />
                            </td>
                            <td>
                              <input
                                aria-label={`${metric.label} ${threshold.level} 진입 지속 시간`}
                                type="number"
                                min="0"
                                step="1"
                                value={draft.enter_for_ms}
                                onChange={(event) =>
                                  updateDraft(
                                    threshold.metric,
                                    threshold.level,
                                    "enter_for_ms",
                                    event.target.value,
                                  )
                                }
                              />
                              <span>ms</span>
                            </td>
                            <td>
                              <input
                                aria-label={`${metric.label} ${threshold.level} 해제값`}
                                type="number"
                                value={draft.exit_threshold}
                                onChange={(event) =>
                                  updateDraft(
                                    threshold.metric,
                                    threshold.level,
                                    "exit_threshold",
                                    event.target.value,
                                  )
                                }
                              />
                            </td>
                            <td>
                              <input
                                aria-label={`${metric.label} ${threshold.level} 해제 지속 시간`}
                                type="number"
                                min="0"
                                step="1"
                                value={draft.exit_for_ms}
                                onChange={(event) =>
                                  updateDraft(
                                    threshold.metric,
                                    threshold.level,
                                    "exit_for_ms",
                                    event.target.value,
                                  )
                                }
                              />
                              <span>ms</span>
                            </td>
                            <td className="threshold-actions">
                              <button
                                type="button"
                                className="threshold-save"
                                onClick={() => void saveRow(threshold)}
                                disabled={savingKey === key}
                              >
                                {savingKey === key ? "…" : "저장"}
                              </button>
                              <button
                                type="button"
                                className="threshold-reset"
                                onClick={() => resetRow(threshold)}
                                disabled={savingKey === key}
                              >
                                초기화
                              </button>
                              {status && (
                                <span
                                  className={`threshold-status threshold-status--${status.tone}`}
                                >
                                  {status.message}
                                </span>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
                <p className="threshold-updated">
                  마지막 변경: {formatUpdatedAt(rows[0]?.updated_at ?? null)}
                </p>
              </article>
            ))}
          </div>
        </section>
      )}

      {tab === "hazards" && (
        <section className="settings-section" aria-labelledby="hazards-title">
          <div className="settings-section-heading">
            <div>
              <p className="settings-section-kicker">TWIN / ZONE PROFILE</p>
              <h3 id="hazards-title">위험 구역 표시</h3>
            </div>
            <span className="settings-source">VISUAL PROFILE</span>
          </div>
          <div className="settings-notice settings-notice--warning">
            <strong>서버 저장 API 연결 대기</strong>
            <span>아래 값은 화면 미리보기용입니다. 운영 경보 판정에 반영되지 않습니다.</span>
          </div>
          <div className="hazard-settings-grid">
            <label className="settings-field">
              <span>위험 구역 반경</span>
              <div className="settings-input-with-unit">
                <input
                  type="number"
                  min="0.1"
                  max="2"
                  step="0.1"
                  value={hazardRadius}
                  onChange={(event) => setHazardRadius(event.target.value)}
                />
                <b>m</b>
              </div>
              <small>0.1m ~ 2.0m · 기본 0.5m</small>
            </label>
            <label className="settings-field">
              <span>트리거 등급</span>
              <select
                value={hazardLevel}
                onChange={(event) => setHazardLevel(event.target.value as ThresholdLevel)}
              >
                <option value="level2_warning">Level 2 · 경고</option>
                <option value="level3_critical">Level 3 · 위험</option>
              </select>
              <small>디지털 트윈에 위험 구역을 표시할 기준입니다.</small>
            </label>
          </div>
          <div className="hazard-preview">
            <div className="hazard-preview-ring">
              <span>{hazardRadius}m</span>
            </div>
            <div>
              <strong>
                {hazardLevel === "level2_warning" ? "Level 2 경고" : "Level 3 위험"} 구역
              </strong>
              <p>활성 센서 노드를 중심으로 표시되는 원형 범위</p>
            </div>
          </div>
        </section>
      )}

      {tab === "system" && (
        <section className="settings-section" aria-labelledby="system-title">
          <div className="settings-section-heading">
            <div>
              <p className="settings-section-kicker">OBSERVABILITY / READ ONLY</p>
              <h3 id="system-title">시스템 상태</h3>
            </div>
            <span className="settings-source">LIVE SNAPSHOT</span>
          </div>
          <div className="system-status-grid">
            <div className="system-status-item">
              <span>Backend</span>
              <strong className={health?.status === "ok" ? "is-ok" : "is-bad"}>
                {health?.status === "ok" ? "정상" : "확인 필요"}
              </strong>
            </div>
            <div className="system-status-item">
              <span>MQTT</span>
              <strong className={health?.mqtt.connected ? "is-ok" : "is-bad"}>
                {health?.mqtt.connected ? "연결됨" : "연결 끊김"}
              </strong>
            </div>
            <div className="system-status-item">
              <span>Database</span>
              <strong className={health?.db.pool_initialized ? "is-ok" : "is-bad"}>
                {health?.db.pool_initialized ? "초기화됨" : "대기 중"}
              </strong>
            </div>
          </div>
          <div className="system-metrics">
            {[
              ["messages_processed", "처리 메시지"],
              ["alerts_published", "발행 경보"],
              ["alerts_resolved", "해제 경보"],
              ["messages_dropped_invalid", "무효 폐기"],
            ].map(([key, label]) => (
              <div className="system-metric" key={key}>
                <span>{label}</span>
                <strong>{metrics[key] ?? "—"}</strong>
              </div>
            ))}
          </div>
          <dl className="system-details">
            <div>
              <dt>프론트엔드</dt>
              <dd>{window.location.host}</dd>
            </div>
            <div>
              <dt>임계값 데이터</dt>
              <dd>GET /api/thresholds · PUT /api/thresholds/:metric/:level</dd>
            </div>
            <div>
              <dt>스냅샷 시각</dt>
              <dd>{new Date().toLocaleString("ko-KR", { hour12: false })}</dd>
            </div>
          </dl>
        </section>
      )}

      {tab === "workers" && hasRole(userRole, "supervisor") && <WorkerRoster />}
      {tab === "users" && hasRole(userRole, "admin") && <UserAdmin />}

      {tab === "demo" && <DemoControlPanel />}
    </div>
  );
}
