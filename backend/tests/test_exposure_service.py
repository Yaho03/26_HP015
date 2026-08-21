"""노출량 적산 서비스 배선 검증 (FR-701, §4.3 / §4.4 / §4.5).

DB·MQTT 없이 돌린다. 리포지토리와 위치 서비스를 대역으로 갈아끼워, 이 모듈이 실제로
책임지는 것만 본다 — **윈도우 수명주기**와 **어느 샘플을 누구에게 귀속시키는가**.

두 번째가 이 파일의 핵심이다. 최근접 노드를 잘못 고르면 작업자에게 엉뚱한 농도가
쌓이고, 그 누적은 되돌릴 수 없다.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models.exposure import ExposureStateRow
from app.services import exposure_service as svc

T0 = datetime(2026, 8, 21, 1, 0, 0, tzinfo=timezone.utc)

# uwb_anchors 기본값과 같은 배치 (config.py). A_n -> sensor-0n.
NODES = {
    "sensor-01": (0.0, 0.0),
    "sensor-02": (2.5, 0.0),
    "sensor-03": (2.5, 2.0),
    "sensor-04": (0.0, 2.0),
}


class _Assignment:
    def __init__(self, node_id="wearable-01", worker_id=7, name="홍길동"):
        self.node_id = node_id
        self.worker_id = worker_id
        self.name = name
        self.assigned_at = T0


class _Position:
    def __init__(self, x, y):
        self.x = x
        self.y = y
        self.z = 0.0


class _Filter:
    def __init__(self, positions: dict): self._p = positions
    def latest(self, node_id): return self._p.get(node_id)


class _Repo:
    """리포지토리 대역. 호출을 기록하고 메모리에서 윈도우를 만든다."""

    def __init__(self):
        self.opened: list[tuple] = []
        self.closed: list[tuple] = []
        self.flushed: list[list] = []
        self.refuse_open = False
        self._seq = 0

    def new_exposure_id(self):
        self._seq += 1
        return f"EXP{self._seq:04d}"

    async def load_limits(self):
        return {"co2_ppm": type("L", (), {"dose_limit_ppm_min": 2_400_000.0})()}

    async def load_active_states(self):
        return []

    async def open_window(self, exposure_id, worker_id, node_id, metric, start, source):
        self.opened.append((node_id, metric))
        if self.refuse_open:
            return None
        return ExposureStateRow(
            exposure_id=exposure_id, worker_id=worker_id, node_id=node_id,
            metric=metric, window_start=start, window_source=source,
        )

    async def close_window(self, state, final):
        self.closed.append((state.node_id, state.metric, final))

    async def flush_states(self, states):
        rows = list(states)
        self.flushed.append(rows)
        return len(rows)


@pytest.fixture
def env(monkeypatch):
    """서비스 모듈 상태를 매 테스트마다 초기화하고 의존성을 대역으로 바꾼다.

    **반드시 뒤에서도 비운다.** `_windows` 는 모듈 전역이라, 남겨두면 다음 테스트가
    아니라 *다른 파일*의 테스트가 깨진다 — lifespan 테스트가 종료 경로에서
    exposure_service.stop() 을 부르면서 남은 윈도우를 실제 DB 풀로 flush 하려 든다.
    실제로 밟은 회귀다.
    """
    fake_repo = _Repo()
    assignments = [_Assignment()]
    positions = {"wearable-01": _Position(0.2, 0.1)}  # sensor-01 이 최근접

    svc._windows.clear()
    svc._limits = {}
    svc._sensor_nodes = dict(NODES)

    monkeypatch.setattr(svc, "repo", fake_repo)
    monkeypatch.setattr(svc.worker_repository, "list_active", lambda: _aio(assignments))
    monkeypatch.setattr(svc.location_service, "get_filter", lambda: _Filter(positions))
    yield {"repo": fake_repo, "assignments": assignments, "positions": positions}

    svc._windows.clear()
    svc._limits = {}
    svc._sensor_nodes = {}


async def _aio(value):
    return value


# ============================================================
# §4.3 윈도우 수명주기
# ============================================================

@pytest.mark.asyncio
async def test_reconcile_opens_one_window_per_metric(env):
    """지표마다 윈도우가 따로 열린다 — 소진율도 경보도 지표별이다."""
    await svc._reconcile()
    assert set(env["repo"].opened) == {
        ("wearable-01", "co2_ppm"), ("wearable-01", "co_ppm"),
        ("wearable-01", "h2s_ppm"), ("wearable-01", "o2_pct"),
    }
    assert len(svc._windows) == 4


@pytest.mark.asyncio
async def test_reconcile_is_idempotent(env):
    """두 번 돌아도 윈도우를 다시 열지 않는다. 루프가 15초마다 부른다."""
    await svc._reconcile()
    env["repo"].opened.clear()
    await svc._reconcile()
    assert env["repo"].opened == []
    assert len(svc._windows) == 4


@pytest.mark.asyncio
async def test_reconcile_ignores_non_wearable_nodes(env):
    """노출은 사람에게 귀속된다 (§5.3). 센서 노드에는 윈도우가 열리지 않는다."""
    env["assignments"].append(_Assignment(node_id="sensor-01", worker_id=9))
    await svc._reconcile()
    assert all(node == "wearable-01" for node, _ in env["repo"].opened)


@pytest.mark.asyncio
async def test_reconcile_closes_window_when_assignment_ends(env):
    """배정이 끝나면 윈도우가 확정된다. 남겨두면 uq_exposure_state_active 가 다음
    배정을 막는다."""
    await svc._reconcile()
    env["assignments"].clear()
    await svc._reconcile()
    assert len(svc._windows) == 0
    assert len(env["repo"].closed) == 4


@pytest.mark.asyncio
async def test_close_records_no_alert_when_limit_unseeded(env):
    """기준값이 없으면 경보가 발령된 적이 없으므로 max_alert_level 은 normal 이
    사실이다. 판정 불가라는 사실은 같은 행의 dose_fraction IS NULL 이 전한다."""
    svc._limits = {}
    await svc._reconcile()
    env["assignments"].clear()
    await svc._reconcile()
    co2 = [f for node, metric, f in env["repo"].closed if metric == "co2_ppm"][0]
    assert co2.dose_fraction is None
    assert co2.max_alert_level == "normal"


# ============================================================
# 귀속 — 어느 노드의 농도가 누구에게 쌓이는가 (ADR-008)
# ============================================================

@pytest.mark.asyncio
async def test_gas_from_nearest_node_is_accumulated(env):
    await svc._reconcile()
    key = ("wearable-01", "co2_ppm")
    await svc.on_reading("sensor-01", "co2_ppm", 1000.0, T0)
    await svc.on_reading("sensor-01", "co2_ppm", 1000.0, T0 + timedelta(seconds=60))
    window = svc._windows[key]
    assert window.state.dose_ppm_min == pytest.approx(1000.0)
    assert window.source == "nearest_node"
    assert window.source_node_id == "sensor-01"
    assert window.dirty is True


@pytest.mark.asyncio
async def test_gas_from_far_node_is_not_accumulated(env):
    """최근접이 아닌 노드의 값을 쌓으면 엉뚱한 농도가 사람에게 귀속된다."""
    await svc._reconcile()
    await svc.on_reading("sensor-03", "co2_ppm", 9000.0, T0)
    await svc.on_reading("sensor-03", "co2_ppm", 9000.0, T0 + timedelta(seconds=60))
    assert svc._windows[("wearable-01", "co2_ppm")].state.dose_ppm_min == 0.0


@pytest.mark.asyncio
async def test_no_position_stops_accumulation_instead_of_guessing(env):
    """위치를 모르면 추측하지 않는다. 틀린 귀속은 되돌릴 수 없다."""
    await svc._reconcile()
    env["positions"].clear()
    await svc.on_reading("sensor-01", "co2_ppm", 1000.0, T0)
    await svc.on_reading("sensor-01", "co2_ppm", 1000.0, T0 + timedelta(seconds=60))
    window = svc._windows[("wearable-01", "co2_ppm")]
    assert window.state.dose_ppm_min == 0.0
    assert window.source == "unavailable"


@pytest.mark.asyncio
async def test_worker_movement_switches_source_node(env):
    """작업자가 옮겨가면 농도 출처도 따라간다."""
    await svc._reconcile()
    await svc.on_reading("sensor-01", "co2_ppm", 500.0, T0)
    env["positions"]["wearable-01"] = _Position(2.4, 1.9)  # sensor-03 근처
    await svc.on_reading("sensor-03", "co2_ppm", 500.0, T0 + timedelta(seconds=30))
    window = svc._windows[("wearable-01", "co2_ppm")]
    assert window.source_node_id == "sensor-03"
    assert window.state.dose_ppm_min > 0.0


@pytest.mark.asyncio
async def test_wearable_o2_uses_direct_source(env):
    """웨어러블 O2 는 대입이 아니라 직접 측정이라 항상 신뢰도가 높다 (§4.4)."""
    await svc._reconcile()
    await svc.on_reading("wearable-01", "o2_pct", 18.0, T0)
    await svc.on_reading("wearable-01", "o2_pct", 18.0, T0 + timedelta(seconds=60))
    window = svc._windows[("wearable-01", "o2_pct")]
    assert window.source == "wearable_direct"
    assert window.state.o2_deficient_s == pytest.approx(60.0)
    assert window.state.dose_ppm_min == 0.0, "O2 는 ppm·min 을 쌓지 않는다"


@pytest.mark.asyncio
async def test_gas_reading_does_not_touch_o2_window(env):
    await svc._reconcile()
    await svc.on_reading("sensor-01", "co2_ppm", 1000.0, T0)
    assert svc._windows[("wearable-01", "o2_pct")].dirty is False


@pytest.mark.asyncio
async def test_unknown_metric_is_ignored(env):
    """온도·습도는 노출량 대상이 아니다."""
    await svc._reconcile()
    await svc.on_reading("sensor-01", "temperature_c", 24.5, T0)
    assert all(not w.dirty for w in svc._windows.values())


@pytest.mark.asyncio
async def test_reading_without_any_window_is_a_noop(env):
    """배정이 없으면 쌓을 곳이 없다. 예외 없이 조용히 지나가야 한다."""
    await svc.on_reading("sensor-01", "co2_ppm", 1000.0, T0)
    assert svc._windows == {}


# ============================================================
# §4.5 flush
# ============================================================

@pytest.mark.asyncio
async def test_flush_writes_only_dirty_windows(env):
    await svc._reconcile()
    await svc.on_reading("sensor-01", "co2_ppm", 1000.0, T0)
    await svc._flush()
    assert len(env["repo"].flushed) == 1
    assert [r.metric for r in env["repo"].flushed[0]] == ["co2_ppm"]


@pytest.mark.asyncio
async def test_flush_clears_dirty_so_it_does_not_rewrite(env):
    await svc._reconcile()
    await svc.on_reading("sensor-01", "co2_ppm", 1000.0, T0)
    await svc._flush()
    await svc._flush()
    assert len(env["repo"].flushed) == 1, "변경 없는 윈도우를 다시 썼다"


@pytest.mark.asyncio
async def test_flush_snapshot_carries_accumulated_values(env):
    """flush 는 row 가 아니라 적산 상태를 저장해야 한다."""
    await svc._reconcile()
    await svc.on_reading("sensor-01", "co2_ppm", 1200.0, T0)
    await svc.on_reading("sensor-01", "co2_ppm", 1200.0, T0 + timedelta(seconds=60))
    await svc._flush()
    row = env["repo"].flushed[0][0]
    assert row.dose_ppm_min == pytest.approx(1200.0)
    assert row.last_value == 1200.0


@pytest.mark.asyncio
async def test_downtime_becomes_data_gap_not_dose(env):
    """복구된 윈도우의 last_sample_at 이 과거면 다음 샘플의 초과분이 data_gap 으로
    간다 (§4.2). 서비스가 다운타임을 따로 계산하지 않는 근거다."""
    await svc._reconcile()
    await svc.on_reading("sensor-01", "co2_ppm", 1000.0, T0)
    await svc.on_reading("sensor-01", "co2_ppm", 1000.0, T0 + timedelta(hours=3))
    window = svc._windows[("wearable-01", "co2_ppm")]
    assert window.state.dose_ppm_min == pytest.approx(1000.0), "3시간이 통째로 적산됐다"
    assert window.state.data_gap_s == pytest.approx(3 * 3600 - 60)
