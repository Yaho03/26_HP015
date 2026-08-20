"""작업자 프로필 + 배정 데이터 모델 (이슈 #136, FR-306).

작업자는 대시보드 계정이 아니다. 로그인하지 않고 밀폐공간에 들어가는 사람이며,
시스템은 이 사람을 경보에 이름으로 등장시키기 위해서만 안다. 그래서 비밀번호나
권한 필드가 없다 — 인증(#132)과 독립적으로 동작한다.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class WorkerBase(BaseModel):
    employee_no: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=64)
    phone: str | None = Field(None, max_length=32)
    emergency_contact: str | None = Field(None, max_length=64)


class WorkerCreate(WorkerBase):
    """POST /api/workers 요청 바디."""


class WorkerUpdate(BaseModel):
    """PATCH /api/workers/{id} 요청 바디. 준 필드만 바꾼다."""

    employee_no: str | None = Field(None, min_length=1, max_length=64)
    name: str | None = Field(None, min_length=1, max_length=64)
    phone: str | None = Field(None, max_length=32)
    emergency_contact: str | None = Field(None, max_length=64)


class Worker(WorkerBase):
    """workers 테이블 한 행."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime | None = None
    updated_at: datetime | None = None


class Assignment(BaseModel):
    """worker_assignments 한 행. released_at 이 None 이면 현재 착용 중."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    worker_id: int
    node_id: str
    assigned_at: datetime
    released_at: datetime | None = None


class AssignmentCreate(BaseModel):
    """POST /api/workers/{id}/assign 요청 바디."""

    node_id: str = Field(..., min_length=1, max_length=64)


class AssignedWorker(BaseModel):
    """어떤 시점에 특정 노드를 착용하고 있던 작업자.

    경보 메시지·조회 응답에 실어 보내는 형태다. 이름과 사번만으로는 대피 지시를
    못 하므로 비상연락처를 함께 준다.
    """

    model_config = ConfigDict(from_attributes=True)

    worker_id: int
    employee_no: str
    name: str
    phone: str | None = None
    emergency_contact: str | None = None
    node_id: str
    assigned_at: datetime
