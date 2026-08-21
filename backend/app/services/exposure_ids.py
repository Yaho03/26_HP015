"""노출 윈도우 식별자 (ULID) — 의존성 없는 순수 모듈.

리포지토리 안에 두지 않고 떼어낸 이유는 검증이다. `exposure_repository` 는 pydantic 과
asyncpg 를 import 하는데 이 저장소에는 둘 다 설치돼 있지 않아서 모듈을 불러올 수조차
없다. 그 안에 있는 유일한 실제 로직이 ID 생성이므로, 여기로 옮겨 단독으로 돌려본다.
"""
from __future__ import annotations

import os
import time

#: Crockford Base32 — ULID 표준 알파벳.
#: I, L, O, U 가 빠져 있어 1/I 와 0/O 를 혼동하지 않는다. 사고 조사에서 ID 를 눈으로
#: 대조하는 일이 실제로 있으므로 이 성질이 그냥 장식이 아니다.
CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

TIME_CHARS = 10
RANDOM_CHARS = 16
ULID_LENGTH = TIME_CHARS + RANDOM_CHARS


def _encode(value: int, length: int) -> str:
    out = []
    for _ in range(length):
        out.append(CROCKFORD[value & 0x1F])
        value >>= 5
    return "".join(reversed(out))


def new_exposure_id(now_ms: int | None = None) -> str:
    """ULID 한 개 (11_EXPOSURE_DOSE_SPEC.md §2.3).

    UUID4 가 아니라 ULID 인 이유는 **시간순 정렬**이다. 앞 48비트가 밀리초
    타임스탬프라 문자열 정렬이 곧 발생 순서가 된다. 노출 윈도우는 사고 조사에서
    시간축으로 훑는 데이터라, 이 성질이 있으면 정렬 인덱스 없이도 눈으로 따라갈 수
    있다.

    외부 라이브러리를 더하지 않으려고 직접 만든다. 26자 = 시각 10자 + 난수 16자.

    :param now_ms: 테스트용 주입. 실제 호출에서는 비워 둔다.
    """
    timestamp_ms = int(time.time() * 1000) if now_ms is None else now_ms
    randomness = int.from_bytes(os.urandom(10), "big")
    return _encode(timestamp_ms, TIME_CHARS) + _encode(randomness, RANDOM_CHARS)
