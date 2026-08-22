-- 공간 통행 구조(nav graph) + 탈출 경로 이력 (FR-801~808, 12_EVACUATION_ROUTE_SPEC §4.3).
--
-- 저장소에 "어디를 지나갈 수 있는가"에 대한 데이터가 없었다. 센서 노드 좌표와 공간
-- 치수(60 x 20 x 14m)만 있을 뿐이라, 경로를 계산하려면 통행 구조를 먼저 데이터로
-- 옮겨야 한다.
--
-- 좌표는 ship-visual (실제 선박 화물창 치수, Z-up) 이다. 축소 데모 공간(2.5 x 2.0m)에
-- 비계와 사다리를 배치하는 것은 물리적으로 말이 안 되고 이동 거리·시간이 실제 작업
-- 상황을 대표하지 못한다 (ADR-010).
--
-- ── 여기서 시드하지 않는 이유 ────────────────────────────────────────────
-- 005_thresholds.sql 은 기본 임계값을 이 파일 안에서 INSERT 한다. 토폴로지는 그렇게
-- 하지 않는다. migration_runner 가 적용된 파일의 checksum 을 검증하므로(migration_runner.py:95)
-- 한 번 적용된 마이그레이션은 **수정할 수 없다** — 고치면 기동이 실패한다.
-- 토폴로지 좌표는 아직 실측이 아니라 가정값이고(OQ-V5) 도면이 들어오면 교체해야 한다.
-- 그래서 값은 config/space_topology.yaml 이 소스이고, 이 파일은 그릇만 만든다.

-- 통행 가능 지점.
CREATE TABLE IF NOT EXISTS nav_nodes (
    nav_node_id TEXT PRIMARY KEY,
    kind        TEXT NOT NULL
                CHECK (kind IN ('floor', 'scaffold_deck', 'ladder_top', 'ladder_bottom', 'exit')),
    x_m         DOUBLE PRECISION NOT NULL,
    y_m         DOUBLE PRECISION NOT NULL,
    z_m         DOUBLE PRECISION NOT NULL,
    -- 비계 층 식별자(L0/L1...). UWB 측위가 2D 라 작업자가 실제로 어느 층에 있는지는
    -- 측정되지 않는다. 경로는 항상 최하층을 가정하고 화면이 그 가정을 표시한다.
    level_id    TEXT NOT NULL,
    label       TEXT NOT NULL DEFAULT ''
);

-- 이동 가능 구간.
CREATE TABLE IF NOT EXISTS nav_edges (
    edge_id         TEXT PRIMARY KEY,
    from_node_id    TEXT NOT NULL REFERENCES nav_nodes (nav_node_id) ON DELETE CASCADE,
    to_node_id      TEXT NOT NULL REFERENCES nav_nodes (nav_node_id) ON DELETE CASCADE,
    kind            TEXT NOT NULL
                    CHECK (kind IN ('walk', 'scaffold_plank', 'ladder', 'hatch')),
    -- 실제 이동 거리. 좌표 직선거리와 다를 수 있다 — 우회 통로는 양 끝점이 가까워도
    -- 돌아가야 한다. 0 이나 음수면 Dijkstra 가 무한 루프에 빠지거나 비용이 역전되므로
    -- 애플리케이션 검증이 아니라 DB 제약으로 막는다.
    length_m        DOUBLE PRECISION NOT NULL CHECK (length_m > 0),
    -- 이동 난이도 계수 (walk 1.0 / scaffold_plank 1.3 / ladder 2.5 / hatch 1.8).
    traverse_factor DOUBLE PRECISION NOT NULL DEFAULT 1.0 CHECK (traverse_factor > 0),
    bidirectional   BOOLEAN NOT NULL DEFAULT TRUE,
    -- 통로 폭. MVP 는 표시만 하고 병목 계산에 쓰지 않는다 (작업자 1명 전제).
    width_m         DOUBLE PRECISION,
    -- 점검·폐쇄 시 관리자가 내린다. 경로 계산에서 제외된다.
    is_usable       BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_nav_edges_from ON nav_edges (from_node_id);
CREATE INDEX IF NOT EXISTS idx_nav_edges_to   ON nav_edges (to_node_id);

-- 탈출구. 실제 선박 화물창 관행에 맞춰 전방·후방 접근 트렁크 2개를 기본으로 한다.
-- 출구가 1개면 "가스가 찬 쪽을 피해 다른 출구로 돌아간다"는 이 기능의 핵심이 화면에
-- 전혀 드러나지 않는다.
CREATE TABLE IF NOT EXISTS evacuation_exits (
    exit_id     TEXT PRIMARY KEY,
    nav_node_id TEXT NOT NULL REFERENCES nav_nodes (nav_node_id) ON DELETE CASCADE,
    kind        TEXT NOT NULL CHECK (kind IN ('manhole', 'hatch', 'ladder_out')),
    is_usable   BOOLEAN NOT NULL DEFAULT TRUE,
    -- 비용이 같을 때 선호 순위. 낮을수록 우선. 두 출구가 동점일 때 화면이 매번
    -- 다른 답을 내놓지 않게 하는 결정론적 tie-break 다.
    priority    INTEGER NOT NULL DEFAULT 100,
    label       TEXT NOT NULL DEFAULT ''
);

-- 경로 이력. 사고 조사에서 "그때 시스템이 무엇을 지시했는가"를 되짚는 근거다.
-- 매 재계산마다 남기면 폭증하므로 route_id 가 바뀔 때(= 경로가 실제로 교체될 때)만
-- 기록한다. 경보 이벤트와 달리 retention 정책을 걸지 않는다 — 사고 조사 자료다.
CREATE TABLE IF NOT EXISTS evacuation_routes (
    route_id        TEXT PRIMARY KEY,
    node_id         TEXT NOT NULL,
    worker_id       BIGINT,
    -- 비정규화. 작업자 계정이 삭제된 뒤에도 "누구에게 무엇을 지시했는가"가 남아야 한다.
    worker_name     TEXT NOT NULL DEFAULT '',
    computed_at     TIMESTAMPTZ NOT NULL,
    route_status    TEXT NOT NULL
                    CHECK (route_status IN ('safe', 'degraded', 'no_safe_route', 'unavailable')),
    target_exit_id  TEXT,
    total_length_m  DOUBLE PRECISION,
    total_cost      DOUBLE PRECISION,
    switch_reason   TEXT,
    -- waypoint 를 별도 테이블로 정규화하지 않는다. 경로는 통째로 읽고 통째로 쓰는
    -- 불변 스냅샷이고, 조인해서 부분 조회할 일이 없다.
    waypoints       JSONB NOT NULL,
    blocked_exits   JSONB NOT NULL DEFAULT '[]'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_evacuation_routes_node_time
    ON evacuation_routes (node_id, computed_at DESC);
