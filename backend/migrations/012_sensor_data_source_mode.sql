-- sensor_data 에 데이터 출처(source_mode)를 보존한다.
--
-- 배경: 04_DATA_CONTRACT 3.5 에 따라 시뮬레이션 주입도 실제 node_id 를 그대로 쓴다
-- (sim-NN prefix 를 쓰지 않는다). 구분은 envelope 의 source_mode 필드가 유일한데,
-- ingest 가 그 필드를 읽지 않아 저장된 뒤에는 실측과 주입을 되돌릴 방법이 없었다.
-- 실제로 지금 DB 의 sensor_data 는 전부 데모 주입값인데 그것을 SQL 로 판별할 수 없다.
--
-- 이 컬럼이 필요한 이유는 AI 이상탐지가 "정상 실측만 학습" 을 전제하기 때문이다.
-- 주입값을 정상 패턴으로 학습하면 모델이 배우는 것은 센서가 아니라 시나리오 스크립트다.
--
-- NULL 을 허용하는 이유:
--   (a) 이 마이그레이션 이전에 쌓인 행은 출처를 소급할 수 없다. 'live' 로 채우면
--       주입값 15만 행이 실측으로 둔갑한다. 모르는 것은 모르는 채로 둔다.
--   (b) 이후에도 source_mode 가 없거나 계약 밖 값인 메시지는 NULL 로 남긴다.
--       필수로 강제해 메시지를 drop 하면 안전 필수 경보 경로가 필드 하나 때문에 끊긴다.
-- 학습셋은 source_mode = 'live' 인 행만 쓴다. NULL 은 자동으로 제외된다.
--
-- CHECK 제약을 걸지 않는다: 계약 밖 값은 ingest 가 NULL 로 정규화하므로 DB 까지
-- 내려오지 않고, 제약 위반으로 INSERT 가 실패하면 그 메시지의 모든 metric 이 유실된다.

ALTER TABLE sensor_data
    ADD COLUMN IF NOT EXISTS source_mode TEXT;

-- 학습셋 추출은 "특정 노드의 특정 구간에서 live 인 행" 을 훑는다.
-- 기존 idx_sensor_data_node_time 은 source_mode 를 모르므로 실측만 뽑을 때
-- 주입 행까지 전부 읽고 버리게 된다.
CREATE INDEX IF NOT EXISTS idx_sensor_data_source_mode_node_time
    ON sensor_data (source_mode, node_id, time DESC);
