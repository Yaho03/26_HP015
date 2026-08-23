"""탈출 경로 API + 브로드캐스트 (FR-804/806/807, §4.1, §4.2).

경로 계산은 test_evacuation_router.py, 교체 판정은 test_evacuation_wiring.py 가
맡는다. 여기서는 "계산된 것이 밖으로 어떻게 나가는가"를 본다.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.models.alert import AlertLevel
from app.services import evacuation_service
from app.services.evacuation_router import Position2D
from app.services.evacuation_topology import load_topology_file

SCHEMA_PATH = (
    Path(__file__).resolve().parents[2] / "schemas" / "evacuation-route.schema.json"
)


@pytest.fixture
def topology():
    return load_topology_file()


@pytest.fixture(autouse=True)
def clean_state():
    evacuation_service.reset_for_test()
    evacuation_service._last_status.clear()
    yield
    evacuation_service.reset_for_test()
    evacuation_service._last_status.clear()


@pytest.fixture
def client():
    from app.main import app

    return TestClient(app)


def _seed_route(topology, position=Position2D(30.0, 0.0)):
    evacuation_service.set_topology(topology)
    active, _ = evacuation_service.compute_and_decide(
        "wearable-01", position, zones=[], hazard_data_available=True
    )
    return active


# ============================================================
# 1. 메시지 형태 — schemas/evacuation-route.schema.json
# ============================================================

def test_message_matches_the_published_schema(topology):
    """스키마와 어긋나면 프론트 타입이 조용히 틀어진다. 계약을 코드로 잠근다.

    스키마 파일은 아직 사양서 브랜치(PR #193)에만 있다. 그 PR 이 머지되면 이
    테스트가 저절로 살아난다 — 그때까지 실패로 두면 CI 가 늘 빨갛다.
    """
    if not SCHEMA_PATH.exists():
        pytest.skip(f"{SCHEMA_PATH.name} 이 이 브랜치에 없다 (PR #193 머지 대기)")
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    active = _seed_route(topology)
    message = evacuation_service.to_message("wearable-01", active)

    jsonschema.validate(message, schema, format_checker=jsonschema.FormatChecker())


def test_message_carries_ship_visual_and_the_level_assumption(topology):
    """프론트는 추가 비율 매핑 없이 Z-up → Y-up 축 변환만 한다 (ADR-010).
    좌표계가 다르게 오면 경로가 엉뚱한 자리에 그려진다."""
    active = _seed_route(topology)
    message = evacuation_service.to_message("wearable-01", active)

    assert message["coordinate_system"] == "ship-visual"
    assert message["assumed_level_id"] == "L0"


def test_unavailable_reason_is_only_present_when_unavailable(topology):
    """스키마가 additionalProperties: false 다. 빈 사유를 늘 실으면 검증이 깨진다."""
    active = _seed_route(topology)
    assert "unavailable_reason" not in evacuation_service.to_message("wearable-01", active)


# ============================================================
# 2. 발행 — 바뀔 때만 (§3.4)
# ============================================================

@pytest.mark.asyncio
async def test_position_update_publishes_once_then_stays_quiet(topology, monkeypatch):
    """같은 자리에 서 있는 사람에게 매 측위마다 경로를 다시 밀어내면 화면이
    깜빡이고 이력이 초당 몇 건씩 쌓인다."""
    evacuation_service.set_topology(topology)

    sent: list[dict] = []

    async def fake_broadcast(message):
        sent.append(message)

    async def fake_record(**_kwargs):
        return None

    monkeypatch.setattr(evacuation_service.manager, "broadcast", fake_broadcast)
    monkeypatch.setattr(evacuation_service.nav_repository, "record_route", fake_record)

    now = datetime.now(timezone.utc)
    for _ in range(5):
        await evacuation_service.on_position_update(
            "wearable-01", 1.25, 1.0, now, "demo-local"
        )

    assert len(sent) == 1
    assert sent[0]["type"] == "evacuation_route"
    assert sent[0]["node_id"] == "wearable-01"


@pytest.mark.asyncio
async def test_fixed_sensor_nodes_are_ignored(topology, monkeypatch):
    """고정 센서는 대피하지 않는다."""
    evacuation_service.set_topology(topology)
    sent: list[dict] = []

    async def fake_broadcast(message):
        sent.append(message)

    monkeypatch.setattr(evacuation_service.manager, "broadcast", fake_broadcast)

    await evacuation_service.on_position_update(
        "sensor-01", 1.25, 1.0, datetime.now(timezone.utc), "demo-local"
    )
    assert sent == []


@pytest.mark.asyncio
async def test_broadcast_failure_does_not_break_the_route(topology, monkeypatch):
    """구독자가 없거나 소켓이 죽은 것은 정상 상황이다. 경로 계산까지 멈추면 안 된다."""
    evacuation_service.set_topology(topology)

    async def boom(_message):
        raise RuntimeError("no clients")

    async def fake_record(**_kwargs):
        return None

    monkeypatch.setattr(evacuation_service.manager, "broadcast", boom)
    monkeypatch.setattr(evacuation_service.nav_repository, "record_route", fake_record)

    await evacuation_service.on_position_update(
        "wearable-01", 1.25, 1.0, datetime.now(timezone.utc), "demo-local"
    )
    assert evacuation_service.get_active_route("wearable-01") is not None


# ============================================================
# 3. no_safe_route 경보 (§3.5 MUST)
# ============================================================

@pytest.mark.asyncio
async def test_no_safe_route_raises_a_level3_alert_once(topology, monkeypatch):
    """화면을 보고 있지 않은 감독자에게도 닿아야 한다. 다만 재계산마다 발령하면
    같은 경보가 초당 몇 건씩 쌓인다 — 상태가 바뀔 때만이다."""
    evacuation_service.set_topology(topology)

    transitions = []

    async def fake_handle(transition):
        transitions.append(transition)

    monkeypatch.setattr(evacuation_service.alert_service, "handle_transition", fake_handle)

    blocked = _seed_route(topology)
    blocked.result.route_status = "no_safe_route"
    for _ in range(3):
        await evacuation_service._sync_no_safe_route_alert("wearable-01", blocked)

    assert len(transitions) == 1
    assert transitions[0].to_level == AlertLevel.LEVEL3
    # alert_key 는 metric 에서 나온다 (alert_publisher).
    assert transitions[0].metric == "no_safe_route"


@pytest.mark.asyncio
async def test_recovering_from_no_safe_route_clears_the_alert(topology, monkeypatch):
    evacuation_service.set_topology(topology)
    transitions = []

    async def fake_handle(transition):
        transitions.append(transition)

    monkeypatch.setattr(evacuation_service.alert_service, "handle_transition", fake_handle)

    active = _seed_route(topology)
    active.result.route_status = "no_safe_route"
    await evacuation_service._sync_no_safe_route_alert("wearable-01", active)

    active.result.route_status = "safe"
    await evacuation_service._sync_no_safe_route_alert("wearable-01", active)

    assert [t.to_level for t in transitions] == [AlertLevel.LEVEL3, AlertLevel.NORMAL]


@pytest.mark.asyncio
async def test_alert_failure_does_not_break_the_route(topology, monkeypatch):
    evacuation_service.set_topology(topology)

    async def boom(_transition):
        raise RuntimeError("mqtt down")

    monkeypatch.setattr(evacuation_service.alert_service, "handle_transition", boom)

    active = _seed_route(topology)
    active.result.route_status = "no_safe_route"
    await evacuation_service._sync_no_safe_route_alert("wearable-01", active)  # 예외 나가면 실패


# ============================================================
# 4. 출구 토글 — 메모리와 DB 를 함께 (§4.2)
# ============================================================

def test_toggling_an_exit_updates_the_in_memory_graph(topology):
    """DB 만 고치면 다음 재기동 전까지 경로 계산이 옛 상태를 본다 —
    관리자가 닫은 출구로 사람을 계속 보내게 된다."""
    evacuation_service.set_topology(topology)

    assert evacuation_service.set_exit_usable_in_memory("trunk-fwd", False) is True
    graph = evacuation_service.get_topology()
    assert next(x for x in graph.exits if x.exit_id == "trunk-fwd").is_usable is False

    # 같은 값으로 다시 부르면 "바뀐 것 없음"이라 재계산을 부르지 않는다.
    assert evacuation_service.set_exit_usable_in_memory("trunk-fwd", False) is False
    assert evacuation_service.set_exit_usable_in_memory("nope", True) is False


def test_closed_exit_changes_the_route(topology):
    evacuation_service.set_topology(topology)
    first, _ = evacuation_service.compute_and_decide(
        "wearable-01", Position2D(30.0, 0.0), zones=[], hazard_data_available=True
    )
    assert first.result.target_exit_id == "trunk-fwd"

    evacuation_service.set_exit_usable_in_memory("trunk-fwd", False)
    second, changed = evacuation_service.compute_and_decide(
        "wearable-01", Position2D(30.0, 0.0), zones=[], hazard_data_available=True
    )
    assert changed is True
    assert second.result.target_exit_id == "trunk-aft"


# ============================================================
# 5. REST
# ============================================================

def test_topology_endpoint_returns_the_graph(client, topology):
    evacuation_service.set_topology(topology)
    body = client.get("/api/evacuation/topology").json()
    assert len(body["nav_nodes"]) == 8
    assert len(body["exits"]) == 2


def test_topology_endpoint_is_409_when_feature_is_off(client):
    """404 가 아니다. 경로가 없는 게 아니라 기능이 설정되지 않은 것이다."""
    resp = client.get("/api/evacuation/topology")
    assert resp.status_code == 409


def test_route_endpoint_returns_the_active_route(client, topology):
    _seed_route(topology)
    body = client.get("/api/evacuation/route/wearable-01").json()
    assert body["route_status"] == "safe"
    assert body["target_exit_id"] == "trunk-fwd"


def test_route_endpoint_is_404_when_nothing_computed(client, topology):
    evacuation_service.set_topology(topology)
    assert client.get("/api/evacuation/route/wearable-99").status_code == 404


def test_put_topology_rejects_an_invalid_graph(client, topology):
    """검증을 건너뛰면 관리자가 끊긴 그래프를 올린 순간 경로 기능이 죽는다.
    그때는 대피 상황에서 발견하게 된다."""
    evacuation_service.set_topology(topology)
    broken = topology.model_dump(mode="json")
    broken["exits"] = []

    resp = client.put("/api/evacuation/topology", json=broken)

    assert resp.status_code == 422
    assert "출구" in json.dumps(resp.json(), ensure_ascii=False)
    # 거부됐으므로 메모리의 그래프는 그대로여야 한다.
    assert len(evacuation_service.get_topology().exits) == 2


def test_topology_endpoint_carries_is_provisional(client, topology):
    """프론트 NavTopology.is_provisional 은 필수 필드다 — 응답에 없으면 배지가
    라이브 모드에서 절대 뜨지 않는다 (#225, 목 모드에서만 동작하던 잠복 버그)."""
    evacuation_service.set_topology(topology)
    body = client.get("/api/evacuation/topology").json()
    assert "is_provisional" in body
    assert body["is_provisional"] is True
