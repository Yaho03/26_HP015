"""작업자 명부 + 배정 이력 DB 액세스 (이슈 #136).

핵심은 `assigned_at_time()` 이다. 경보를 조회할 때 "지금 누가 착용 중인가"가
아니라 "그 경보가 났을 때 누가 착용하고 있었나"를 답해야 한다. 배정이 바뀐 뒤에
과거 사고를 조회하면 엉뚱한 사람 이름이 붙기 때문이다.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

import asyncpg

from app.db import get_pool
from app.models.worker import AssignedWorker, Assignment, Worker, WorkerCreate, WorkerUpdate


class DuplicateEmployeeNo(Exception):
    """같은 사번이 이미 있다."""


class NodeAlreadyAssigned(Exception):
    """해당 노드에 이미 다른 작업자가 배정돼 있다."""


_WORKER_COLUMNS = "id, employee_no, name, phone, emergency_contact, created_at, updated_at"


async def list_all() -> List[Worker]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"SELECT {_WORKER_COLUMNS} FROM workers ORDER BY name, employee_no"
        )
        return [Worker(**dict(r)) for r in rows]


async def get(worker_id: int) -> Optional[Worker]:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"SELECT {_WORKER_COLUMNS} FROM workers WHERE id = $1", worker_id
        )
        return Worker(**dict(row)) if row else None


async def create(payload: WorkerCreate) -> Worker:
    pool = get_pool()
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                f"""
                INSERT INTO workers (employee_no, name, phone, emergency_contact)
                VALUES ($1, $2, $3, $4)
                RETURNING {_WORKER_COLUMNS}
                """,
                payload.employee_no, payload.name, payload.phone, payload.emergency_contact,
            )
        except asyncpg.UniqueViolationError as exc:
            raise DuplicateEmployeeNo(payload.employee_no) from exc
        return Worker(**dict(row))


async def update(worker_id: int, payload: WorkerUpdate) -> Optional[Worker]:
    """준 필드만 바꾼다. COALESCE 로 None 은 기존 값을 유지한다."""
    pool = get_pool()
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                f"""
                UPDATE workers SET
                    employee_no       = COALESCE($2, employee_no),
                    name              = COALESCE($3, name),
                    phone             = COALESCE($4, phone),
                    emergency_contact = COALESCE($5, emergency_contact),
                    updated_at        = now()
                WHERE id = $1
                RETURNING {_WORKER_COLUMNS}
                """,
                worker_id, payload.employee_no, payload.name,
                payload.phone, payload.emergency_contact,
            )
        except asyncpg.UniqueViolationError as exc:
            raise DuplicateEmployeeNo(payload.employee_no or "") from exc
        return Worker(**dict(row)) if row else None


async def delete(worker_id: int) -> bool:
    """작업자를 지운다. 배정 이력도 CASCADE 로 함께 지워진다."""
    pool = get_pool()
    async with pool.acquire() as conn:
        status = await conn.execute("DELETE FROM workers WHERE id = $1", worker_id)
        return status.endswith(" 1")


# ── 배정 ────────────────────────────────────────────────────────────────

async def assign(worker_id: int, node_id: str) -> Assignment:
    """작업자에게 노드를 배정한다.

    노드당 동시 1배정은 부분 유니크 인덱스가 강제한다. 여기서 미리 SELECT 해서
    검사하지 않는 이유는 두 요청이 동시에 들어오면 검사와 INSERT 사이가 벌어져
    둘 다 통과하기 때문이다. DB 가 거절하게 두고 예외를 번역한다.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                """
                INSERT INTO worker_assignments (worker_id, node_id)
                VALUES ($1, $2)
                RETURNING id, worker_id, node_id, assigned_at, released_at
                """,
                worker_id, node_id,
            )
        except asyncpg.UniqueViolationError as exc:
            raise NodeAlreadyAssigned(node_id) from exc
        return Assignment(**dict(row))


async def release(node_id: str) -> Optional[Assignment]:
    """노드의 현재 배정을 종료한다. 이력 행은 남긴다 (사고 조사용)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE worker_assignments SET released_at = now()
            WHERE node_id = $1 AND released_at IS NULL
            RETURNING id, worker_id, node_id, assigned_at, released_at
            """,
            node_id,
        )
        return Assignment(**dict(row)) if row else None


async def list_active() -> List[AssignedWorker]:
    """현재 착용 중인 배정 전체. 대시보드가 노드→사람 매핑을 그릴 때 쓴다."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT w.id AS worker_id, w.employee_no, w.name, w.phone,
                   w.emergency_contact, a.node_id, a.assigned_at
            FROM worker_assignments a
            JOIN workers w ON w.id = a.worker_id
            WHERE a.released_at IS NULL
            ORDER BY a.node_id
            """
        )
        return [AssignedWorker(**dict(r)) for r in rows]


async def assigned_at_time(node_id: str, at: datetime) -> Optional[AssignedWorker]:
    """`at` 시점에 `node_id` 를 착용하고 있던 작업자.

    경보 발생 시각을 넣으면 그 시점의 배정을 돌려준다. 배정이 바뀐 뒤에 과거
    경보를 조회해도 당시 사람이 나온다 — 이게 이 테이블을 시계열로 만든 이유다.

    경계: assigned_at <= at < released_at. released_at 을 배타로 두어야 배정을
    끝내고 곧바로 다른 사람에게 넘긴 순간에 두 명이 동시에 잡히지 않는다.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT w.id AS worker_id, w.employee_no, w.name, w.phone,
                   w.emergency_contact, a.node_id, a.assigned_at
            FROM worker_assignments a
            JOIN workers w ON w.id = a.worker_id
            WHERE a.node_id = $1
              AND a.assigned_at <= $2
              AND (a.released_at IS NULL OR a.released_at > $2)
            ORDER BY a.assigned_at DESC
            LIMIT 1
            """,
            node_id, at,
        )
        return AssignedWorker(**dict(row)) if row else None


async def history(node_id: str, limit: int = 50) -> List[Assignment]:
    """노드의 배정 이력. 최근 순."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, worker_id, node_id, assigned_at, released_at
            FROM worker_assignments
            WHERE node_id = $1
            ORDER BY assigned_at DESC
            LIMIT $2
            """,
            node_id, limit,
        )
        return [Assignment(**dict(r)) for r in rows]
