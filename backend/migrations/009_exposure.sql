-- 작업자 누적 유해가스 노출량 (FR-701~708, docs/11_EXPOSURE_DOSE_SPEC.md §6.3).
--
-- 기존 경보는 순간값만 본다. CO2 가 1,200ppm 이면 주의, 900ppm 으로 내려가면
-- 정상이다. 그런데 산업위생에서 위험은 농도가 아니라 **농도 x 시간**으로 결정된다.
-- 1,200ppm 에서 6시간 일한 작업자와 방금 들어온 작업자는 같은 상태가 아닌데,
-- 지금 시스템은 둘을 구분하지 못한다. 이 스키마가 그 차이를 기록한다.
--
-- 설계 결정 1 — 기준값은 코드가 아니라 DB 가 소스다.
--   thresholds 테이블과 같은 철학이다 (FR-201). 노출 기준은 법령 개정으로 바뀌고
--   관리자가 고칠 수 있어야 한다. 코드에 박으면 배포 없이는 못 고친다.
--
-- 설계 결정 2 — 적산 상태(exposure_state)와 확정 이력(exposure_shift_log)을 나눈다.
--   전자는 10초마다 덮어써지는 작업 상태이고, 후자는 사고 조사용 영구 기록이다.
--   수명도 접근 패턴도 다르다. 한 테이블에 두면 활성 윈도우 조회가 과거 전체를
--   훑게 되고, 확정된 기록이 실수로 갱신될 여지가 생긴다.
--
-- 설계 결정 3 — 이 마이그레이션은 exposure_limits 에 **아무 값도 넣지 않는다**.
--   기준값 출처는 고용노동부 「화학물질 및 물리적 인자의 노출기준」 고시로
--   확정됐으나(§3.1) 원문 대조(P0-A)가 끝나지 않았다(§3.2). 검증되지 않은 숫자를
--   안전 기준으로 넣는 것은 근거 없는 숫자에 사람 목숨을 거는 일이다. 시드되지
--   않은 metric 은 API 가 status "unavailable", reason "limit_unverified" 로 내려보낸다.
--   화면은 그것을 "0% 노출"이 아니라 "기준값 미검증"으로 그린다 (§6.4 MUST).

-- ── 노출 기준값 ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS exposure_limits (
    metric              TEXT PRIMARY KEY,
    -- 8시간 시간가중평균 허용 농도. 고시에서 확인하는 값은 이것과 STEL 둘뿐이다.
    twa_limit_ppm       DOUBLE PRECISION,
    -- twa_limit_ppm x 480분. 독립적으로 정하는 값이 아니라 위에서 파생된다(§2.1).
    -- 생성 컬럼으로 묶지 않은 이유는 고시가 누적 기준을 따로 제시할 경우를 남겨두기
    -- 위해서다. 시드 시점에 두 값이 어긋나지 않는지 확인할 책임은 시드 쪽에 있다.
    dose_limit_ppm_min  DOUBLE PRECISION,
    -- 15분 단시간노출기준.
    stel_limit_ppm      DOUBLE PRECISION,
    reference           TEXT NOT NULL,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- metric 문자열은 sensor_data.metric 과 **같은 값**이어야 한다 (§2.3).
    -- 어긋나면 조인이 조용히 빈 결과를 내고, 화면에는 "측정 없음"으로 보인다.
    -- 오타를 런타임까지 끌고 가지 않도록 DB 가 막는다. 노출량 대상은 이 4종으로
    -- 고정이며(센서 노드 4종 + 웨어러블 O2), 늘어나면 마이그레이션으로 넓힌다.
    CONSTRAINT exposure_limits_metric_known
        CHECK (metric IN ('co2_ppm', 'co_ppm', 'h2s_ppm', 'o2_pct')),

    -- 출처 없는 기준값은 기준값이 아니다 (§3.3 MUST). 고시명·조항·개정일이 들어가야
    -- 하므로 "ACGIH" 같은 단어 하나나 빈 문자열은 통과시키지 않는다. 심사에서
    -- "이 숫자는 어디서 왔는가"에 답하지 못하면 이 기능 전체가 근거를 잃는다.
    CONSTRAINT exposure_limits_reference_substantive
        CHECK (length(btrim(reference)) >= 10)
);

-- ── 활성 노출 윈도우 (재시작 복구용, §4.5) ─────────────────────────────────
CREATE TABLE IF NOT EXISTS exposure_state (
    exposure_id     TEXT PRIMARY KEY,
    worker_id       BIGINT NOT NULL REFERENCES workers (id) ON DELETE CASCADE,
    node_id         TEXT NOT NULL,
    metric          TEXT NOT NULL,
    window_start    TIMESTAMPTZ NOT NULL,
    window_source   TEXT NOT NULL,

    -- 누적 노출량. 메모리에만 두면 백엔드 재시작에 8시간치가 사라진다 (§4.5 MUST).
    dose_ppm_min    DOUBLE PRECISION NOT NULL DEFAULT 0,
    -- 전 노드 최댓값 기준 누적. **표시 전용이고 경보 판정에 쓰지 않는다** (ADR-008).
    dose_worst_case_ppm_min DOUBLE PRECISION NOT NULL DEFAULT 0,

    -- O2 는 몸에 축적되지 않는다. 결핍 상태에 있던 시간을 누적한다 (§2.4).
    -- 그래서 이 세 컬럼만 단위가 ppm·min 이 아니라 초다.
    o2_deficient_s  INTEGER NOT NULL DEFAULT 0,
    o2_severe_s     INTEGER NOT NULL DEFAULT 0,
    o2_enriched_s   INTEGER NOT NULL DEFAULT 0,

    peak_ppm        DOUBLE PRECISION,
    peak_at         TIMESTAMPTZ,
    o2_min_pct      DOUBLE PRECISION,

    -- 사다리꼴 적분의 좌변. 다음 샘플이 올 때 이 값과 평균 내어 적산한다 (§4.1).
    last_value      DOUBLE PRECISION,
    last_sample_at  TIMESTAMPTZ,

    -- 샘플이 없어 적산하지 못한 시간. 이만큼 dose 는 **과소평가**되어 있다 (§4.2).
    -- 0 으로 간주하면 안전 시스템에서 최악의 오류가 되므로 별도로 남긴다.
    data_gap_s      INTEGER NOT NULL DEFAULT 0,

    closed_at       TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT exposure_state_metric_known
        CHECK (metric IN ('co2_ppm', 'co_ppm', 'h2s_ppm', 'o2_pct')),
    CONSTRAINT exposure_state_window_source_known
        CHECK (window_source IN ('assignment', 'manual_reset', 'shift_rollover')),
    CONSTRAINT exposure_state_period_valid
        CHECK (closed_at IS NULL OR closed_at > window_start),

    -- 누적값은 단조 증가한다 (§5.2). 음수가 나왔다면 적산 로직이 깨진 것이고,
    -- 그 상태로 경보를 판정하게 두는 것보다 쓰기를 거부하는 편이 안전하다.
    CONSTRAINT exposure_state_totals_non_negative
        CHECK (
            dose_ppm_min >= 0
            AND dose_worst_case_ppm_min >= 0
            AND o2_deficient_s >= 0
            AND o2_severe_s >= 0
            AND o2_enriched_s >= 0
            AND data_gap_s >= 0
        )
);

-- 한 (작업자, 노드, 지표) 조합에 활성 윈도우는 하나뿐이다.
-- 부분 유니크 인덱스라 종료된(closed_at NOT NULL) 과거 윈도우는 몇 건이든 남는다.
--
-- 애플리케이션 검증이 아니라 DB 제약으로 두는 이유는 007_workers.sql 과 같다.
-- 윈도우가 둘로 갈라지면 한쪽에만 적산되어 누적량이 실제보다 작게 나오고, 화면은
-- 그것을 정상으로 표시한다. 배정 이벤트와 기동 복구가 동시에 윈도우를 열려는
-- 경합이 실제로 가능하므로, 경합 조건에서도 깨지지 않아야 한다.
CREATE UNIQUE INDEX IF NOT EXISTS uq_exposure_state_active
    ON exposure_state (worker_id, node_id, metric)
    WHERE closed_at IS NULL;

-- 작업자 기준 조회(현재 소진율, 과거 윈도우 역추적) 전용.
CREATE INDEX IF NOT EXISTS idx_exposure_state_worker
    ON exposure_state (worker_id, window_start DESC);

-- 기동 시 활성 윈도우를 한 번에 끌어오기 위한 인덱스 (§4.5 복구 경로).
CREATE INDEX IF NOT EXISTS idx_exposure_state_active_node
    ON exposure_state (node_id)
    WHERE closed_at IS NULL;

-- ── 확정된 과거 윈도우 (사고 조사용, 영구 보관) ────────────────────────────
-- retention 정책을 걸지 않는다. 004_processed_messages_retention.sql 이 다루는
-- 운영 데이터와 성격이 다르다 — 노출 이력은 사후 조사와 분쟁의 근거이고, 보관
-- 기간이 지났다는 이유로 사라지면 안 된다.
CREATE TABLE IF NOT EXISTS exposure_shift_log (
    exposure_id     TEXT PRIMARY KEY,
    worker_id       BIGINT NOT NULL,
    -- 비정규화. workers 로 FK 를 걸지 않는 이유는 계정·작업자가 삭제된 뒤에도
    -- "누가 얼마나 노출됐는가"가 남아야 하기 때문이다. FK + CASCADE 로 묶으면
    -- 퇴사 처리 한 번에 사고 기록이 함께 지워진다.
    worker_name     TEXT NOT NULL,
    node_id         TEXT NOT NULL,
    metric          TEXT NOT NULL,
    window_start    TIMESTAMPTZ NOT NULL,
    window_end      TIMESTAMPTZ NOT NULL,
    dose_ppm_min    DOUBLE PRECISION,
    dose_fraction   DOUBLE PRECISION,
    twa_8h_ppm      DOUBLE PRECISION,
    peak_ppm        DOUBLE PRECISION,
    o2_deficient_s  INTEGER,
    data_gap_s      INTEGER NOT NULL DEFAULT 0,
    trust_level     TEXT NOT NULL,
    max_alert_level TEXT NOT NULL,

    CONSTRAINT exposure_shift_log_metric_known
        CHECK (metric IN ('co2_ppm', 'co_ppm', 'h2s_ppm', 'o2_pct')),
    CONSTRAINT exposure_shift_log_period_valid
        CHECK (window_end > window_start),
    CONSTRAINT exposure_shift_log_trust_level_known
        CHECK (trust_level IN ('high', 'medium', 'low')),
    -- 06_ALERT_RULES.md 의 등급 문자열을 그대로 재사용한다. 여기만 다른 이름을
    -- 쓰면 경보 이력과 노출 이력을 나란히 놓고 볼 수 없다.
    CONSTRAINT exposure_shift_log_alert_level_known
        CHECK (max_alert_level IN (
            'normal', 'level1_caution', 'level2_warning', 'level3_critical'
        ))
);

-- 작업자별 기간 조회 (교대 리포트, 사고 조사).
CREATE INDEX IF NOT EXISTS idx_exposure_shift_log_worker
    ON exposure_shift_log (worker_id, window_start DESC);
