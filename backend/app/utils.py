"""공용 유틸리티."""
from __future__ import annotations

from datetime import datetime, timezone


def to_iso_z(ts: datetime) -> str:
    """datetime을 ISO8601 'Z' 접미사 문자열로 변환.

    tz-naive는 UTC로 간주해 그냥 접미사만 붙인다. tz-aware(예: asyncpg가
    반환하는 UTC datetime)에 그냥 'Z'를 붙이면 isoformat()이 이미 만든
    '+00:00' 뒤에 또 붙어 '+00:00Z'라는 파싱 불가능한 이중 오프셋이 되므로,
    먼저 UTC로 정규화한 뒤 '+00:00'을 'Z'로 치환한다.
    (experiments/inject/envelope.py의 _iso()와 동일 로직)
    """
    if ts.tzinfo is None:
        return ts.isoformat() + "Z"
    return ts.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
