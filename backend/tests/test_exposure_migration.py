"""009_exposure.sql 스키마 검증 (FR-701~708, A2).

test_migrations.py 는 모든 마이그레이션에 공통으로 걸리는 idempotency 가드를 본다.
이 파일은 노출량 스키마에만 해당하는 **안전 불변식**을 본다.

가장 중요한 것은 `test_exposure_limits_is_not_seeded` 다. 기준값 원문 대조가 끝나기
전에 누군가 "일단 ACGIH 값이라도 넣자"고 시드하는 순간, 검증되지 않은 숫자가 안전
기준이 된다. 그 실수를 리뷰가 아니라 테스트가 막는다.

DB 없이 검증 가능한 정적 검사만 담는다. 실제 DDL 실행 검증은 CI 통합 테스트(#84) 소관.
"""
from __future__ import annotations

import re
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"
EXPOSURE_SQL = MIGRATIONS_DIR / "009_exposure.sql"

# 노출량이 다루는 지표. sensor_data.metric 과 **같은 문자열**이어야 한다
# (11_EXPOSURE_DOSE_SPEC.md §2.3). 어긋나면 조인이 조용히 빈 결과를 낸다.
EXPECTED_METRICS = {"co2_ppm", "co_ppm", "h2s_ppm", "o2_pct"}

TABLES = ("exposure_limits", "exposure_state", "exposure_shift_log")


def _strip_comments(sql: str) -> str:
    """`--` 주석 제거. 주석 안의 예시 문자열이 검사에 걸리지 않게 한다."""
    out = []
    for line in sql.splitlines():
        if line.strip().startswith("--"):
            continue
        if "--" in line:
            line = line.split("--", 1)[0]
        out.append(line)
    return "\n".join(out)


def _sql() -> str:
    return _strip_comments(EXPOSURE_SQL.read_text(encoding="utf-8"))


def _table_block(sql: str, table: str) -> str:
    """CREATE TABLE ... ( ... ) 본문을 괄호 균형으로 잘라낸다."""
    m = re.search(
        rf"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+{table}\s*\(", sql, re.IGNORECASE
    )
    assert m, f"{table} 테이블 정의를 찾을 수 없다"
    i = m.end()
    depth = 1
    start = i
    while i < len(sql) and depth > 0:
        if sql[i] == "(":
            depth += 1
        elif sql[i] == ")":
            depth -= 1
        i += 1
    return sql[start : i - 1]


# ============================================================
# 파일 자체 — 번호가 정확해야 한다
# ============================================================

def test_migration_file_is_009_not_008():
    """노출량 마이그레이션은 009 다.

    세션 계획서는 008 을 예약했으나 그 사이 origin/main 에 008_login_lockout.sql
    (AUTH-10, #186)이 들어갔다. migration_runner 는 파일명 순 정렬 + 파일명 키
    추적이라 008_ 중복이 checksum 에러를 내지는 않지만, main 을 이미 적용한 DB
    에서는 008_exposure.sql 이 알파벳 순으로 앞서면서 번호보다 늦게 적용된다.
    그 순간 번호가 적용 순서를 보장하지 못하게 된다.
    """
    assert EXPOSURE_SQL.exists(), "009_exposure.sql 이 없다"
    assert not (MIGRATIONS_DIR / "008_exposure.sql").exists(), (
        "008_exposure.sql 이 남아 있다. 008 은 login_lockout 이 쓰고 있다"
    )


def test_all_three_tables_defined():
    sql = _sql()
    for table in TABLES:
        assert re.search(
            rf"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+{table}\b", sql, re.IGNORECASE
        ), f"{table} 이 정의되지 않았다"


# ============================================================
# 기준값 — 검증 전에는 시드하지 않는다 (§3.2 MUST)
# ============================================================

def test_exposure_limits_is_not_seeded():
    """이 마이그레이션은 exposure_limits 에 한 행도 넣지 않아야 한다.

    기준값 출처는 고용노동부 고시로 확정됐으나(§3.1) 원문 대조(P0-A)가 끝나지
    않았다(§3.2). 검증되지 않은 숫자를 안전 기준으로 넣으면, 화면은 그것을 근거
    있는 값처럼 보여준다. 시드되지 않은 metric 은 status "unavailable",
    reason "limit_unverified" 로 내려가는 것이 정상 동작이다.
    """
    sql = _sql()
    inserts = re.findall(r"INSERT\s+INTO\s+(\w+)", sql, re.IGNORECASE)
    assert not inserts, (
        f"마이그레이션이 데이터를 시드하고 있다: {inserts}. "
        f"기준값은 고시 원문 대조(P0-A) 후에 넣는다."
    )


def test_exposure_limits_requires_substantive_reference():
    """출처 없는 기준값은 기준값이 아니다 (§3.3 MUST).

    빈 문자열이나 "ACGIH" 같은 단어 하나는 출처가 아니다. 고시명·조항·개정일이
    들어가야 하므로 길이 하한을 DB 가 강제한다.
    """
    block = _table_block(_sql(), "exposure_limits")
    assert re.search(r"reference\s+TEXT\s+NOT\s+NULL", block, re.IGNORECASE), (
        "reference 가 NOT NULL 이 아니다"
    )
    assert "length(" in block.lower(), (
        "reference 길이 CHECK 가 없다 — 빈 문자열이나 한 단어가 통과한다"
    )


# ============================================================
# 활성 윈도우 유일성 — 애플리케이션이 아니라 DB 가 막는다
# ============================================================

def test_active_window_uniqueness_is_a_partial_index():
    """(worker, node, metric) 당 활성 윈도우는 하나뿐이어야 한다.

    윈도우가 둘로 갈라지면 한쪽에만 적산되어 누적량이 실제보다 작게 나오고,
    화면은 그것을 정상으로 표시한다. 배정 이벤트와 기동 복구가 동시에 윈도우를
    열려는 경합이 실제로 가능하므로 애플리케이션 검증으로는 부족하다.
    """
    sql = _sql()
    m = re.search(
        r"CREATE\s+UNIQUE\s+INDEX\s+IF\s+NOT\s+EXISTS\s+uq_exposure_state_active"
        r"\s+ON\s+exposure_state\s*\(([^)]*)\)\s*WHERE\s+([^;]+);",
        sql,
        re.IGNORECASE,
    )
    assert m, "uq_exposure_state_active 부분 유니크 인덱스가 없다"

    columns = {c.strip().lower() for c in m.group(1).split(",")}
    assert columns == {"worker_id", "node_id", "metric"}, (
        f"인덱스 컬럼이 사양(§6.3)과 다르다: {columns}"
    )

    # 부분 인덱스가 아니면 종료된 과거 윈도우까지 유일성에 걸려 두 번째 교대를
    # 시작할 수 없게 된다.
    assert re.search(r"closed_at\s+IS\s+NULL", m.group(2), re.IGNORECASE), (
        "WHERE closed_at IS NULL 조건이 없다 — 과거 윈도우가 재배정을 막는다"
    )


# ============================================================
# 지표 문자열 — sensor_data 와 어긋나면 조인이 깨진다
# ============================================================

def test_metric_check_matches_sensor_data_vocabulary():
    sql = _sql()
    for table in TABLES:
        block = _table_block(sql, table)
        m = re.search(r"metric\s+IN\s*\(([^)]*)\)", block, re.IGNORECASE)
        assert m, f"{table}: metric CHECK 제약이 없다"
        values = set(re.findall(r"'([^']+)'", m.group(1)))
        assert values == EXPECTED_METRICS, (
            f"{table}: metric 목록이 sensor_data 어휘와 다르다. "
            f"기대 {sorted(EXPECTED_METRICS)}, 실제 {sorted(values)}"
        )


def test_alert_level_vocabulary_matches_alert_rules():
    """06_ALERT_RULES.md 의 등급 문자열을 그대로 재사용해야 한다.

    여기만 다른 이름을 쓰면 경보 이력과 노출 이력을 나란히 놓고 볼 수 없다.
    """
    block = _table_block(_sql(), "exposure_shift_log")
    m = re.search(r"max_alert_level\s+IN\s*\(([^)]*)\)", block, re.IGNORECASE)
    assert m, "max_alert_level CHECK 가 없다"
    values = set(re.findall(r"'([^']+)'", m.group(1)))
    assert values == {
        "normal",
        "level1_caution",
        "level2_warning",
        "level3_critical",
    }, f"등급 문자열이 06_ALERT_RULES 와 다르다: {sorted(values)}"


# ============================================================
# 이력 보존 — 사람이 지워져도 기록은 남는다
# ============================================================

def test_shift_log_does_not_cascade_from_workers():
    """exposure_shift_log 는 workers 로 FK 를 걸지 않는다.

    비정규화(worker_name)는 실수가 아니라 의도다. FK + CASCADE 로 묶으면 퇴사
    처리 한 번에 사고 기록이 함께 지워진다. 노출 이력은 사후 조사와 분쟁의
    근거라 사람 레코드보다 오래 살아야 한다.
    """
    block = _table_block(_sql(), "exposure_shift_log")
    assert not re.search(r"REFERENCES\s+workers", block, re.IGNORECASE), (
        "exposure_shift_log 에 workers FK 가 걸렸다 — 작업자 삭제 시 이력이 사라진다"
    )
    assert re.search(r"worker_name\s+TEXT\s+NOT\s+NULL", block, re.IGNORECASE), (
        "worker_name 비정규화 컬럼이 없다"
    )


def test_active_state_cascades_from_workers():
    """반대로 exposure_state 는 CASCADE 가 맞다.

    활성 적산 상태는 작업 중인 사람에 딸린 임시 상태다. 사람이 사라지면 남아 있을
    이유가 없고, 남아 있으면 uq_exposure_state_active 가 다음 배정을 막는다.
    """
    block = _table_block(_sql(), "exposure_state")
    assert re.search(
        r"worker_id\s+BIGINT\s+NOT\s+NULL\s+REFERENCES\s+workers\s*\(\s*id\s*\)"
        r"\s+ON\s+DELETE\s+CASCADE",
        block,
        re.IGNORECASE,
    ), "exposure_state.worker_id 의 FK/CASCADE 가 사양(§6.3)과 다르다"


# ============================================================
# 누적값의 성질
# ============================================================

def test_accumulated_totals_cannot_go_negative():
    """누적값은 단조 증가한다 (§5.2). 음수는 적산 로직이 깨졌다는 뜻이다."""
    block = _table_block(_sql(), "exposure_state")
    m = re.search(r"CHECK\s*\((.*?dose_ppm_min\s*>=\s*0.*?)\)\s*\)", block, re.DOTALL | re.IGNORECASE)
    assert m or "dose_ppm_min >= 0" in block, (
        "dose_ppm_min 음수 방지 CHECK 가 없다"
    )
    for column in ("o2_deficient_s", "o2_severe_s", "o2_enriched_s", "data_gap_s"):
        assert f"{column} >= 0" in block, f"{column} 음수 방지 CHECK 가 없다"


def test_data_gap_column_exists():
    """측정 공백은 dose 를 과소평가하는 방향이라 반드시 별도로 기록한다 (§4.2 MUST).

    공백을 0 으로 간주하면 안전 시스템에서 최악의 오류가 된다.
    """
    block = _table_block(_sql(), "exposure_state")
    assert re.search(r"data_gap_s\s+INTEGER\s+NOT\s+NULL", block, re.IGNORECASE), (
        "exposure_state.data_gap_s 가 없거나 NULL 을 허용한다"
    )
