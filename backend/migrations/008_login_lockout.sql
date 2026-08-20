-- 계정 잠금 (AUTH-10, 이슈 #140; FR-609).
--
-- 로그인 5회 실패 시 10분 잠금. locked_until 이 now() 보다 미래면 올바른
-- 비밀번호라도 거부한다 — 무차별 대입의 시간당 시도 횟수를 30회로 묶는다.
-- 실패 횟수는 성공 시 0으로 리셋된다 (애플리케이션이 관리).

ALTER TABLE users ADD COLUMN IF NOT EXISTS failed_login_attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS locked_until TIMESTAMPTZ;
