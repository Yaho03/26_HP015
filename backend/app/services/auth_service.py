"""인증 서비스 — 해싱·세션 발급/검증/폐기 (AUTH-2, 이슈 #132).

정책 (ADR-007, FR-601~611):
- Argon2id 해싱 (argon2-cffi 직접 사용 — passlib 은 의존성만 추가한다).
- 세션 토큰: 32바이트 urlsafe. DB 에는 SHA-256 해시만 저장.
- 만료: 절대 12h (expires_at), 유휴 8h (last_seen_at 기준).
- 계정 열거 방지: 없는 계정에도 더미 해시 검증을 수행해 응답 시간을 맞춘다.
"""
from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.config import settings
from app.repositories import user_repository
from app.repositories.user_repository import UserRow

_hasher = PasswordHasher()  # 기본 매개변수가 Argon2id 다.

# 계정 열거 방지용 더미 해시 — 없는 계정 로그인도 해시 검증 1회를 수행한다.
# verify_mismatch 가 아닌 다른 예외(argon2 라이브러리 내부 오류)를 피하려고
# 실제 포맷의 고정 해시를 쓴다.
_DUMMY_HASH = _hasher.hash("timing-mask-placeholder")


class InvalidCredentials(Exception):
    """사용자명/비밀번호 불일치. 어떤 쪽이 틀렸는지 노출하지 않는다."""


class SessionExpired(Exception):
    """유휴/절대 만료. 401 로 응답한다."""


@dataclass
class IssuedSession:
    token: str
    csrf_token: str
    user: UserRow


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False
    except Exception:
        # 손상된 해시 등 — 검증 실패로 취급 (인증 거부가 안전 기본값).
        return False


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def login(username: str, password: str) -> IssuedSession:
    """자격 증명 검증 + 세션 발급.

    계정이 없어도 verify_password 를 1회 돌린다 — 로그인 실패 응답 시간으로
    "계정 존재 여부"를 추측하게 두지 않는다 (FR-609).
    """
    user = await user_repository.get_by_username(username)
    if user is None:
        verify_password(password, _DUMMY_HASH)
        raise InvalidCredentials()
    if not verify_password(password, user.password_hash):
        raise InvalidCredentials()
    if not user.is_active:
        # 비활성 계정도 동일 예외 — 응답으로 계정 존재를 알리지 않는다.
        raise InvalidCredentials()

    token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(
        hours=settings.session_absolute_ttl_hours
    )
    await user_repository.create_session(
        user.id, hash_token(token), csrf_token, expires_at
    )
    return IssuedSession(token=token, csrf_token=csrf_token, user=user)


@dataclass
class ValidSession:
    session_id: int
    csrf_token: str
    user: UserRow


async def validate_session(token: str) -> ValidSession:
    """세션 토큰 검증. 유휴 만료를 함께 판정하고 last_seen_at 을 갱신한다.

    절대 만료는 SQL(expires_at)이 이미 걸러준다. 유휴 만료는 여기서
    last_seen_at + idle TTL 로 판정한다.
    """
    row = await user_repository.find_active_session(hash_token(token))
    if row is None:
        raise SessionExpired()

    now = datetime.now(timezone.utc)
    if now - row["last_seen_at"] > timedelta(hours=settings.session_idle_ttl_hours):
        raise SessionExpired()

    user = UserRow(
        {
            "id": row["user_id"],
            "username": row["username"],
            # 서비스 계층 내부(비밀번호 변경 검증)에서만 쓴다. UserOut 변환
            # 시점에 떨어져 나가 응답에는 절대 나가지 않는다.
            "password_hash": row["password_hash"],
            "display_name": row["display_name"],
            "role": row["role"],
            "is_active": row["is_active"],
            "must_change_password": row["must_change_password"],
        }
    )
    if not user.is_active:
        raise SessionExpired()

    await user_repository.touch_session(row["session_id"], now)
    return ValidSession(session_id=row["session_id"], csrf_token=row["csrf_token"], user=user)


async def logout(token: str) -> None:
    await user_repository.revoke_session(hash_token(token))


async def change_password(user: UserRow, current_password: str, new_password: str) -> None:
    """비밀번호 변경. 성공 시 해당 사용자의 모든 세션을 폐기한다 (재로그인)."""
    if not verify_password(current_password, user.password_hash):
        raise InvalidCredentials()
    await user_repository.update_password(user.id, hash_password(new_password))
    await user_repository.revoke_all_for_user(user.id)


def session_cookie_attributes() -> dict[str, object]:
    """Set-Cookie 에 붙일 속성 (ADR-007).

    HttpOnly: JS 에서 토큰 접근 차단 (XSS 방어)
    SameSite=Lax: CSRF 표면 축소 (double-submit 과 별개의 1차 방어)
    Secure: 운영(HTTPS)에서만. settings.cookie_secure 로 제어.
    """
    return {
        "httponly": True,
        "samesite": "lax",
        "secure": settings.cookie_secure,
        "path": "/",
        "max_age": int(settings.session_absolute_ttl_hours * 3600),
    }
