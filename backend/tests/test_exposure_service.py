"""노출량 적산 서비스 배선 검증 (FR-701, §4.3 / §4.4 / §4.5).

DB·MQTT 없이 돌린다. 리포지토리와 위치 서비스를 대역으로 갈아끼워, 이 모듈이 실제로
책임지는 것만 본다 — **윈도우 수명주기**와 **어느 샘플을 누구에게 귀속시키는가**.

두 번째가 이 파일의 핵심이다. 최근접 노드를 잘못 고르면 작업자에게 엉뚱한 농도가
쌓이고, 그 누적은 되돌릴 수 없다.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from ulid import ULID

from app.models.exposure import ExposureStateRow
from app.services import exposure_service as svc

#: WS 계약. 스펙 문서가 아니라 **이 파일**이 프론트·펌웨어와의 계약이다.
SCHEMA_PATH = (
    Path(__file__).resolve().parents[2] / "schemas" / "worker-exposure.schema.json"
)

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
        # 진짜 ULID 를 쓴다. worker-exposure.schema.json 이 exposure_id 패턴을
        # 검사하므로, 가짜 ID 를 쓰면 스키마 검증 테스트가 통과할 수 없다.
        self._seq += 1
        return str(ULID())

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

    transitions: list = []

    async def _capture(t):
        transitions.append(t)

    from app.services import alert_service
    monkeypatch.setattr(alert_service, "handle_transition", _capture)

    monkeypatch.setattr(svc, "repo", fake_repo)
    monkeypatch.setattr(svc.worker_repository, "list_active", lambda: _aio(assignments))
    monkeypatch.setattr(svc.location_service, "get_filter", lambda: _Filter(positions))
    yield {
        "repo": fake_repo, "assignments": assignments,
        "positions": positions, "transitions": transitions,
    }

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
async def test_reassigning_the_wearable_does_not_reuse_the_previous_window(env):
    """웨어러블이 다른 작업자에게 넘어가면 윈도우를 새로 연다.

    `_windows` 는 (node_id, metric) 키라 착용자가 바뀌어도 같은 자리를 가리킨다.
    이전 구현은 키가 있으면 **worker_name 만 바꿔 달았고**, 그러면 B 의 노출이
    A 의 exposure_id·worker_id 에 쌓여 교대 로그가 worker_id=A / worker_name=B 라는
    자기모순인 행으로 확정된다. 누적은 되돌릴 수 없다.

    통합 테스트(`test_exposure_recovery.py`)가 다운타임 중 교대 경로를 실 DB 로
    검증하지만, DB 없이 도는 이 파일에도 둔다 — Docker 없이 돌릴 때도 이 보호가
    깨졌는지 알아야 한다.
    """
    await svc._reconcile()
    before = svc._windows[("wearable-01", "co2_ppm")].row.exposure_id
    env["repo"].closed.clear()

    env["assignments"][:] = [_Assignment(worker_id=9, name="김철수")]
    await svc._reconcile()

    window = svc._windows[("wearable-01", "co2_ppm")]
    assert window.row.worker_id == 9, "B 가 착용 중인데 A 에게 적산된다"
    assert window.row.exposure_id != before
    assert window.worker_name == "김철수"

    # A 의 기록은 확정되어 남는다. 이름은 A 의 것이어야 한다.
    finals = {(node, metric): f for node, metric, f in env["repo"].closed}
    assert set(finals) == {
        ("wearable-01", "co2_ppm"), ("wearable-01", "co_ppm"),
        ("wearable-01", "h2s_ppm"), ("wearable-01", "o2_pct"),
    }
    closed_co2 = finals[("wearable-01", "co2_ppm")]
    assert closed_co2.worker_id == 7
    assert closed_co2.worker_name == "홍길동", "A 의 교대 기록에 B 의 이름이 적혔다"


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


# ============================================================
# §5 경보 연동
# ============================================================

async def _push_dose(fraction: float, *, metric="co2_ppm", node="sensor-01"):
    """소진율이 fraction 이 되도록 농도를 밀어 넣는다 (기준 2,400,000 ppm·min).

    **60초 간격으로 여러 번** 넣어야 한다. 한 번에 긴 간격을 주면 gap_max_s 가
    구간을 60초로 자르고 나머지는 data_gap_s 로 가버려서 dose 가 안 쌓인다 (§4.2).
    적산기가 의도대로 동작하는 것이고, 그걸 모르고 짠 첫 버전이 틀렸었다.
    """
    ppm = 50_000.0
    steps = int(round(2_400_000.0 * fraction / ppm))
    for i in range(steps + 1):
        await svc.on_reading(node, metric, ppm, T0 + timedelta(seconds=60 * i))


@pytest.mark.asyncio
async def test_alert_uses_exposure_alert_key_not_metric(env):
    """§5.3 — alert_key 는 exposure_co2, metric 은 co2_ppm 으로 서로 달라야 한다."""
    svc._limits = await env["repo"].load_limits()
    await svc._reconcile()
    await _push_dose(0.6)
    t = env["transitions"][-1]
    assert t.alert_key == "exposure_co2"
    assert t.metric == "co2_ppm"


@pytest.mark.asyncio
async def test_alert_source_node_is_the_wearable_not_the_sensor(env):
    """§5.3 MUST — 노출은 사람에게 귀속된다. 센서 노드로 넣으면 대시보드에서
    센서 카드가 빨갛게 뜬다."""
    svc._limits = await env["repo"].load_limits()
    await svc._reconcile()
    await _push_dose(0.6)
    assert env["transitions"][-1].node_id == "wearable-01"


@pytest.mark.asyncio
async def test_alert_ladder_follows_fraction(env):
    svc._limits = await env["repo"].load_limits()
    await svc._reconcile()
    await _push_dose(0.6)
    assert env["transitions"][-1].to_level.value == "level1_caution"


@pytest.mark.asyncio
async def test_alert_never_goes_down_while_window_is_open(env):
    """§5.2 — 누적값은 줄지 않으므로 해제도 없다. 농도가 0 이 되어도 유지된다."""
    svc._limits = await env["repo"].load_limits()
    await svc._reconcile()
    await _push_dose(0.9)
    before = len(env["transitions"])
    assert env["transitions"][-1].to_level.value == "level2_warning"

    # 농도가 정상으로 돌아와도 새 전환(특히 하향)이 없어야 한다.
    for i in range(5):
        await svc.on_reading("sensor-01", "co2_ppm", 0.0,
                             T0 + timedelta(hours=2, minutes=i))
    assert len(env["transitions"]) == before, "노출량 경보가 저절로 내려갔다"
    assert svc._windows[("wearable-01", "co2_ppm")].emitted_level == "level2_warning"


@pytest.mark.asyncio
async def test_alert_is_emitted_once_per_level(env):
    """같은 등급을 반복 발행하면 대시보드가 계속 깜빡인다."""
    svc._limits = await env["repo"].load_limits()
    await svc._reconcile()
    await _push_dose(0.6)
    count = len([t for t in env["transitions"] if t.alert_key == "exposure_co2"])
    await svc.on_reading("sensor-01", "co2_ppm", 100.0, T0 + timedelta(hours=3))
    assert len([t for t in env["transitions"] if t.alert_key == "exposure_co2"]) == count


@pytest.mark.asyncio
async def test_no_alert_at_all_when_limit_unseeded(env):
    """§3.2 — 판정이 불가능하면 normal 조차 내보내지 않는다.

    normal 을 내보내면 "확인했고 정상"이라는 거짓 신호가 된다.
    """
    svc._limits = {}
    await svc._reconcile()
    await _push_dose(5.0)
    assert [t for t in env["transitions"] if t.metric == "co2_ppm"] == []


@pytest.mark.asyncio
async def test_o2_time_alert_uses_its_own_key(env):
    """§5.4 — 시간 누적 O2 경보는 순간값 o2_low 와 독립이다. 키가 달라야 한다."""
    await svc._reconcile()
    # 60초 간격으로 8번 = 결핍 420초 (L1 경계 300초 초과). 한 번에 400초를 주면
    # gap_max_s 가 60초로 자른다.
    for i in range(8):
        await svc.on_reading("wearable-01", "o2_pct", 18.0, T0 + timedelta(seconds=60 * i))
    o2 = [t for t in env["transitions"] if t.metric == "o2_pct"]
    assert o2, "O2 시간 누적 경보가 발령되지 않았다"
    assert o2[-1].alert_key == "o2_deficiency_time"
    assert o2[-1].to_level.value == "level1_caution"


@pytest.mark.asyncio
async def test_window_close_resolves_the_alert(env):
    """§5.2 — 해제는 윈도우 종료로만."""
    svc._limits = await env["repo"].load_limits()
    await svc._reconcile()
    await _push_dose(0.6)
    env["assignments"].clear()
    await svc._reconcile()
    resolved = [t for t in env["transitions"]
                if t.alert_key == "exposure_co2" and t.to_level.value == "normal"]
    assert len(resolved) == 1


@pytest.mark.asyncio
async def test_close_does_not_resolve_what_never_fired(env):
    """경보가 없던 윈도우를 닫으면서 해제 이벤트를 만들면 로그가 지저분해진다."""
    svc._limits = await env["repo"].load_limits()
    await svc._reconcile()
    env["assignments"].clear()
    await svc._reconcile()
    assert env["transitions"] == []


# ============================================================
# §6.1 WS 계약 — schemas/worker-exposure.schema.json
# ============================================================

def _validate(message: dict) -> None:
    """스키마 위반을 전부 모아서 보여준다. 하나씩 고치면 왕복이 길어진다."""
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema).iter_errors(message), key=lambda e: e.path
    )
    assert not errors, "\n".join(
        f"  {'/'.join(str(p) for p in e.path) or '(root)'}: {e.message}" for e in errors
    )


@pytest.mark.asyncio
async def test_snapshot_conforms_to_schema_when_active(env):
    """`additionalProperties: false` 라 필드를 하나만 잘못 넣어도 계약이 깨진다.

    사양서 §6.1 의 **예시**를 보고 페이로드를 만들었기 때문에 스키마와 실제로
    맞는지는 별개 문제다. 여기서 확인한다.
    """
    svc._limits = await env["repo"].load_limits()
    await svc._reconcile()
    await _push_dose(0.3)
    await svc.on_reading("wearable-01", "o2_pct", 18.0, T0)
    await svc.on_reading("wearable-01", "o2_pct", 18.0, T0 + timedelta(seconds=60))
    _validate(svc.snapshot("wearable-01"))


@pytest.mark.asyncio
async def test_snapshot_conforms_to_schema_when_limit_unseeded(env):
    """기준값 미시드 경로도 계약 안에 있어야 한다 (reason: limit_unverified)."""
    svc._limits = {}
    await svc._reconcile()
    await _push_dose(0.3)
    message = svc.snapshot("wearable-01")
    _validate(message)
    assert message["metrics"]["co2_ppm"] == {
        "status": "unavailable", "reason": "limit_unverified",
    }


@pytest.mark.asyncio
async def test_snapshot_conforms_to_schema_when_position_unknown(env):
    """위치를 모르는 경로도 계약 안에 있어야 한다 (reason: no_position)."""
    svc._limits = await env["repo"].load_limits()
    await svc._reconcile()
    env["positions"].clear()
    await svc.on_reading("sensor-01", "co2_ppm", 1000.0, T0)
    message = svc.snapshot("wearable-01")
    _validate(message)
    assert message["metrics"]["co2_ppm"]["reason"] == "no_position"


@pytest.mark.asyncio
async def test_snapshot_seconds_are_integers_not_floats(env):
    """적산기는 float 초로 계산하지만 계약은 integer 를 요구한다."""
    svc._limits = await env["repo"].load_limits()
    await svc._reconcile()
    await _push_dose(0.1)
    m = svc.snapshot("wearable-01")
    for field in ("elapsed_s", "accumulated_s", "data_gap_s"):
        assert isinstance(m[field], int), f"{field} 가 int 가 아니다: {type(m[field])}"
    o2 = m["metrics"]["o2_pct"]
    if o2["status"] == "active":
        for field in ("o2_deficient_s", "o2_severe_s", "o2_enriched_s"):
            assert isinstance(o2[field], int)


@pytest.mark.asyncio
async def test_snapshot_is_none_without_windows(env):
    assert svc.snapshot("wearable-01") is None
    assert svc.snapshot_all() == []


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
