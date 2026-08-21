"""노출 윈도우 ULID 검증 (§2.3).

pytest 를 import 하지 않는다 — 이 저장소에는 pytest 도 venv 도 없어서 `python` 으로
직접 호출해 돌릴 수 있어야 실제로 검증이 된다. pytest 가 들어오면 그대로 수집된다.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.exposure_ids import (  # noqa: E402
    CROCKFORD,
    ULID_LENGTH,
    new_exposure_id,
)


def test_length_is_26():
    assert len(new_exposure_id()) == ULID_LENGTH == 26


def test_alphabet_is_crockford_base32():
    """I, L, O, U 가 나오면 안 된다 — 사람이 눈으로 대조할 때 혼동한다."""
    allowed = set(CROCKFORD)
    for _ in range(200):
        assert set(new_exposure_id()) <= allowed
    for banned in "ILOU":
        assert banned not in CROCKFORD


def test_lexicographic_order_follows_time():
    """문자열 정렬이 곧 발생 순서여야 한다. ULID 를 고른 유일한 이유다.

    UUID4 였다면 이 성질이 없어서, 사고 조사에서 시간축으로 훑을 때 정렬 인덱스에
    의존해야 한다.
    """
    earlier = new_exposure_id(now_ms=1_700_000_000_000)
    later = new_exposure_id(now_ms=1_700_000_001_000)
    assert earlier < later

    # 밀리초 1 차이도 구분되어야 한다.
    a = new_exposure_id(now_ms=1_700_000_000_000)
    b = new_exposure_id(now_ms=1_700_000_000_001)
    assert a[:10] < b[:10]


def test_same_millisecond_ids_are_distinct():
    """같은 밀리초에 여러 윈도우가 열려도 충돌하면 안 된다."""
    ids = {new_exposure_id(now_ms=1_700_000_000_000) for _ in range(2000)}
    assert len(ids) == 2000


def test_time_prefix_is_stable_for_same_timestamp():
    """앞 10자는 시각만으로 결정된다 — 난수가 시각 부분을 오염시키지 않는다."""
    prefixes = {new_exposure_id(now_ms=1_700_000_000_000)[:10] for _ in range(50)}
    assert len(prefixes) == 1
