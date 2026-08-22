import { ExposureGauge } from "../components/ExposureGauge";
import { IconWarning } from "../components/icons";
import { useExposure, useExposureBootstrap } from "../hooks/useExposure";
import {
  EXPOSURE_MOCK_STATES,
  MOCK_NODE_ID,
  useExposureMock,
  type ExposureMockState,
} from "../mocks/exposure";
import {
  EXPOSURE_DISCLAIMER,
  EXPOSURE_DOSE_METRICS,
  O2_UNAVAILABLE_LABEL,
  TRUST_HINT,
  TRUST_LABEL,
  UNAVAILABLE_HINT,
  UNAVAILABLE_LABEL,
  doseLevel,
  formatDuration,
  hasActiveDose,
} from "../utils/exposure";
import type { ExposureDoseMetric, ExposureO2Metric } from "../types/ws";

/**
 * 시각 표기는 로컬 시간 HH:MM:SS.
 *
 * ko-KR 로케일은 "0시 10분 36초"로 풀어 쓴다. 관제 화면에서는 자릿수가 고정된
 * 숫자여야 세로로 훑을 때 눈이 미끄러지지 않는다. Header 의 UTC 시계와 같은
 * en-GB 를 쓰는 이유다.
 */
function clock(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleTimeString("en-GB", { hour12: false });
}

function num(value: number | null | undefined, digits: number): string {
  return value == null ? "—" : value.toFixed(digits);
}

/**
 * 작업자 누적 노출량 상세.
 *
 * "누적 노출량"이라고 쓴다. "몸에 축적된 양"이라고 쓰지 않는다 — 이 시스템은
 * 생리학적 체내 축적을 측정하지 않는다. 공기 중 농도를 시간에 대해 적분한
 * 값이고, 둘은 다른 것이다 (§7 한계 #7).
 */
export function ExposureScreen() {
  useExposureBootstrap();
  const { exposure, is_mock } = useExposure(MOCK_NODE_ID);

  return (
    <div className="exposure">
      <MockControls />

      {!exposure ? (
        <p className="exposure__empty">
          노출량 데이터가 없습니다. 웨어러블이 배정되지 않았거나 적산이 시작되지 않았습니다.
        </p>
      ) : (
        <>
          <header className="exposure__head">
            <div className="exposure__who">
              <strong>{exposure.worker_name}</strong>
              <em>{exposure.node_id}</em>
              {is_mock && <span className="exposure__mock-badge">MOCK</span>}
            </div>
            <dl className="exposure__window">
              <div>
                <dt>윈도우 시작</dt>
                <dd>{clock(exposure.window_start)}</dd>
              </div>
              <div>
                <dt>경과</dt>
                <dd>{formatDuration(exposure.elapsed_s)}</dd>
              </div>
              <div>
                <dt>적산</dt>
                <dd>{formatDuration(exposure.accumulated_s)}</dd>
              </div>
              <div>
                <dt>신뢰도</dt>
                <dd
                  className={"exposure__trust exposure__trust--" + exposure.trust_level}
                  title={TRUST_HINT[exposure.trust_level]}
                >
                  {TRUST_LABEL[exposure.trust_level]}
                </dd>
              </div>
            </dl>
          </header>

          {/* 공백은 곧 과소평가다. 이 사실을 숨기면 화면의 숫자가 상한처럼 읽힌다. */}
          {exposure.data_gap_s > 0 && (
            <p className="exposure__gap" role="status">
              <IconWarning size={14} />
              <span>
                측정 공백 <strong>{formatDuration(exposure.data_gap_s)}</strong> — 이 시간만큼
                적산되지 않았습니다. 실제 노출은 표시값보다 <strong>큽니다</strong>.
              </span>
            </p>
          )}

          <section className="exposure__gauges" aria-label="지표별 누적 노출량">
            {EXPOSURE_DOSE_METRICS.map(({ key, label }) => (
              <ExposureGauge
                key={key}
                label={label}
                metric={exposure.metrics[key]}
                trust={exposure.trust_level}
              />
            ))}
          </section>

          {hasActiveDose(exposure) && (
            <section aria-label="지표별 상세">
              <h3 className="section-head">지표 상세</h3>
              <table className="exposure__table">
                <thead>
                  <tr>
                    <th>지표</th>
                    <th>TWA 8h</th>
                    <th>TWA 15min</th>
                    <th>최고 농도</th>
                    <th>STEL</th>
                    <th>농도 출처</th>
                  </tr>
                </thead>
                <tbody>
                  {EXPOSURE_DOSE_METRICS.map(({ key, label }) => (
                    <DoseRow key={key} label={label} metric={exposure.metrics[key]} />
                  ))}
                </tbody>
              </table>
            </section>
          )}

          <O2Section o2={exposure.metrics.o2_pct} />

          <footer className="exposure__disclaimer">{EXPOSURE_DISCLAIMER}</footer>
        </>
      )}
    </div>
  );
}

function DoseRow({ label, metric }: { label: string; metric: ExposureDoseMetric | undefined }) {
  const level = doseLevel(metric);

  if (!metric || metric.status === "unavailable") {
    // 빈 칸으로 두면 "해당 없음"으로 읽힌다. 왜 없는지를 그 자리에 적는다.
    return (
      <tr className="is-unknown exposure__row--na">
        <th scope="row">{label}</th>
        <td colSpan={5}>
          {metric?.reason ? (
            <>
              <strong>{UNAVAILABLE_LABEL[metric.reason]}</strong> —{" "}
              {UNAVAILABLE_HINT[metric.reason]}
            </>
          ) : (
            "산출 불가"
          )}
        </td>
      </tr>
    );
  }

  return (
    <tr className={"is-" + level}>
      <th scope="row">{label}</th>
      <td>{num(metric.twa_8h_ppm, 1)}</td>
      <td>{num(metric.twa_15min_ppm, 1)}</td>
      <td>
        {num(metric.peak_ppm, 1)}
        {metric.peak_at && <em> {clock(metric.peak_at)}</em>}
      </td>
      <td className={metric.stel_exceeded ? "exposure__stel--over" : ""}>
        {metric.stel_exceeded ? "초과" : metric.stel_limit_ppm != null ? "이내" : "—"}
      </td>
      <td>
        {metric.source_node_id ?? "—"}
        {metric.source_distance_m != null && <em> {metric.source_distance_m.toFixed(1)}m</em>}
      </td>
    </tr>
  );
}

/**
 * O₂ 누적.
 *
 * 산소는 몸에 축적되지 않는다. 결핍 상태에 있던 **시간**을 누적한다 (§2.4).
 * 그래서 이 절만 단위가 ppm·min 이 아니라 초다.
 */
function O2Section({ o2 }: { o2: ExposureO2Metric | undefined }) {
  if (!o2 || o2.status === "unavailable") {
    return (
      <section className="exposure__o2 is-unknown" aria-label="O₂ 노출 시간">
        <h3 className="section-head">O₂ 노출 시간</h3>
        <p className="exposure__o2-na">
          {o2?.reason ? O2_UNAVAILABLE_LABEL[o2.reason] : "산출 불가"} — 누적 시간을 알 수 없습니다.
        </p>
      </section>
    );
  }

  return (
    <section className={"exposure__o2 is-" + doseLevel(o2)} aria-label="O₂ 노출 시간">
      <h3 className="section-head">O₂ 노출 시간</h3>
      <dl className="exposure__o2-grid">
        <div>
          <dt>결핍 (&lt; 19.5%)</dt>
          <dd>{formatDuration(o2.o2_deficient_s ?? 0)}</dd>
        </div>
        <div>
          <dt>심각 (&lt; 16.0%)</dt>
          <dd className={(o2.o2_severe_s ?? 0) > 0 ? "exposure__o2-severe" : ""}>
            {formatDuration(o2.o2_severe_s ?? 0)}
          </dd>
        </div>
        <div>
          <dt>과다 (&gt; 23.5%)</dt>
          <dd>{formatDuration(o2.o2_enriched_s ?? 0)}</dd>
        </div>
        <div>
          <dt>최저 농도</dt>
          <dd>{o2.o2_min_pct != null ? `${o2.o2_min_pct.toFixed(1)}%` : "—"}</dd>
        </div>
      </dl>
    </section>
  );
}

/**
 * 목 데이터 토글 (A1).
 *
 * 운영 빌드에서는 렌더하지 않는다. 관제 화면에 가짜 데이터를 켜는 버튼이 있으면
 * 안 된다.
 */
function MockControls() {
  const enabled = useExposureMock((s) => s.enabled);
  const state = useExposureMock((s) => s.state);
  const setEnabled = useExposureMock((s) => s.setEnabled);
  const setState = useExposureMock((s) => s.setState);

  if (!import.meta.env.DEV) return null;

  return (
    <div className="exposure__mock">
      <label className="exposure__mock-toggle">
        <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
        <span>목 데이터</span>
      </label>
      <div className="exposure__mock-states" role="group" aria-label="목 데이터 상태">
        {EXPOSURE_MOCK_STATES.map(({ key, label }) => (
          <button
            key={key}
            type="button"
            disabled={!enabled}
            aria-pressed={state === key}
            className={"exposure__mock-btn" + (state === key ? " is-active" : "")}
            onClick={() => setState(key as ExposureMockState)}
          >
            {label}
          </button>
        ))}
      </div>
    </div>
  );
}
