"""alert_events 로그 조회 repository (이슈 #60)."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from app.db import get_pool


async def has_active_alerts_at_or_above(level: str) -> bool:
    """활성 L2+ 경보 존재 여부 (AUTH-7/이슈 #137 — 세션 유휴 연장 판정).

    level 은 하한: 'level2_warning' 을 주면 L2+L3, 'level3_critical' 이면 L3.
    경보 규칙상 level 문자열 정렬이 위험도 순과 일치한다
    (level1_caution < level2_warning < level3_critical).
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            SELECT EXISTS(
                SELECT 1 FROM alert_events
                WHERE status = 'active' AND level >= $1
            )
            """,
            level,
        )


async def query(
    *,
    node_id: Optional[str] = None,
    alert_key: Optional[str] = None,
    status: Optional[str] = None,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    limit: int = 100,
) -> List[dict]:
    pool = get_pool()
    conditions = []
    args: list = []
    idx = 1

    # 컬럼명을 e. 로 한정한다 — 아래에서 worker 조인이 붙으면서 이름이 겹칠 여지가 생겼다.
    if node_id:
        conditions.append(f"e.source_node_id = ${idx}")
        args.append(node_id)
        idx += 1
    if alert_key:
        conditions.append(f"e.alert_key = ${idx}")
        args.append(alert_key)
        idx += 1
    if status:
        conditions.append(f"e.status = ${idx}")
        args.append(status)
        idx += 1
    if start:
        conditions.append(f"e.activated_at >= ${idx}")
        args.append(start)
        idx += 1
    if end:
        conditions.append(f"e.activated_at <= ${idx}")
        args.append(end)
        idx += 1

    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    args.append(limit)

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT e.message_id, e.alert_id, e.source_node_id, e.alert_key, e.alert_type,
                   e.level, e.trigger_value, e.threshold, e.metric, e.message, e.status,
                   e.schema_version, e.activated_at, e.resolved_at, e.published_at,
                   w.worker_id, w.worker_name, w.worker_employee_no,
                   w.worker_emergency_contact
            FROM alert_events e
            -- 이슈 #136 — "지금 누가 착용 중인가"가 아니라 "이 경보가 났을 때 누가
            -- 착용하고 있었나"를 붙인다. 배정이 바뀐 뒤 과거 사고를 조회해도 당시
            -- 사람이 나와야 사고 조사가 성립한다.
            -- LEFT JOIN 이라 배정 이력이 없는 경보(기존 데이터 포함)는 그대로 나온다.
            LEFT JOIN LATERAL (
                SELECT wk.id           AS worker_id,
                       wk.name         AS worker_name,
                       wk.employee_no  AS worker_employee_no,
                       wk.emergency_contact AS worker_emergency_contact
                FROM worker_assignments a
                JOIN workers wk ON wk.id = a.worker_id
                WHERE a.node_id = e.source_node_id
                  AND a.assigned_at <= e.activated_at
                  AND (a.released_at IS NULL OR a.released_at > e.activated_at)
                ORDER BY a.assigned_at DESC
                LIMIT 1
            ) w ON TRUE
            {where_clause}
            ORDER BY e.activated_at DESC
            LIMIT ${idx}
            """,
            *args,
        )
        return [dict(r) for r in rows]
