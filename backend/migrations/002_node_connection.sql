-- node_status에 연결상태(LWT) 컬럼 추가 (이슈 #51).
-- nodes/{node_id}/connection 토픽 페이로드에는 message_id가 없어 processed_messages
-- dedup 대상이 아니다 (최신 상태로 덮어쓰기만 하면 되므로 중복 문제 없음).
-- 30초 무응답 감지 등 능동적 타임아웃 로직은 #52에서 구현한다. #51은 수신한 그대로 저장만 한다.

ALTER TABLE node_status
    ADD COLUMN IF NOT EXISTS connection_status TEXT,
    ADD COLUMN IF NOT EXISTS connection_reason TEXT,
    ADD COLUMN IF NOT EXISTS connection_updated_at TIMESTAMPTZ;
