"""작업자 배정 통합 테스트 — 실제 DB (이슈 #136).

이 기능의 위험은 SQL 에 있다. 시점 조회 경계(assigned_at <= t < released_at)와
부분 유니크 인덱스는 mock 으로 검증할 수 없다 — 둘 다 DB 가 판정하는 것이다.

특히 "그 시점의 배정"이 틀리면 과거 사고 조회에서 **엉뚱한 사람 이름**이 나온다.
사고 조사가 통째로 무너지므로 경계값을 직접 확인한다.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models.worker import WorkerCreate, WorkerUpdate
from app.repositories import worker_repository as repo
from app.repositories.worker_repository import DuplicateEmployeeNo, NodeAlreadyAssigned

NODE = "wearable-itest-01"


@pytest.fixture
async def clean(db_pool):
    """이 테스트가 쓰는 행만 지운다. 다른 데이터는 건드리지 않는다."""
    async def _purge():
        async with db_pool.acquire() as c:
            await c.execute("DELETE FROM worker_assignments WHERE node_id LIKE 'wearable-itest-%'")
            await c.execute("DELETE FROM workers WHERE employee_no LIKE 'ITEST-%'")

    await _purge()
    yield
    await _purge()


async def _worker(no: str, name: str):
    return await repo.create(
        WorkerCreate(employee_no=f"ITEST-{no}", name=name, emergency_contact="010-0000-0000")
    )


# ── 명부 ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_and_read_worker(db_pool, clean):
    created = await _worker("001", "김안전")
    assert created.id > 0
    assert created.name == "김안전"

    fetched = await repo.get(created.id)
    assert fetched is not None and fetched.employee_no == "ITEST-001"


@pytest.mark.asyncio
async def test_duplicate_employee_no_rejected(db_pool, clean):
    """사번 중복은 DB 유니크 인덱스가 막는다."""
    await _worker("001", "김안전")
    with pytest.raises(DuplicateEmployeeNo):
        await _worker("001", "다른사람")


@pytest.mark.asyncio
async def test_partial_update_keeps_other_fields(db_pool, clean):
    w = await _worker("002", "이감독")
    updated = await repo.update(w.id, WorkerUpdate(phone="010-1111-2222"))
    assert updated is not None
    assert updated.phone == "010-1111-2222"
    assert updated.name == "이감독", "주지 않은 필드가 지워지면 안 된다"
    assert updated.emergency_contact == "010-0000-0000"


# ── 배정 제약 ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_one_node_cannot_hold_two_workers(db_pool, clean):
    """★ 완료 조건 — 한 노드에 두 작업자 동시 배정이 DB 제약으로 거부된다."""
    a = await _worker("010", "작업자A")
    b = await _worker("011", "작업자B")

    await repo.assign(a.id, NODE)
    with pytest.raises(NodeAlreadyAssigned):
        await repo.assign(b.id, NODE)


@pytest.mark.asyncio
async def test_release_then_reassign_is_allowed(db_pool, clean):
    """배정을 끝내면 같은 노드를 다른 사람에게 넘길 수 있다.
    부분 유니크 인덱스가 released_at IS NULL 에만 걸리는지 확인한다."""
    a = await _worker("020", "작업자A")
    b = await _worker("021", "작업자B")

    await repo.assign(a.id, NODE)
    released = await repo.release(NODE)
    assert released is not None and released.released_at is not None

    await repo.assign(b.id, NODE)  # 예외가 나면 실패
    active = await repo.list_active()
    holders = [w.name for w in active if w.node_id == NODE]
    assert holders == ["작업자B"]


@pytest.mark.asyncio
async def test_release_without_assignment_returns_none(db_pool, clean):
    assert await repo.release("wearable-itest-nobody") is None


# ── 시점 조회 (이 기능의 핵심) ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_point_in_time_returns_the_worker_of_that_moment(db_pool, clean):
    """★ 완료 조건 — 배정 이력이 바뀐 뒤 과거를 조회하면 '당시 작업자'가 나온다.

    A 가 착용 → 해제 → B 가 착용. A 구간의 시각으로 조회하면 B 가 아니라 A 다.
    """
    a = await _worker("030", "먼저작업자")
    b = await _worker("031", "나중작업자")

    now = datetime.now(timezone.utc)
    async with db_pool.acquire() as c:
        # 시각을 직접 넣어 구간을 만든다. now-60m ~ now-30m 은 A, now-30m 부터는 B.
        await c.execute(
            """INSERT INTO worker_assignments (worker_id, node_id, assigned_at, released_at)
               VALUES ($1, $2, $3, $4)""",
            a.id, NODE, now - timedelta(minutes=60), now - timedelta(minutes=30),
        )
        await c.execute(
            """INSERT INTO worker_assignments (worker_id, node_id, assigned_at)
               VALUES ($1, $2, $3)""",
            b.id, NODE, now - timedelta(minutes=30),
        )

    during_a = await repo.assigned_at_time(NODE, now - timedelta(minutes=45))
    assert during_a is not None and during_a.name == "먼저작업자"

    during_b = await repo.assigned_at_time(NODE, now - timedelta(minutes=10))
    assert during_b is not None and during_b.name == "나중작업자"


@pytest.mark.asyncio
async def test_point_in_time_boundary_is_half_open(db_pool, clean):
    """경계는 assigned_at <= t < released_at 이다.

    교대 순간에 두 명이 동시에 잡히면 경보가 누구를 지목할지 비결정적이 된다.
    해제 시각 정각에는 다음 사람이 나와야 한다.
    """
    a = await _worker("040", "교대전")
    b = await _worker("041", "교대후")

    now = datetime.now(timezone.utc)
    switch = now - timedelta(minutes=10)
    async with db_pool.acquire() as c:
        await c.execute(
            """INSERT INTO worker_assignments (worker_id, node_id, assigned_at, released_at)
               VALUES ($1, $2, $3, $4)""",
            a.id, NODE, now - timedelta(minutes=40), switch,
        )
        await c.execute(
            """INSERT INTO worker_assignments (worker_id, node_id, assigned_at)
               VALUES ($1, $2, $3)""",
            b.id, NODE, switch,
        )

    at_switch = await repo.assigned_at_time(NODE, switch)
    assert at_switch is not None and at_switch.name == "교대후", "정각은 다음 배정에 속한다"

    just_before = await repo.assigned_at_time(NODE, switch - timedelta(milliseconds=1))
    assert just_before is not None and just_before.name == "교대전"


@pytest.mark.asyncio
async def test_point_in_time_before_any_assignment_is_none(db_pool, clean):
    """배정 이력이 시작되기 전 시각에는 아무도 없다 — 없는 사람을 지어내면 안 된다."""
    a = await _worker("050", "작업자")
    await repo.assign(a.id, NODE)

    long_ago = datetime.now(timezone.utc) - timedelta(days=7)
    assert await repo.assigned_at_time(NODE, long_ago) is None


@pytest.mark.asyncio
async def test_alert_query_attaches_worker_of_that_moment(db_pool, clean):
    """★ 완료 조건 — 경보 조회가 '당시 작업자'를 붙인다.

    A 구간에 경보 하나, B 구간에 경보 하나를 넣고 각각 다른 이름이 붙는지 본다.
    LATERAL 조인 문법과 시점 경계가 실제 DB 에서 도는지도 여기서 확인된다.
    """
    from app.repositories import alert_events_repository

    a = await _worker("070", "당시작업자")
    b = await _worker("071", "이후작업자")

    now = datetime.now(timezone.utc)
    switch = now - timedelta(minutes=20)
    async with db_pool.acquire() as c:
        await c.execute(
            """INSERT INTO worker_assignments (worker_id, node_id, assigned_at, released_at)
               VALUES ($1, $2, $3, $4)""",
            a.id, NODE, now - timedelta(minutes=60), switch,
        )
        await c.execute(
            """INSERT INTO worker_assignments (worker_id, node_id, assigned_at)
               VALUES ($1, $2, $3)""",
            b.id, NODE, switch,
        )
        for suffix, activated in (("old", now - timedelta(minutes=40)),
                                  ("new", now - timedelta(minutes=5))):
            await c.execute(
                """INSERT INTO alert_events (message_id, schema_version, alert_id,
                       source_node_id, alert_key, alert_type, level, trigger_value,
                       threshold, metric, message, status, activated_at, published_at)
                   VALUES ($1,'1.1',$2,$3,'o2_low','o2_low','level3_critical',16.2,16.0,
                           'o2_pct','테스트','active',$4,now())""",
                f"ITEST-MSG-{suffix}", f"ITEST-ALERT-{suffix}", NODE, activated,
            )

    try:
        rows = await alert_events_repository.query(node_id=NODE, limit=10)
        by_id = {r["message_id"]: r for r in rows}
        assert by_id["ITEST-MSG-old"]["worker_name"] == "당시작업자"
        assert by_id["ITEST-MSG-new"]["worker_name"] == "이후작업자"
        assert by_id["ITEST-MSG-old"]["worker_employee_no"] == "ITEST-070"
    finally:
        async with db_pool.acquire() as c:
            await c.execute("DELETE FROM alert_events WHERE message_id LIKE 'ITEST-MSG-%'")


@pytest.mark.asyncio
async def test_alert_query_without_assignment_still_returns_rows(db_pool, clean):
    """배정 이력이 없는 경보도 그대로 나온다 (LEFT JOIN). 기존 데이터가 사라지면 안 된다."""
    from app.repositories import alert_events_repository

    async with db_pool.acquire() as c:
        await c.execute(
            """INSERT INTO alert_events (message_id, schema_version, alert_id,
                   source_node_id, alert_key, alert_type, level, trigger_value,
                   threshold, metric, message, status, activated_at, published_at)
               VALUES ('ITEST-MSG-bare','1.1','ITEST-ALERT-bare',$1,'co2_ppm',
                       'gas_threshold','level2_warning',2100,2000,'co2_ppm',
                       '테스트','active',now(),now())""",
            NODE,
        )
    try:
        rows = await alert_events_repository.query(node_id=NODE, limit=10)
        bare = next(r for r in rows if r["message_id"] == "ITEST-MSG-bare")
        assert bare["worker_name"] is None
        assert bare["level"] == "level2_warning", "경보 자체는 온전해야 한다"
    finally:
        async with db_pool.acquire() as c:
            await c.execute("DELETE FROM alert_events WHERE message_id LIKE 'ITEST-MSG-%'")


@pytest.mark.asyncio
async def test_deleting_worker_removes_assignment_history(db_pool, clean):
    """CASCADE 확인. 참조가 남으면 조회 시 JOIN 이 끊긴 행이 생긴다."""
    a = await _worker("060", "삭제대상")
    await repo.assign(a.id, NODE)

    assert await repo.delete(a.id) is True
    async with db_pool.acquire() as c:
        left = await c.fetchval(
            "SELECT count(*) FROM worker_assignments WHERE node_id = $1", NODE
        )
    assert left == 0
