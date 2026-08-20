-- 사용자 계정 + 세션 + 감사 로그 (AUTH-2, 이슈 #132; FR-601~611).
--
-- 설계 결정 (ADR-007):
--   1. 세션은 서버 저장 + HttpOnly 쿠키. JWT 가 아니다 — WebSocket 핸드셰이크에
--      커스텀 헤더를 못 붙이는 브라우저 제약과 즉시 폐기(경보 상황 권한 회수)
--      가 결정적 근거였다.
--   2. sessions.session_hash 는 원문 토큰의 SHA-256 이다. DB 가 유출돼도
--      쿠키 값을 그대로 재사용할 수 없다.
--   3. users.password_hash 는 Argon2id (argon2-cffi). 마이그레이션 SQL 에
--      계정/해시를 하드코딩하지 않는다 — 최초 계정은 환경 변수 부트스트랩
--      (AUTH-9, #139)이 만든다. 이 파일엔 시드가 없다.
--
-- 007_workers.sql 이 006 번호를 건너뛰며 이미 존재한다 (당시 006 을
-- users 로 예약). 이 파일이 그 예약 번호를 채운다. migration_runner 는
-- 파일명 순서대로 적용하므로 005 → 006(본 파일) → 007 순으로 실행된다.

CREATE TABLE IF NOT EXISTS users (
    id                    BIGSERIAL PRIMARY KEY,
    username              TEXT NOT NULL,
    password_hash         TEXT NOT NULL,
    display_name          TEXT NOT NULL DEFAULT '',
    role                  TEXT NOT NULL DEFAULT 'viewer'
                          CHECK (role IN ('admin', 'supervisor', 'viewer')),
    is_active             BOOLEAN NOT NULL DEFAULT true,
    must_change_password  BOOLEAN NOT NULL DEFAULT false,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- username 은 로그인 식별자로 조직 내 유일하다.
CREATE UNIQUE INDEX IF NOT EXISTS uq_users_username ON users (username);

CREATE TABLE IF NOT EXISTS sessions (
    id            BIGSERIAL PRIMARY KEY,
    user_id       BIGINT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    -- 쿠키 원문 토큰의 SHA-256 hex. 원문은 어디에도 저장하지 않는다.
    session_hash  TEXT NOT NULL,
    -- double-submit CSRF (FR-608). HttpOnly 가 아닌 쿠키로도 내려가고
    -- X-CSRF-Token 헤더와 이 값이 일치해야 상태 변경이 통과된다.
    csrf_token    TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- 절대 만료 기준(created_at + 12h). 유휴 만료는 last_seen_at + 8h.
    expires_at    TIMESTAMPTZ NOT NULL,
    last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at    TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_sessions_hash ON sessions (session_hash);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions (user_id) WHERE revoked_at IS NULL;

CREATE TABLE IF NOT EXISTS audit_log (
    id          BIGSERIAL PRIMARY KEY,
    -- actor 는 user_id FK 가 아니라 비정규화된 이름을 남긴다 — 계정이
    -- 삭제돼도 "누가 했는지"는 감사 가능해야 한다 (FR-605).
    actor_id    BIGINT,
    actor_name  TEXT NOT NULL,
    action      TEXT NOT NULL,
    target      TEXT NOT NULL DEFAULT '',
    detail      JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_audit_log_created ON audit_log (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_action ON audit_log (action);
