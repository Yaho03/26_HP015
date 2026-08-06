-- 초기 TimescaleDB 스키마 (이슈 #50).
-- sensor_data(hypertable) + alert_events + node_status.
-- 실제 MQTT 연동은 #51, 임계값 관리는 #53에서 이 테이블들을 사용한다.
--
-- 적용: psql "$TIMESCALE_URL" -f backend/migrations/001_init.sql

CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ============================================================
-- sensor_data — 센서 측정값 (long format: 한 측정값 = 한 행)
-- 04_DATA_CONTRACT.md의 telemetry 필드(co2_ppm, temperature_c 등)를
-- metric 컬럼값으로 저장한다.
-- ============================================================
-- time: 반드시 메시지의 sampled_at 값을 사용한다 (backend_received_at/now() 아님).
--   #51 구현 시 이 규칙을 지켜야 아래 message_id 관련 중복 방지가 의미를 가진다
--   (재전송된 메시지도 sampled_at은 원본과 동일하므로 중복 판정에 사용 가능).
-- message_id: 04_DATA_CONTRACT.md 7.1 "동일 message_id 수신 시 두 번째 메시지는
-- 저장하지 않는다"(FR-101 MUST) 요구사항을 DB 레벨에서 강제하기 위한 컬럼.
-- 메시지 하나가 여러 metric 행으로 펼쳐지므로 (message_id, metric) 조합으로 unique 처리한다.
-- 이 unique 제약은 2차 방어선이며, 1차 방어선은 아래 processed_messages 테이블이다.
CREATE TABLE IF NOT EXISTS sensor_data (
    time       TIMESTAMPTZ NOT NULL,
    node_id    TEXT NOT NULL,
    metric     TEXT NOT NULL,
    value      DOUBLE PRECISION NOT NULL,
    message_id TEXT NOT NULL
);

SELECT create_hypertable('sensor_data', 'time', if_not_exists => TRUE);

-- 인덱스 최적화 (node_id + time 조합 조회)
CREATE INDEX IF NOT EXISTS idx_sensor_data_node_time
    ON sensor_data (node_id, time DESC);

-- 중복 메시지 방지 2차 방어선. hypertable의 unique index는 파티션 키(time)를 포함해야 한다.
CREATE UNIQUE INDEX IF NOT EXISTS uq_sensor_data_message_metric
    ON sensor_data (message_id, metric, time);

-- ============================================================
-- processed_messages — 메시지 단위 중복 방지 1차 방어선 (FR-101 MUST)
-- #51은 파싱/저장 전에 이 테이블에 먼저 INSERT ... ON CONFLICT DO NOTHING 한다.
-- 0행이 삽입되면(이미 존재) 해당 메시지 전체(모든 metric 포함)를 스킵한다.
-- time/metric 값과 무관하게 message_id만으로 판단하므로 FR-101을 정확히 만족한다.
-- ============================================================
CREATE TABLE IF NOT EXISTS processed_messages (
    message_id  TEXT PRIMARY KEY,
    node_id     TEXT NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 1분 평균 continuous aggregate
--
-- 주의(알려진 한계): refresh policy의 start_offset/end_offset은 "정책 실행 시각" 기준
-- 슬라이딩 윈도우이며, 데이터의 실제 time 값 기준이 아니다. 노드가 오프라인 버퍼링
-- 후 재전송(FR-101 SHOULD, 최대 100건)하여 3분보다 오래된 데이터가 뒤늦게 들어오면,
-- 원시 데이터(sensor_data)에는 정상 저장되지만 1분 평균(sensor_data_1min)에는
-- 반영되지 않을 수 있다. MVP 단계에서는 허용하되, 필요 시 refresh_continuous_aggregate()
-- 수동 호출 또는 start_offset 확대를 고려한다.
CREATE MATERIALIZED VIEW IF NOT EXISTS sensor_data_1min
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 minute', time) AS bucket,
    node_id,
    metric,
    AVG(value) AS avg_value
FROM sensor_data
GROUP BY bucket, node_id, metric
WITH NO DATA;

SELECT add_continuous_aggregate_policy('sensor_data_1min',
    start_offset => INTERVAL '3 minutes',
    end_offset   => INTERVAL '1 minute',
    schedule_interval => INTERVAL '1 minute',
    if_not_exists => TRUE
);

-- 원시 데이터 30일 retention (1분 평균은 별도 뷰라 영향받지 않음)
SELECT add_retention_policy('sensor_data', INTERVAL '30 days', if_not_exists => TRUE);

-- ============================================================
-- alert_events — 경보 발생/해제 이력 (영구 보관, retention 없음)
-- schemas/alert-event.schema.json 필드와 대응
-- ============================================================
CREATE TABLE IF NOT EXISTS alert_events (
    message_id     TEXT PRIMARY KEY,
    schema_version TEXT NOT NULL,
    alert_id       TEXT NOT NULL,
    source_node_id TEXT NOT NULL,
    alert_key      TEXT NOT NULL,
    alert_type     TEXT NOT NULL,
    level          TEXT NOT NULL,
    trigger_value  DOUBLE PRECISION,
    threshold      DOUBLE PRECISION,
    metric         TEXT,
    message        TEXT NOT NULL,
    status         TEXT NOT NULL,
    activated_at   TIMESTAMPTZ NOT NULL,
    resolved_at    TIMESTAMPTZ,
    published_at   TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_alert_events_node_time
    ON alert_events (source_node_id, activated_at DESC);

-- ============================================================
-- node_status — 노드별 최신 상태 (배터리/RSSI/uptime 등)
-- schemas/sensor-status.schema.json 필드와 대응. node_id당 최신값 1행 유지.
-- ============================================================
CREATE TABLE IF NOT EXISTS node_status (
    node_id          TEXT PRIMARY KEY,
    battery_pct      INTEGER,
    wifi_rssi_dbm    INTEGER,
    uptime_s         INTEGER,
    free_heap_bytes  INTEGER,
    sensors_online   TEXT[],
    sensors_error    TEXT[],
    updated_at       TIMESTAMPTZ NOT NULL
);
