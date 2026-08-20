"""사용자 계정·세션 데이터 모델 (AUTH-2, 이슈 #132).

UserOut 은 API 응답 전용 모델이며 password_hash 필드가 아예 없다 —
"응답에서 빼는" 것이 아니라 "모델에 없는" 것이다 (FR-603: 해시가 응답·로그에
등장하지 않음). 실수로 dict 를 통째로 반환해도 노출 경로가 없다.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class UserOut(BaseModel):
    """API 응답용 사용자. 비밀번호 해시 없음."""

    id: int
    username: str
    display_name: str
    role: str = Field(..., pattern="^(admin|supervisor|viewer)$")
    is_active: bool
    must_change_password: bool


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=256)


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=256)
    new_password: str = Field(..., min_length=8, max_length=256)


class SessionInfo(BaseModel):
    """세션 발급 결과 — 로그인 응답 바디. 토큰 원문은 쿠키로만 전달한다."""

    user: UserOut
    csrf_token: str


# ── 사용자 관리 (AUTH-10, 이슈 #140) ────────────────────────────────────


class UserAdminOut(UserOut):
    """관리자용 사용자 응답 — 잠금 상태 포함. 해시는 여전히 없다."""

    failed_login_attempts: int
    locked_until: datetime | None


class UserCreateRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(..., min_length=8, max_length=256)
    role: str = Field("viewer", pattern="^(admin|supervisor|viewer)$")
    display_name: str = Field("", max_length=64)


class UserUpdateRequest(BaseModel):
    role: str | None = Field(None, pattern="^(admin|supervisor|viewer)$")
    is_active: bool | None = None


class PasswordResetResult(BaseModel):
    """비밀번호 초기화 — 임시 비밀번호는 이 응답으로 1회만 보여준다."""

    user: UserAdminOut
    temporary_password: str
