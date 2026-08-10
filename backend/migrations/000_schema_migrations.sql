-- schema_migrations 추적 테이블 (이슈 #98).
-- 백엔드 시작 시 app/migration_runner.py 가 가장 먼저 실행한다.
-- 이 파일 자체는 러너가 직접 처리하므로 일반 마이그레이션 루프에서는 스킵된다
-- (러너의 SCHEMA_MIGRATIONS_SQL 상수와 동일한 내용).
--
-- 수동 적용 시: psql "$TIMESCALE_URL" -f backend/migrations/000_schema_migrations.sql
-- (러너 미사용 환경에서도 추적 테이블을 만들 수 있도록 파일로도 제공).

CREATE TABLE IF NOT EXISTS schema_migrations (
    filename    TEXT PRIMARY KEY,
    checksum    TEXT NOT NULL,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
