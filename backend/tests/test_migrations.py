"""이슈 #98: migration 스크립트 idempotency 보강 — TDD 테스트.

검증 범위:
1. 정적 검사 — 모든 DDL이 idempotency 가드(IF NOT EXISTS / CREATE OR REPLACE / if_not_exists => TRUE)를 사용
2. 마이그레이션 러너 단위 테스트 — schema_migrations 추적 + 미적용 파일만 순차 적용 + checksum 변조 감지

DB 없이 검증 가능한 부분만 단위 테스트로 작성.
Testcontainers 통합 테스트(실제 두 번 실행)는 #84 CI 구축 시 추가.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


# ============================================================
# 1. 정적 검사 — 모든 DDL 구문이 idempotency 가드를 포함하는지
# ============================================================

def _sql_files() -> list[Path]:
    """migrations/ 디렉토리의 모든 .sql 파일을 번호순으로 반환."""
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


def _strip_sql_comments(sql: str) -> str:
    """SQL 주석(-- ...)과 블록 주록(/* ... */)을 제거해 순수 DDL만 남긴다.
    문자열 리터럴 내의 -- 는 주석이 아님을 고려해야 하지만 현재 마이그레이션
    파일에는 DDL 문자열에 -- 가 없으므로 단순 라인 단위 처리로 충분."""
    lines = []
    for line in sql.splitlines():
        stripped = line.strip()
        if stripped.startswith("--"):
            continue
        # 라인 중간의 -- 주석 제거 (문자열 내 -- 가 없다는 가정)
        if "--" in line:
            line = line.split("--", 1)[0]
        lines.append(line)
    return "\n".join(lines)


def test_migrations_dir_has_files():
    """migrations/ 디렉토리에 최소 1개 이상의 .sql 파일이 존재해야 한다."""
    files = _sql_files()
    assert len(files) > 0, "migrations/ 디렉토리에 .sql 파일이 없습니다"
    # 001_init.sql 은 항상 존재해야 한다
    names = [f.name for f in files]
    assert "001_init.sql" in names


@pytest.mark.parametrize("sql_file", _sql_files(), ids=lambda f: f.name)
def test_create_table_has_if_not_exists(sql_file: Path):
    """모든 CREATE TABLE 구문은 IF NOT EXISTS 가드를 포함해야 한다."""
    sql = _strip_sql_comments(sql_file.read_text())
    # CREATE TABLE [IF NOT EXISTS] name ...
    pattern = re.compile(r"CREATE\s+TABLE\s+(?!IF\s+NOT\s+EXISTS)", re.IGNORECASE)
    matches = pattern.findall(sql)
    assert not matches, (
        f"{sql_file.name}: IF NOT EXISTS 없는 CREATE TABLE 발견. "
        f"재실행 시 객체 충돌로 실패할 수 있다."
    )


@pytest.mark.parametrize("sql_file", _sql_files(), ids=lambda f: f.name)
def test_create_index_has_if_not_exists(sql_file: Path):
    """모든 CREATE [UNIQUE] INDEX 구문은 IF NOT EXISTS 가드를 포함해야 한다."""
    sql = _strip_sql_comments(sql_file.read_text())
    # CREATE [UNIQUE] INDEX [IF NOT EXISTS] name ...
    pattern = re.compile(r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?!IF\s+NOT\s+EXISTS)", re.IGNORECASE)
    matches = pattern.findall(sql)
    assert not matches, (
        f"{sql_file.name}: IF NOT EXISTS 없는 CREATE INDEX 발견."
    )


@pytest.mark.parametrize("sql_file", _sql_files(), ids=lambda f: f.name)
def test_create_materialized_view_has_if_not_exists(sql_file: Path):
    """CREATE MATERIALIZED VIEW 구문은 IF NOT EXISTS 를 포함해야 한다."""
    sql = _strip_sql_comments(sql_file.read_text())
    pattern = re.compile(
        r"CREATE\s+MATERIALIZED\s+VIEW\s+(?!IF\s+NOT\s+EXISTS)", re.IGNORECASE
    )
    matches = pattern.findall(sql)
    assert not matches, (
        f"{sql_file.name}: IF NOT EXISTS 없는 CREATE MATERIALIZED VIEW 발견."
    )


@pytest.mark.parametrize("sql_file", _sql_files(), ids=lambda f: f.name)
def test_create_extension_has_if_not_exists(sql_file: Path):
    """CREATE EXTENSION 구문은 IF NOT EXISTS 를 포함해야 한다."""
    sql = _strip_sql_comments(sql_file.read_text())
    pattern = re.compile(r"CREATE\s+EXTENSION\s+(?!IF\s+NOT\s+EXISTS)", re.IGNORECASE)
    matches = pattern.findall(sql)
    assert not matches, (
        f"{sql_file.name}: IF NOT EXISTS 없는 CREATE EXTENSION 발견."
    )


@pytest.mark.parametrize("sql_file", _sql_files(), ids=lambda f: f.name)
def test_alter_table_add_column_has_if_not_exists(sql_file: Path):
    """ALTER TABLE ... ADD COLUMN 구문은 IF NOT EXISTS 를 포함해야 한다."""
    sql = _strip_sql_comments(sql_file.read_text())
    # ALTER TABLE 이후 ADD COLUMN [IF NOT EXISTS]
    if not re.search(r"ALTER\s+TABLE", sql, re.IGNORECASE):
        return  # ADD COLUMN 없는 ALTER TABLE 이면 스킵
    pattern = re.compile(
        r"ADD\s+COLUMN\s+(?!IF\s+NOT\s+EXISTS)", re.IGNORECASE
    )
    matches = pattern.findall(sql)
    assert not matches, (
        f"{sql_file.name}: IF NOT EXISTS 없는 ADD COLUMN 발견."
    )


@pytest.mark.parametrize("sql_file", _sql_files(), ids=lambda f: f.name)
def test_timescaledb_functions_have_if_not_exists(sql_file: Path):
    """create_hypertable / add_continuous_aggregate_policy / add_retention_policy 호출은
    if_not_exists => TRUE 인자를 포함해야 한다."""
    sql = _strip_sql_comments(sql_file.read_text())
    for func in ("create_hypertable", "add_continuous_aggregate_policy", "add_retention_policy"):
        if func not in sql:
            continue
        # 함수 호출 단위로 분리해 if_not_exists => TRUE 가 있는지 검사
        # 단순화: 함수가 등장한 줄을 찾아 닫는 괄호까지 슬라이싱
        for m in re.finditer(re.escape(func) + r"\s*\(", sql):
            # 닫는 괄호를 찾아 인자 블록 추출
            start = m.end()
            depth = 1
            i = start
            while i < len(sql) and depth > 0:
                if sql[i] == "(":
                    depth += 1
                elif sql[i] == ")":
                    depth -= 1
                i += 1
            block = sql[start:i]
            assert "if_not_exists" in block, (
                f"{sql_file.name}: {func} 호출에 if_not_exists 인자가 없습니다."
            )


# ============================================================
# 2. 마이그레이션 러너 단위 테스트 — schema_migrations 추적
# ============================================================

class _FakeTx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeConn:
    """asyncpg.Connection 을 흉내내는 fake. DB 없이 러너 로직을 검증한다.

    executed: 실행된 SQL 문과 인자 리스트
    fetchrow_results: fetchrow 호출 시 반환할 값 매핑 (sql 패턴 → row dict)
    execute_results: execute 호출 시 반환할 영향받은 행 수 매핑
    """

    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple]] = []
        self._fetchrow_results: dict[str, dict] = {}
        self._execute_results: dict[str, str] = {}

    async def execute(self, sql: str, *args: object) -> str:
        self.executed.append((sql, args))
        for key, val in self._execute_results.items():
            if key in sql:
                return val
        return "INSERT 0 1"

    async def fetchrow(self, sql: str, *args: object):
        self.executed.append((sql, args))
        for key, val in self._fetchrow_results.items():
            if key in sql:
                return val
        return None

    def transaction(self):
        return _FakeTx()

    def set_fetchrow(self, sql_substr: str, row: dict) -> None:
        self._fetchrow_results[sql_substr] = row

    def set_execute(self, sql_substr: str, status: str) -> None:
        self._execute_results[sql_substr] = status


class FakePool:
    """asyncpg.Pool 의 async context manager 인터페이스를 흉내낸다."""

    def __init__(self, conn: FakeConn) -> None:
        self._conn = conn

    class _Acquired:
        def __init__(self, conn: FakeConn) -> None:
            self._conn = conn

        async def __aenter__(self):
            return self._conn

        async def __aexit__(self, *exc):
            return False

    def acquire(self):
        return self._Acquired(self._conn)


def _checksum(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def test_migration_runner_module_importable():
    """app.migration_runner 모듈이 존재하고 apply_all 함수가 있어야 한다."""
    from app import migration_runner
    assert hasattr(migration_runner, "apply_all")
    assert hasattr(migration_runner, "SCHEMA_MIGRATIONS_SQL")


@pytest.mark.asyncio
async def test_apply_all_creates_schema_migrations_table_first(tmp_path, monkeypatch):
    """apply_all()은 가장 먼저 schema_migrations 추적 테이블을 생성해야 한다."""
    from app import migration_runner

    conn = FakeConn()
    pool = FakePool(conn)
    monkeypatch.setattr(migration_runner, "get_pool", lambda: pool)
    monkeypatch.setattr(migration_runner, "_migrations_dir", lambda: tmp_path)

    # 빈 migrations 디렉토리 (러너 자체 테이블 생성만 검증)
    await migration_runner.apply_all()

    # 첫 실행 SQL 이 schema_migrations 테이블 생성이어야 한다
    assert len(conn.executed) > 0
    first_sql = conn.executed[0][0].upper()
    assert "CREATE TABLE" in first_sql
    assert "SCHEMA_MIGRATIONS" in first_sql


@pytest.mark.asyncio
async def test_apply_all_records_applied_migration(tmp_path, monkeypatch):
    """새로 적용한 마이그레이션 파일을 schema_migrations 에 기록해야 한다."""
    from app import migration_runner

    migration_file = tmp_path / "001_test.sql"
    migration_file.write_text("CREATE TABLE IF NOT EXISTS foo (id int);")

    conn = FakeConn()
    pool = FakePool(conn)
    # schema_migrations 조회 시 "아직 적용 안 됨" 반환
    conn.set_fetchrow(
        "SELECT",
        None,  # row 없음 → 새로 적용
    )
    monkeypatch.setattr(migration_runner, "get_pool", lambda: pool)
    monkeypatch.setattr(migration_runner, "_migrations_dir", lambda: tmp_path)

    await migration_runner.apply_all()

    # INSERT INTO schema_migrations 실행되어야 함
    insert_calls = [s for s, _ in conn.executed if "INSERT INTO SCHEMA_MIGRATIONS" in s.upper()]
    assert len(insert_calls) >= 1, "schema_migrations 에 INSERT 가 실행되지 않았다"


@pytest.mark.asyncio
async def test_apply_all_skips_already_applied(tmp_path, monkeypatch):
    """schema_migrations 에 이미 기록된 파일은 스킵해야 한다."""
    from app import migration_runner

    migration_file = tmp_path / "001_test.sql"
    migration_file.write_text("CREATE TABLE IF NOT EXISTS foo (id int);")

    conn = FakeConn()
    pool = FakePool(conn)
    # 이미 적용된 것으로 가정
    conn.set_fetchrow(
        "SELECT",
        {"filename": "001_test.sql", "checksum": _checksum(migration_file.read_text())},
    )
    monkeypatch.setattr(migration_runner, "get_pool", lambda: pool)
    monkeypatch.setattr(migration_runner, "_migrations_dir", lambda: tmp_path)

    await migration_runner.apply_all()

    # 마이그레이션 파일의 본문 SQL 은 실행되지 않아야 한다
    foo_executions = [
        s for s, _ in conn.executed if "CREATE TABLE" in s.upper() and "FOO" in s.upper()
    ]
    assert len(foo_executions) == 0, "이미 적용된 마이그레이션이 재실행되었다"


@pytest.mark.asyncio
async def test_apply_all_detects_checksum_mismatch(tmp_path, monkeypatch):
    """이미 적용된 파일의 내용이 변경되면(checksum 불일치) 에러를 발생해야 한다."""
    from app import migration_runner

    migration_file = tmp_path / "001_test.sql"
    migration_file.write_text("CREATE TABLE IF NOT EXISTS foo (id int);")

    conn = FakeConn()
    pool = FakePool(conn)
    # 다른 checksum 으로 "이미 적용됨" 반환
    conn.set_fetchrow(
        "SELECT",
        {"filename": "001_test.sql", "checksum": "different_checksum_value"},
    )
    monkeypatch.setattr(migration_runner, "get_pool", lambda: pool)
    monkeypatch.setattr(migration_runner, "_migrations_dir", lambda: tmp_path)

    with pytest.raises(Exception) as exc_info:
        await migration_runner.apply_all()
    assert "checksum" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_apply_all_applies_files_in_filename_order(tmp_path, monkeypatch):
    """파일은 번호(파일명) 순서대로 적용되어야 한다.
    검증 방법: schema_migrations INSERT 의 filename 인자 순서를 비교한다."""
    from app import migration_runner

    # 역순로 생성해도 파일명 정렬로 순서대로 적용되어야 한다
    for name, sql in [
        ("003_third.sql", "CREATE TABLE IF NOT EXISTS c (id int);"),
        ("001_first.sql", "CREATE TABLE IF NOT EXISTS a (id int);"),
        ("002_second.sql", "CREATE TABLE IF NOT EXISTS b (id int);"),
    ]:
        (tmp_path / name).write_text(sql)

    conn = FakeConn()
    pool = FakePool(conn)
    conn.set_fetchrow("SELECT", None)
    monkeypatch.setattr(migration_runner, "get_pool", lambda: pool)
    monkeypatch.setattr(migration_runner, "_migrations_dir", lambda: tmp_path)

    await migration_runner.apply_all()

    inserted_filenames = [
        args[0] for s, args in conn.executed
        if "INSERT INTO SCHEMA_MIGRATIONS" in s.upper() and args
    ]
    assert inserted_filenames == ["001_first.sql", "002_second.sql", "003_third.sql"], (
        f"잘못된 순서: {inserted_filenames}"
    )


@pytest.mark.asyncio
async def test_apply_all_skips_schema_migrations_file_from_normal_processing(tmp_path, monkeypatch):
    """000_schema_migrations.sql 파일은 일반 마이그레이션 처리 루프에서 스킵되어야 한다.
    (러너가 직접 처리하므로 일반 루프에서 중복 처리 금지)"""
    from app import migration_runner

    runner_file = tmp_path / "000_schema_migrations.sql"
    runner_file.write_text("CREATE TABLE IF NOT EXISTS schema_migrations (id int);")
    normal_file = tmp_path / "001_normal.sql"
    normal_file.write_text("CREATE TABLE IF NOT EXISTS foo (id int);")

    conn = FakeConn()
    pool = FakePool(conn)
    conn.set_fetchrow("SELECT", None)
    monkeypatch.setattr(migration_runner, "get_pool", lambda: pool)
    monkeypatch.setattr(migration_runner, "_migrations_dir", lambda: tmp_path)

    await migration_runner.apply_all()

    inserted_filenames = [
        args[0] for s, args in conn.executed
        if "INSERT INTO SCHEMA_MIGRATIONS" in s.upper() and args
    ]
    assert "000_schema_migrations.sql" not in inserted_filenames, (
        "000_schema_migrations.sql 이 일반 루프에서 중복 처리되었다"
    )
    assert "001_normal.sql" in inserted_filenames


def test_schema_migrations_sql_file_exists():
    """migrations/000_schema_migrations.sql 파일이 존재해야 한다."""
    expected = MIGRATIONS_DIR / "000_schema_migrations.sql"
    assert expected.exists(), "000_schema_migrations.sql 이 없다"


def test_schema_migrations_sql_table_schema():
    """schema_migrations 테이블은 filename, checksum, applied_at 컬럼을 가져야 한다."""
    from app import migration_runner
    sql = migration_runner.SCHEMA_MIGRATIONS_SQL.upper()
    assert "CREATE TABLE IF NOT EXISTS SCHEMA_MIGRATIONS" in sql
    assert "FILENAME" in sql
    assert "CHECKSUM" in sql
    assert "APPLIED_AT" in sql
    assert "PRIMARY KEY" in sql
