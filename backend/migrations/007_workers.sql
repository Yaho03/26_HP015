-- 작업자 프로필 + 웨어러블 배정 이력 (이슈 #136, FR-306).
--
-- 지금 경보는 `wearable-01` 이라는 노드 ID 만 알고 사람을 모른다. 밀폐공간
-- 산소결핍 경보에서 "누가 위험한가"를 모르면 대피 지시와 구조가 불가능하다.
--
-- 설계 결정 1 — "사용자"와 "작업자"는 다른 개념이다.
--   대시보드 계정(admin/supervisor/viewer)은 로그인하는 주체이고,
--   작업자는 밀폐공간에 들어가는 사람이며 웹 UI 를 쓰지 않는다 (PRODUCT.md).
--   그래서 workers 에는 비밀번호도 권한도 없다. 인증 도입(#132)과 독립적으로
--   이 테이블만으로 경보에 이름을 붙일 수 있다.
--
-- 설계 결정 2 — 배정은 시계열이다.
--   어제 wearable-01 을 착용한 사람과 오늘이 다르다. 과거 경보를 조회할 때
--   "그 시점의 배정"을 되짚어야 사고 조사가 성립한다. 그래서 workers 에
--   node_id 컬럼을 두지 않고 배정 이력을 별도 테이블로 분리했다.

CREATE TABLE IF NOT EXISTS workers (
    id                BIGSERIAL PRIMARY KEY,
    employee_no       TEXT NOT NULL,
    name              TEXT NOT NULL,
    phone             TEXT,
    emergency_contact TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 사번은 조직 내 유일하다. 동명이인을 경보에서 구분하는 근거이기도 하다.
CREATE UNIQUE INDEX IF NOT EXISTS uq_workers_employee_no
    ON workers (employee_no);

CREATE TABLE IF NOT EXISTS worker_assignments (
    id          BIGSERIAL PRIMARY KEY,
    worker_id   BIGINT NOT NULL REFERENCES workers (id) ON DELETE CASCADE,
    node_id     TEXT NOT NULL,
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    released_at TIMESTAMPTZ,
    CONSTRAINT worker_assignments_period_valid
        CHECK (released_at IS NULL OR released_at > assigned_at)
);

-- 한 노드에 두 작업자가 동시에 배정될 수 없다 (이슈 #136 완료 조건).
-- 부분 유니크 인덱스라 종료된(released_at NOT NULL) 과거 배정은 몇 건이든 남는다.
-- 애플리케이션 검증이 아니라 DB 제약으로 두는 이유: 경보가 잘못된 사람을
-- 지목하는 것은 안전 사고로 이어진다. 경합 조건에서도 깨지지 않아야 한다.
CREATE UNIQUE INDEX IF NOT EXISTS uq_worker_assignments_active_node
    ON worker_assignments (node_id)
    WHERE released_at IS NULL;

-- 시점 조회(경보 발생 시각 기준 배정 역추적) 전용 인덱스.
CREATE INDEX IF NOT EXISTS idx_worker_assignments_node_period
    ON worker_assignments (node_id, assigned_at DESC);
