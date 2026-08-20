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
