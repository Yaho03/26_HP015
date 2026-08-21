"""검증된 노출기준 시드 마이그레이션의 정적 안전 규약."""
from pathlib import Path


MIGRATION = (
    Path(__file__).resolve().parent.parent
    / "migrations"
    / "011_exposure_limits.sql"
)


def _sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def test_seed_migration_exists_and_keeps_010_for_evacuation():
    assert MIGRATION.exists()
    assert MIGRATION.name.startswith("011_")


def test_seed_contains_only_verified_accumulated_metrics():
    sql = _sql()
    assert "'co2_ppm'" in sql
    assert "'co_ppm'" in sql
    assert "'h2s_ppm'" in sql
    assert "'o2_pct'" not in sql


def test_seed_values_match_ministry_annex_and_derive_eight_hour_dose():
    sql = " ".join(_sql().split())
    assert "'co2_ppm', 5000, 2400000, 30000" in sql
    assert "'co_ppm', 30, 14400, 200" in sql
    assert "'h2s_ppm', 10, 4800, 15" in sql


def test_every_seed_has_primary_source_identity_and_cas_number():
    sql = _sql()
    assert sql.count("제2020-48호") >= 4
    assert "124-38-9" in sql
    assert "630-08-0" in sql
    assert "7783-06-4" in sql


def test_seed_is_idempotent_and_updates_all_safety_values():
    sql = _sql()
    assert "ON CONFLICT (metric) DO UPDATE" in sql
    for column in (
        "twa_limit_ppm",
        "dose_limit_ppm_min",
        "stel_limit_ppm",
        "reference",
        "updated_at",
    ):
        assert f"{column} =" in sql
