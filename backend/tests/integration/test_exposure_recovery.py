"""EXP-7.1 — 백엔드 재시작을 넘어 누적 노출량이 이어지는가 (FR-704, §4.5).

**왜 통합 테스트여야 하는가**

`test_exposure_service.py` 는 `load_active_states` 를 가짜로 바꿔 놓고 돈다. 그래서
"복구 경로가 호출된다"는 것까지만 확인되고, **실제 DB 에 적산 중이던 행이 남았을 때
dose 가 이어지는지**는 확인된 적이 없었다. FR-704 가 MUST 인데 그 구간이 비어 있었다.

여기서는 진짜 TimescaleDB 에 붙어 아래를 한 줄로 꿴다.

    적산 → flush → **메모리 전멸(프로세스 사망)** → _recover() → 이어서 적산

메모리를 비우는 것이 이 파일의 핵심이다. `_windows` 를 남겨두면 복구가 아니라 그냥
기존 상태를 다시 쓰는 것이라 아무것도 검증하지 못한다.

**무엇이 검증되지 않는가**: 실제 프로세스를 죽였다 살리는 것은 아니다. asyncio 루프,
컨테이너 재기동, 커넥션 풀 재생성은 이 테스트의 범위 밖이다. 검증되는 것은
"영속화된 상태만으로 적산을 재개할 수 있는가"다.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.config import settings
from app.repositories import exposure_repository as repo
from app.services import exposure_service as svc


T0 = datetime(2026, 8, 21, 1, 0, 0, tzinfo=timezone.utc)

#: 경보 임계에 한참 못 미치는 농도. 이 테스트가 보는 것은 경보가 아니라 연속성이다.
PPM = 1200.0

#: config.py 의 uwb_anchors 기본 배치와 같다 (A_n → sensor-0n).
NODES = {
    "sensor-01": (0.0, 0.0),
    "sensor-02": (2.5, 0.0),
    "sensor-03": (2.5, 2.0),
    "sensor-04": (0.0, 2.0),
}


class _SameConnectionPool:
    """repository 가 fixture 트랜잭션과 같은 연결을 쓰게 하는 최소 어댑터.

    풀에서 다른 연결을 잡으면 롤백 예정인 미커밋 데이터가 보이지 않는다.
    """

    def __init__(self, connection):
        self.connection = connection

    class _Acquire:
        def __init__(self, connection):
            self.connection = connection

        async def __aenter__(self):
            return self.connection

        async def __aexit__(self, *exc):
            return False

    def acquire(self):
        return self._Acquire(self.connection)


class _Assignment:
    def __init__(self, worker_id: int, node_id: str = "wearable-01", name: str = "홍길동"):
        self.node_id = node_id
        self.worker_id = worker_id
        self.name = name
        self.assigned_at = T0


class _Position:
    def __init__(self, x: float, y: float):
        self.x = x
        self.y = y
        self.z = 0.0


class _Filter:
    def __init__(self, positions: dict):
        self._p = positions

    def latest(self, node_id):
        return self._p.get(node_id)


@pytest.fixture
async def wired(conn, monkeypatch):
    """서비스를 실제 DB 에 붙이고, 그 밖의 subsystem 만 대역으로 바꾼다.

    `exposure_repository` 는 **진짜를 쓴다** — 이 테스트가 보려는 것이 바로 그 경로다.
    작업자 명부·측위·경보·WS 는 다른 기능의 책임이라 대역으로 둔다.
    """
    # 다른 작업자의 열린 윈도우를 치운다. `_recover()` 는 테이블 전체를 읽으므로
    # 잔여 행이 있으면 이 테스트가 그것까지 메모리에 올린다 — 실제로 이 DB 에는
    # EXP-8 지연 측정 스크립트가 커밋한 wearable-01 행이 남아 있었다.
    # 이 DELETE 는 fixture 트랜잭션 안이라 테스트가 끝나면 롤백된다.
    await conn.execute("DELETE FROM exposure_state")

    worker_id = await conn.fetchval(
        "INSERT INTO workers (employee_no, name) VALUES ($1, $2) RETURNING id",
        "EXP-7-1", "홍길동",
    )

    # 두 리포지토리 모두 같은 연결을 보게 한다. worker_repository 를 빼먹으면
    # 이름 조회가 다른 연결로 나가 미커밋 작업자를 못 본다.
    monkeypatch.setattr(repo, "get_pool", lambda: _SameConnectionPool(conn))
    monkeypatch.setattr(
        svc.worker_repository, "get_pool", lambda: _SameConnectionPool(conn)
    )

    assignments = [_Assignment(worker_id)]

    async def _list_active():
        return list(assignments)

    monkeypatch.setattr(svc.worker_repository, "list_active", _list_active)
    # sensor-01 이 최근접이 되는 위치.
    monkeypatch.setattr(
        svc.location_service, "get_filter",
        lambda: _Filter({"wearable-01": _Position(0.2, 0.1)}),
    )

    from app.services import alert_service

    async def _swallow(_transition):
        return None

    monkeypatch.setattr(alert_service, "handle_transition", _swallow)

    svc._windows.clear()
    svc._last_broadcast.clear()
    svc._sensor_nodes = dict(NODES)
    svc._limits = await repo.load_limits()

    yield {"worker_id": worker_id, "assignments": assignments}

    # 모듈 전역이라 반드시 비운다. 남기면 *다른 파일*의 테스트가 깨진다 —
    # lifespan 테스트가 stop() 에서 남은 윈도우를 실제 풀로 flush 하려 든다.
    svc._windows.clear()
    svc._last_broadcast.clear()
    svc._limits = {}
    svc._sensor_nodes = {}


async def _feed(offset_s: int) -> None:
    await svc.on_reading("sensor-01", "co2_ppm", PPM, T0 + timedelta(seconds=offset_s))


def _co2():
    return svc._windows[("wearable-01", "co2_ppm")]


async def _simulate_restart() -> None:
    """프로세스가 죽었다 살아난 것과 같은 상태를 만든다.

    `init()` 이 하는 순서 그대로 복구 → 조정이다. 조정까지 돌리는 이유는, 복구가
    되살린 윈도우를 조정이 **다시 열어버리면** 누적이 0 부터 시작하기 때문이다.
    """
    svc._windows.clear()
    svc._last_broadcast.clear()
    await svc._recover()
    await svc._reconcile()


@pytest.mark.asyncio
async def test_dose_survives_restart_and_keeps_accumulating(wired):
    """flush 된 누적값이 재기동 후에도 남고, 이어서 쌓인다."""
    await svc._reconcile()

    # 60초 간격 3샘플 → 사다리꼴로 1200 ppm·min 씩 두 구간. 첫 샘플은 적산하지 않는다.
    await _feed(0)
    await _feed(60)
    await _feed(120)
    assert _co2().state.dose_ppm_min == pytest.approx(2400.0)

    await svc._flush()
    exposure_id_before = _co2().row.exposure_id

    await _simulate_restart()

    window = _co2()
    assert window.state.dose_ppm_min == pytest.approx(2400.0), "재기동 후 누적이 0 으로 돌아갔다"
    assert window.row.exposure_id == exposure_id_before, (
        "윈도우가 새로 열렸다 — 교대 로그가 두 조각으로 갈라진다"
    )

    # 이어서 적산된다. 복구가 '읽기만' 하고 끝나면 여기서 드러난다.
    await _feed(180)
    assert _co2().state.dose_ppm_min == pytest.approx(3600.0)


@pytest.mark.asyncio
async def test_loss_is_bounded_by_the_last_flush(wired):
    """flush 되지 않은 증분만 잃는다 — 그 이상도, 그 이하도 아니다.

    §4.5 가 약속하는 손실 상한이 `flush_interval_s` 분량이라는 것의 실제 의미다.
    '이하'도 중요하다: 복구가 flush 안 된 값까지 되살린다면 그건 어딘가 다른 곳에
    상태가 새고 있다는 뜻이다.
    """
    await svc._reconcile()
    await _feed(0)
    await _feed(60)
    await _feed(120)
    await svc._flush()

    # flush 이후의 증분. 아직 DB 에 없다.
    await _feed(180)
    assert _co2().state.dose_ppm_min == pytest.approx(3600.0)
    assert _co2().dirty is True

    await _simulate_restart()

    assert _co2().state.dose_ppm_min == pytest.approx(2400.0)


@pytest.mark.asyncio
async def test_downtime_becomes_data_gap_not_dose(wired):
    """꺼져 있던 시간이 dose 로 둔갑하지 않는다 (§4.2).

    복구된 윈도우는 `last_sample_at` 이 과거로 남아 있다. 다음 샘플의 Δt 가
    `gap_max_s` 를 넘기므로 초과분은 전부 `data_gap_s` 로 가야 한다. 이걸 놓치면
    8시간 다운타임이 8시간치 노출로 기록된다.
    """
    await svc._reconcile()
    await _feed(0)
    await _feed(60)
    await _feed(120)
    await svc._flush()

    await _simulate_restart()
    assert _co2().state.data_gap_s == pytest.approx(0.0)

    # 880초 만에 재개. gap_max_s(기본 60초)를 넘는 820초는 공백이다.
    await _feed(1000)

    window = _co2()
    gap_max = settings.exposure_gap_max_s
    assert window.state.data_gap_s == pytest.approx(880.0 - gap_max)
    # 폭주했다면 2400 + 1200 * 880/60 = 20000 이 됐을 것이다.
    assert window.state.dose_ppm_min == pytest.approx(2400.0 + PPM * gap_max / 60.0)


@pytest.mark.asyncio
async def test_recovered_window_is_persisted_not_duplicated(wired, conn):
    """복구 후 flush 가 새 행을 만들지 않고 같은 행을 갱신한다.

    `uq_exposure_state_active` 가 막아주긴 하지만, 막혀서 예외가 나는 것과 애초에
    한 행만 쓰는 것은 다르다. 전자는 재기동마다 에러 로그가 쌓인다.
    """
    await svc._reconcile()
    await _feed(0)
    await _feed(60)
    await svc._flush()

    await _simulate_restart()
    await _feed(120)
    await svc._flush()

    # worker_id 로 좁힌다. 이 DB 에는 다른 작업자의 잔여 행이 있을 수 있고
    # (측정 스크립트가 커밋한다), 그건 이 테스트가 판단할 대상이 아니다.
    rows = await conn.fetch(
        """SELECT exposure_id, dose_ppm_min FROM exposure_state
           WHERE worker_id = $1 AND node_id = 'wearable-01'
             AND metric = 'co2_ppm' AND closed_at IS NULL""",
        wired["worker_id"],
    )
    assert len(rows) == 1, "재기동이 활성 윈도우를 하나 더 만들었다"
    assert rows[0]["dose_ppm_min"] == pytest.approx(2400.0)


@pytest.mark.asyncio
async def test_reassignment_during_downtime_does_not_inherit_previous_worker(wired, conn):
    """다운타임 중에 웨어러블이 다른 작업자에게 넘어가도 노출이 섞이지 않는다.

    `uq_exposure_state_active` 는 worker_id 를 포함한 키라, A 의 윈도우가 열린 채로
    B 의 윈도우가 또 열릴 수 있다. 그런데 `_windows` 는 (node_id, metric) 키라
    하나만 든다.

    이전 구현은 키가 이미 있으면 **worker_name 만 바꿔 달았다.** 그러면 B 의 노출이
    A 의 exposure_id·worker_id 에 쌓이고, 교대 로그는 worker_id=A / worker_name=B
    라는 자기모순인 행으로 확정된다. 누적은 되돌릴 수 없다.
    """
    await svc._reconcile()
    await _feed(0)
    await _feed(60)
    await _feed(120)
    await svc._flush()
    worker_a = wired["worker_id"]
    exposure_a = _co2().row.exposure_id

    # 백엔드가 꺼진 사이 같은 웨어러블이 B 에게 넘어갔다.
    worker_b = await conn.fetchval(
        "INSERT INTO workers (employee_no, name) VALUES ($1, $2) RETURNING id",
        "EXP-7-1-B", "김철수",
    )
    wired["assignments"][:] = [_Assignment(worker_b, name="김철수")]

    await _simulate_restart()

    window = _co2()
    assert window.row.worker_id == worker_b, "B 가 착용 중인데 A 에게 적산되고 있다"
    assert window.row.exposure_id != exposure_a
    assert window.state.dose_ppm_min == pytest.approx(0.0), (
        "B 의 윈도우가 A 의 누적을 물려받았다"
    )
    assert window.worker_name == "김철수"

    # A 의 기록은 사라지지 않는다 — 확정 로그로 넘어가야 한다.
    closed = await conn.fetchrow(
        """SELECT worker_id, worker_name, dose_ppm_min
           FROM exposure_shift_log WHERE exposure_id = $1""",
        exposure_a,
    )
    assert closed is not None, "A 의 윈도우가 확정되지 않고 사라졌다"
    assert closed["worker_id"] == worker_a
    assert closed["worker_name"] == "홍길동", "A 의 기록에 B 의 이름이 적혔다"
    assert closed["dose_ppm_min"] == pytest.approx(2400.0)


@pytest.mark.asyncio
async def test_recovery_keeps_window_when_assignment_is_gone(wired):
    """배정이 사라진 채로 재기동해도 누적을 잃지 않는다.

    복구가 배정 목록에 의존해 윈도우를 버리면, 배정 해제와 재기동이 겹친 작업자의
    교대 기록이 통째로 사라진다. 윈도우를 닫는 것은 `_reconcile()` 의 책임이고,
    닫힘은 `exposure_shift_log` 에 확정 기록을 남기는 경로여야 한다.
    """
    await svc._reconcile()
    await _feed(0)
    await _feed(60)
    await _feed(120)
    await svc._flush()

    wired["assignments"].clear()

    svc._windows.clear()
    svc._last_broadcast.clear()
    await svc._recover()

    window = svc._windows.get(("wearable-01", "co2_ppm"))
    assert window is not None, "배정이 없다고 활성 윈도우를 버렸다"
    assert window.state.dose_ppm_min == pytest.approx(2400.0)
    # 배정이 끝났어도 **이름은 남는다.** exposure_shift_log.worker_name 은 workers FK
    # 없이 비정규화된 컬럼이라, 여기에 "(배정 해제됨)" 같은 문자열이 들어가면 그
    # 교대에 누가 있었는지가 영구히 사라진다.
    assert window.worker_name == "홍길동"
