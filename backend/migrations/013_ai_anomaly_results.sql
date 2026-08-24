-- AI 이상징후 판정 결과 (연구용).
--
-- **alert_events 와 분리한다.** 같은 테이블에 두면 안 되는 이유:
--   1. alert_events 는 산업안전 경보 이력이고 영구 보관 대상이다. 사고 조사에서
--      "그때 시스템이 뭐라고 했나" 의 근거가 되는 기록이다.
--   2. AI 결과는 연구용 참고 지표이며 모델을 바꾸면 과거 값의 의미가 달라진다.
--   3. 한 테이블에 섞이면 경보 이력 조회가 AI 행까지 훑게 되고, 무엇보다
--      누군가 status='active' 로 필터하다 AI 행을 안전 경보로 세게 된다.
--
-- level 컬럼을 두지 않는다. AlertLevel(level1~3)로 변환할 수 있는 통로를 만들면
-- 언젠가 누가 변환한다. AI 상태는 자체 enum 으로만 존재한다.

CREATE TABLE IF NOT EXISTS ai_anomaly_results (
    time            TIMESTAMPTZ NOT NULL,
    node_id         TEXT NOT NULL,
    -- model_not_ready / insufficient_data / stale_data / feature_mismatch
    -- / normal_pattern / anomaly_candidate / anomaly
    -- 앞의 넷은 "판단하지 않았다" 이고 normal_pattern 으로 변환되지 않는다.
    status          TEXT NOT NULL,
    -- 판단 불가 상태에서는 NULL 이다. 0 으로 채우면 "완벽히 정상" 으로 읽힌다.
    score           DOUBLE PRECISION,
    threshold       DOUBLE PRECISION,
    consecutive_exceedances INTEGER NOT NULL DEFAULT 0,
    -- [{"metric": "...", "error": 0.62}, ...]
    top_contributors JSONB,
    model_version   TEXT NOT NULL,
    -- 이 판정이 실측 데이터에서 나왔는지 주입 데이터에서 나왔는지.
    source_mode     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

SELECT create_hypertable('ai_anomaly_results', 'time', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_ai_anomaly_node_time
    ON ai_anomaly_results (node_id, time DESC);

-- 연구용 참고 지표라 영구 보관하지 않는다. 안전 경보 이력(alert_events)과 달리
-- 법적 보존 의무가 없고, 모델이 바뀌면 과거 점수는 비교 대상이 되지 못한다.
SELECT add_retention_policy('ai_anomaly_results', INTERVAL '30 days', if_not_exists => TRUE);
