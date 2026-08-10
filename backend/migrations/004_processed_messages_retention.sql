-- processed_messages retention 지원 인덱스 (이슈 #97).
-- processed_messages 자체는 일반 테이블 (hypertable 아님) — PK(message_id) 만으로
-- partition key(time) 를 포함할 수 없어 TimescaleDB retention policy 대신
-- 백엔드의 주기적 DELETE 작업으로 정리한다.
--
-- received_at 인덱스는 cleanup 쿼리(DELETE WHERE received_at < now() - INTERVAL '30 days')
-- 의 성능을 보장한다. 테이블이 커져도 인덱스 스캔으로 빠르게 정리.

CREATE INDEX IF NOT EXISTS idx_processed_messages_received_at
    ON processed_messages (received_at);
