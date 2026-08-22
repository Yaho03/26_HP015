import { useCallback, useEffect, useState } from "react";
import {
  fetchDemoScenarios,
  fetchDemoStatus,
  runDemoScenario,
  stopDemoScenario,
  type DemoRunState,
  type DemoScenario,
} from "../services/api";

// 09_DEMO_SCENARIOS 4절 — 안전한 데이터 주입. 실제 유해 가스를 쓰지 않고
// 시나리오를 소프트웨어로 주입한다. 주입된 값은 source_mode="simulation" 이라
// 대시보드에서 SIM 배지로 실제 센서와 구분된다 (4.4 주의사항).

const POLL_MS = 3000;

export function DemoControlPanel() {
  const [scenarios, setScenarios] = useState<DemoScenario[] | null>(null);
  const [state, setState] = useState<DemoRunState | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // 404(기능 꺼짐)와 통신 실패를 구분한다. 둘 다 "비활성"으로 보이면 CORS·서버
  // 다운 같은 진짜 고장을 정상 상태로 착각하게 된다.
  const [unreachable, setUnreachable] = useState(false);

  const load = useCallback(async () => {
    const list = await fetchDemoScenarios();
    setScenarios(list);
    setState(list ? await fetchDemoStatus() : null);
  }, []);

  useEffect(() => {
    load()
      .catch((e) => {
        setUnreachable(true);
        setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => setLoading(false));
  }, [load]);

  // 자식 프로세스가 스스로 끝나면(duration 소진) 화면도 따라가야 한다.
  useEffect(() => {
    if (!scenarios) return;
    const id = setInterval(() => {
      fetchDemoStatus()
        .then(setState)
        .catch(() => undefined);
    }, POLL_MS);
    return () => clearInterval(id);
  }, [scenarios]);

  const act = async (label: string, fn: () => Promise<DemoRunState>) => {
    setBusy(label);
    setError(null);
    try {
      setState(await fn());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  if (loading) return <p className="settings-note">데모 제어 상태를 불러오는 중…</p>;

  if (unreachable) {
    return (
      <section className="panel settings-panel">
        <h3 className="settings-section-title">데모 제어</h3>
        <p className="settings-error">
          백엔드에 연결하지 못했다. 서버가 떠 있는지, CORS 허용 오리진 (<code>CORS_ORIGINS</code>)에
          이 주소가 포함돼 있는지 확인할 것.
          {error ? ` — ${error}` : ""}
        </p>
      </section>
    );
  }

  // 백엔드가 기능을 꺼둔 상태. 에러가 아니라 정상적인 기본값이다.
  if (!scenarios) {
    return (
      <section className="panel settings-panel">
        <h3 className="settings-section-title">데모 제어</h3>
        <p className="settings-notice">
          <strong>비활성</strong>
          <span>
            시뮬레이션 값을 원격 주입하는 기능이라 기본으로 꺼져 있다. 인증이 붙기 전 (#116)
            열어두면 임의의 값이 안전 시스템에 들어올 수 있다. 시연 환경에서만 백엔드 환경변수{" "}
            <code>DEMO_CONTROL_ENABLED=true</code> 로 켠다.
          </span>
        </p>
      </section>
    );
  }

  const running = state?.running ? state : null;

  return (
    <section className="panel settings-panel">
      <div className="settings-section-head">
        <h3 className="settings-section-title">데모 제어</h3>
        <span className="settings-section-note">
          주입된 값은 <strong>SIM</strong> 배지로 실제 센서와 구분된다
        </span>
      </div>

      <p className="settings-notice">
        <strong>주의</strong>
        <span>주입 중에는 화면의 수치가 실제 측정값이 아니다. 시연이 끝나면 반드시 중지한다.</span>
      </p>

      {error && <p className="settings-error">{error}</p>}

      <div className={"demo-running" + (running ? " demo-running--active" : "")}>
        <span className="demo-running__label">RUNNING</span>
        {running ? (
          <>
            <strong>{running.scenario}</strong>
            <span className="demo-running__nodes">{running.node_ids.join(", ")}</span>
            <button
              type="button"
              className="chart-action chart-action--primary"
              disabled={busy !== null}
              onClick={() => act("stop", stopDemoScenario)}
            >
              {busy === "stop" ? "중지 중…" : "중지"}
            </button>
          </>
        ) : (
          <span className="pending">실행 중인 시나리오 없음</span>
        )}
      </div>

      <ul className="demo-list">
        {scenarios.map((s) => {
          const active = running?.scenario === s.name;
          return (
            <li key={s.name} className={"demo-item" + (active ? " demo-item--active" : "")}>
              <div className="demo-item__text">
                <span className="demo-item__label">
                  {s.label}
                  <code>{s.name}</code>
                </span>
                <span className="demo-item__desc">{s.description}</span>
                <span className="demo-item__meta">
                  {s.default_nodes.join(", ")}
                  {s.supports_duration && s.default_duration_s
                    ? ` · ${s.default_duration_s}초`
                    : " · 고정 길이"}
                </span>
              </div>
              <button
                type="button"
                className="chart-action"
                disabled={busy !== null}
                onClick={() => act(s.name, () => runDemoScenario(s.name))}
              >
                {busy === s.name ? "시작 중…" : active ? "다시 실행" : "실행"}
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
