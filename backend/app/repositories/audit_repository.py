"""감사 로그(audit_log) 기록/조회 (AUTH-5, 이슈 #135; FR-605).

기록 대상: 로그인 성공/실패, 로그아웃, 비밀번호 변경, 임계값 수정(전/후 값),
작업자 명부/배정 변경. 사용자 관리 이벤트는 UsersScreen(#140)과 함께 붙는다.

설계 원칙:
1. 감사 기록 실패가 본 기능을 깨면 안 된다 — record() 는 예외를 삼키지 않고
   로그만 남긴다(서비스 계층에서 통제). 단, 호출부는 await 하되 try 밖에 둔다.
2. actor_name 은 비정규화 — 계정이 삭제돼도 행위자 추적이 가능해야 한다.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, List, Optional

from app.db import get_pool

logger = logging.getLogger(__name__)


async def record(
    actor_id: Optional[int],
    actor_name: str,
    action: str,
    target: str = "",
    detail: Optional[dict[str, Any]] = None,
) -> None:
    """감사 이벤트 1건 기록. 실패해도 예외를 밖으로 던지지 않는다.

    감사 쓰기가 실패했다고 임계값 변경을 거부하면, 감사가 오히려 안전
    운영을 막는 역설이 생긴다. 대신 error 로그로 실패 사실을 남긴다.
    """
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO audit_log (actor_id, actor_name, action, target, detail)
                VALUES ($1, $2, $3, $4, $5::jsonb)
                """,
                actor_id, actor_name, action, target,
                json.dumps(detail or {}),
            )
    except Exception:
        logger.exception(
            "audit record failed (action=%s actor=%s target=%s) — 본 기능은 계속된다",
            action, actor_name, target,
        )


async def query(
    *,
    action: Optional[str] = None,
    actor_name: Optional[str] = None,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    limit: int = 200,
) -> List[dict]:
    """감사 로그 조회 (GET /api/audit-log). 최신순.

    action 은 전방 일치(action LIKE 'login%')로 필터링해 login.success /
    login.failure 를 함께 잡을 수 있게 한다.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, actor_id, actor_name, action, target, detail, created_at
            FROM audit_log
            WHERE ($1::text IS NULL OR action LIKE $1 || '%')
              AND ($2::text IS NULL OR actor_name = $2)
              AND ($3::timestamptz IS NULL OR created_at >= $3)
              AND ($4::timestamptz IS NULL OR created_at < $4)
            ORDER BY created_at DESC, id DESC
            LIMIT $5
            """,
            action, actor_name, start, end, limit,
        )
        result = []
        for r in rows:
            item = dict(r)
            item["detail"] = json.loads(item["detail"]) if item["detail"] else {}
            result.append(item)
        return result
