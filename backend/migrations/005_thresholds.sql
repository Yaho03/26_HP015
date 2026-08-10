-- thresholds 테이블 + 기본값 시드 (이슈 #53).
-- PRD FR-201 + 06_ALERT_RULES 섹션 4.1/4.2 의 임계값 데이터.
-- 경보 판정 로직(#54)과 Hysteresis/De-escalation(#55)이 이 테이블을 참조한다.
--
-- metric / level 별로 enter_threshold(진입) 와 exit_threshold(해제) 쌍을 가진다.
-- direction 이 'below' 인 경우 (O2 저농도) 측정값이 enter_threshold 미만일 때 진입.
-- 'above' (기본) 인 경우 측정값이 enter_threshold 이상일 때 진입.

CREATE TABLE IF NOT EXISTS thresholds (
    metric          TEXT NOT NULL,
    level           TEXT NOT NULL CHECK (level IN ('level1_caution', 'level2_warning', 'level3_critical')),
    direction       TEXT NOT NULL DEFAULT 'above' CHECK (direction IN ('above', 'below')),
    enter_threshold DOUBLE PRECISION NOT NULL,
    exit_threshold  DOUBLE PRECISION NOT NULL,
    enter_for_ms    INTEGER NOT NULL CHECK (enter_for_ms >= 0),
    exit_for_ms     INTEGER NOT NULL CHECK (exit_for_ms >= 0),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (metric, level)
);

-- ============================================================
-- 기본 임계값 시드 (PRD FR-201, 06_ALERT_RULES 4.1/4.2)
-- ON CONFLICT 로 재실행 안전 (#98).
-- ============================================================

INSERT INTO thresholds (metric, level, direction, enter_threshold, exit_threshold, enter_for_ms, exit_for_ms) VALUES
    ('co2_ppm', 'level1_caution', 'above', 1000,  900,  3000, 5000),
    ('co2_ppm', 'level2_warning', 'above', 2000, 1900,  3000, 5000),
    ('co2_ppm', 'level3_critical','above', 5000, 4500,  0,    5000)
ON CONFLICT (metric, level) DO NOTHING;

INSERT INTO thresholds (metric, level, direction, enter_threshold, exit_threshold, enter_for_ms, exit_for_ms) VALUES
    ('co_ppm', 'level1_caution', 'above', 25,  20,   3000, 5000),
    ('co_ppm', 'level2_warning', 'above', 50,  45,   3000, 5000),
    ('co_ppm', 'level3_critical','above', 200, 180,  0,    5000)
ON CONFLICT (metric, level) DO NOTHING;

INSERT INTO thresholds (metric, level, direction, enter_threshold, exit_threshold, enter_for_ms, exit_for_ms) VALUES
    ('h2s_ppm', 'level1_caution', 'above', 1,  0.5, 3000, 5000),
    ('h2s_ppm', 'level2_warning', 'above', 5,  4,   3000, 5000),
    ('h2s_ppm', 'level3_critical','above', 10, 8,   0,    5000)
ON CONFLICT (metric, level) DO NOTHING;

INSERT INTO thresholds (metric, level, direction, enter_threshold, exit_threshold, enter_for_ms, exit_for_ms) VALUES
    ('temperature_c', 'level1_caution', 'above', 35, 34, 5000, 10000),
    ('temperature_c', 'level2_warning', 'above', 38, 37, 5000, 10000),
    ('temperature_c', 'level3_critical','above', 40, 39, 0,    10000)
ON CONFLICT (metric, level) DO NOTHING;

INSERT INTO thresholds (metric, level, direction, enter_threshold, exit_threshold, enter_for_ms, exit_for_ms) VALUES
    ('o2_low', 'level1_caution', 'below', 19.5, 20.0, 5000, 10000),
    ('o2_low', 'level2_warning', 'below', 18.0, 18.5, 5000, 10000),
    ('o2_low', 'level3_critical','below', 16.0, 16.5, 0,    10000)
ON CONFLICT (metric, level) DO NOTHING;

INSERT INTO thresholds (metric, level, direction, enter_threshold, exit_threshold, enter_for_ms, exit_for_ms) VALUES
    ('o2_high', 'level1_caution', 'above', 23.5, 23.0, 5000, 10000),
    ('o2_high', 'level2_warning', 'above', 25.0, 24.5, 5000, 10000),
    ('o2_high', 'level3_critical','above', 28.0, 27.5, 0,    10000)
ON CONFLICT (metric, level) DO NOTHING;
