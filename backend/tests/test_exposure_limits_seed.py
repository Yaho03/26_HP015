"""011_exposure_limits.sql 시드의 정적 안전 규약.

**이 테스트들은 고시 원문을 검증하지 않는다. 검증할 수 없다.**

숫자가 고용노동부고시와 같은지는 원문을 펼쳐 본 사람만 판단할 수 있고, 그 확인
기록은 docs/EXPOSURE_LIMITS_VERIFICATION.md 에 있다. 여기서 하는 일은 다르다 —
**한번 확인된 숫자가 조용히 바뀌는 것을 막는다.**

구분이 중요하다. 앞선 버전의 이 파일은 테스트 이름이
`test_seed_values_match_ministry_annex...` 였고 내용은 SQL 문자열이 자기 자신과
같은지 보는 것이었다. 통과해도 "고시와 일치함"을 뜻하지 않는데 이름은 그렇게
읽힌다. 안전 기준값에서 그런 이름은 검증을 했다는 착각을 만든다.

그래서 여기서는
  - 이름이 하는 일을 그대로 말하고 (pinned = 고정, verified = 확인 아님),
  - 문자열 대조 대신 SQL 을 **파싱해서** 값을 꺼내 산술을 검사하며,
  - DB CHECK 제약을 정적으로 한 번 더 건다 (DB 도착 전에 깨지도록).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.models.exposure import EXPOSURE_METRICS


MIGRATION = (
    Path(__file__).resolve().parent.parent / "migrations" / "011_exposure_limits.sql"
)

# 8시간 교대 = 480분. dose_limit_ppm_min 은 법정값이 아니라 TWA x 480 파생값이다
# (11_EXPOSURE_DOSE_SPEC §2.1, 011 헤더 주석). 백엔드에 상수로 없는 이유는
# twa_8h_ppm() 이 실제 경과시간으로 나누기 때문이다 — 480 은 기준값 파생에만 쓴다.
SHIFT_MINUTES = 480

# 확인된 시드값. 바꾸려면 docs/EXPOSURE_LIMITS_VERIFICATION.md 의 재확인 절차를
# 먼저 밟아야 한다. 이 상수를 고치는 것만으로 테스트가 통과하지만, 그 편집은
# diff 에 남아 리뷰에서 반드시 눈에 띈다 — 그게 이 pin 의 목적이다.
PINNED = {
    "co2_ppm": (5000.0, 30000.0, "124-38-9"),
    "co_ppm": (30.0, 200.0, "630-08-0"),
    "h2s_ppm": (10.0, 15.0, "7783-06-4"),
}

# VALUES 목록의 한 행. 컬럼 목록 (metric, twa_limit_ppm, ...) 과
# ON CONFLICT (metric) 은 따옴표/숫자가 없어 걸리지 않는다.
_ROW = re.compile(
    r"\(\s*'(?P<metric>\w+)'\s*,"
    r"\s*(?P<twa>[\d.]+)\s*,"
    r"\s*(?P<dose>[\d.]+)\s*,"
    r"\s*(?P<stel>[\d.]+)\s*,"
    r"\s*'(?P<reference>[^']*)'\s*\)"
)


def _sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def _seeded() -> dict[str, dict]:
    """시드 SQL 에서 실제 값을 파싱해 꺼낸다.

    substring 검사와 달리, 값이 어느 컬럼에 들어갔는지까지 확인된다. 컬럼 순서가
    바뀌면 (twa 와 stel 이 뒤집히는 식) 문자열 대조로는 안 잡히고 여기서 잡힌다.
    """
    rows = {
        m.group("metric"): {
            "twa": float(m.group("twa")),
            "dose": float(m.group("dose")),
            "stel": float(m.group("stel")),
            "reference": m.group("reference"),
        }
        for m in _ROW.finditer(" ".join(_sql().split()))
    }
    assert rows, "시드 SQL 에서 VALUES 행을 하나도 파싱하지 못했다 — 정규식과 SQL 형식이 어긋났다"
    return rows


def test_seed_migration_keeps_010_for_evacuation():
    """번호를 011 로 둔 것은 우연이 아니다.

    008 은 main 의 login_lockout, 010 은 세션 B(탈출 경로)가 예약했다. 러너는
    파일명 키라 번호가 비어도 문제없지만, 되쓰면 두 브랜치가 머지될 때 같은
    파일명이 서로 다른 내용으로 충돌한다.
    """
    assert MIGRATION.exists()
    assert MIGRATION.name.startswith("011_")


def test_seed_covers_only_accumulating_metrics():
    """O2 는 여기 없어야 한다.

    O2 결핍은 ppm·min 축적이 아니라 시간(초) 기반 지표다 (§2.2). twa_limit_ppm 에
    19.5 같은 값을 넣으면 dose_fraction 이 산출되면서 화면이 "산소 노출량 x%"라는
    존재하지 않는 개념을 그린다.
    """
    seeded = set(_seeded())
    assert seeded == {"co2_ppm", "co_ppm", "h2s_ppm"}
    assert "o2_pct" not in seeded
    # metric 문자열은 새로 짓는 게 아니라 EXPOSURE_METRICS 를 따른다 (§2.3).
    # 이름이 바뀌면 조인이 조용히 빈 결과를 낸다.
    assert seeded < set(EXPOSURE_METRICS)


@pytest.mark.parametrize("metric", sorted(PINNED))
def test_seed_values_are_pinned_against_silent_edits(metric):
    """확인된 TWA/STEL 이 바뀌면 여기서 깨진다.

    통과가 "고시와 일치한다"는 뜻은 **아니다**. "마지막으로 사람이 확인한
    값에서 바뀌지 않았다"는 뜻이다.
    """
    twa, stel, _cas = PINNED[metric]
    row = _seeded()[metric]
    assert row["twa"] == twa
    assert row["stel"] == stel


@pytest.mark.parametrize("metric", sorted(PINNED))
def test_dose_limit_is_derived_from_twa_not_chosen_independently(metric):
    """dose_limit_ppm_min == twa_limit_ppm x 480 을 산술로 확인한다.

    009 가 이 컬럼을 생성 컬럼으로 묶지 않고 남겨둔 대가다 — 두 값이 어긋나지
    않는지 확인할 책임이 시드 쪽에 있다고 009 헤더가 명시했고, 그 책임이 실제로
    이행되는 지점이 여기다. 어긋나면 게이지 소진율이 TWA 표시와 다른 기준을
    쓰게 되는데, 화면에서는 계산 버그로 보인다.
    """
    row = _seeded()[metric]
    assert row["dose"] == row["twa"] * SHIFT_MINUTES


@pytest.mark.parametrize("metric", sorted(PINNED))
def test_every_seed_carries_primary_source_and_cas_number(metric):
    """출처 없는 기준값은 기준값이 아니다 (§3.3 MUST).

    CAS 번호까지 요구하는 이유는 고시 별표에 이름이 비슷한 물질이 여럿이라
    물질명만으로는 어느 행을 봤는지 확정되지 않기 때문이다.
    """
    _twa, _stel, cas = PINNED[metric]
    reference = _seeded()[metric]["reference"]
    assert "제2020-48호" in reference
    assert "별표 1" in reference
    assert cas in reference


@pytest.mark.parametrize("metric", sorted(PINNED))
def test_reference_satisfies_the_database_length_check(metric):
    """DB CHECK(length(btrim(reference)) >= 10) 을 정적으로도 건다.

    DB 까지 가야 알 수 있으면 통합 테스트가 없는 환경에서는 마이그레이션이
    운영 부팅 중에 처음 실패한다.
    """
    assert len(_seeded()[metric]["reference"].strip()) >= 10


def test_seed_is_idempotent_and_updates_all_safety_values():
    """재적용 시 값 하나라도 빠지면 DB 에 구버전 기준이 남는다.

    ON CONFLICT DO NOTHING 이었다면 기준값 정정 마이그레이션이 조용히 무시된다.
    """
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


def test_verification_record_exists_and_names_every_seeded_metric():
    """시드와 확인 기록이 같이 움직이게 묶는다.

    기록 없는 시드는 P0-A 이전 상태와 구분되지 않는다. 새 물질을 시드하면서
    기록에 안 적으면 여기서 깨진다.
    """
    record = (
        Path(__file__).resolve().parents[2] / "docs" / "EXPOSURE_LIMITS_VERIFICATION.md"
    )
    assert record.exists(), "docs/EXPOSURE_LIMITS_VERIFICATION.md 가 없다"
    text = record.read_text(encoding="utf-8")
    for metric, (_twa, _stel, cas) in PINNED.items():
        assert metric in text
        assert cas in text
