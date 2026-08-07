-- node_status에 backend_received_at 추가 (이슈 #51 리뷰 반영).
-- status/connection(LWT) 메시지가 백엔드에 도착한 시각을 직접 기록한다.
-- (기존 processed_messages.received_at은 telemetry에는 있지만 node_status가
--  message_id를 저장하지 않아 역추적이 안 되고, connection 메시지는 message_id가
--  없어 processed_messages를 아예 거치지 않아 기록이 전혀 없었음)

ALTER TABLE node_status
    ADD COLUMN IF NOT EXISTS backend_received_at TIMESTAMPTZ;
