"""통행 구조 로더 + 검증기 (FR-801/FR-806, 12_EVACUATION_ROUTE_SPEC §2, §6.3).

가장 중요한 성질 두 가지를 잠근다.

1. **저장소에 든 실제 YAML 이 검증을 통과한다.** 이 파일이 깨지면 시연 당일
   경로 기능이 통째로 꺼지므로, 사람이 손으로 고칠 때마다 CI 가 잡아야 한다.
2. **망가진 토폴로지로도 서버는 뜬다.** 경로 기능만 꺼지고 사유가 남는다.
   토폴로지 오타 때문에 센서 수집과 가스 경보까지 멈추면 안 된다.
"""
from __future__ import annotations

import copy

import pytest
import yaml

from app.models.evacuation import NavTopology
from app.services import evacuation_service, evacuation_topology
from app.services.evacuation_topology import (
    TopologyError,
    load_topology_file,
    topology_path,
    validate_topology,
)


# ============================================================
# 1. 저장소에 든 실제 파일
# ============================================================

def test_repo_topology_file_exists():
    assert topology_path().exists(), (
        f"{topology_path()} 가 없다. 경로 기능이 통째로 꺼진다."
    )


def test_repo_topology_loads_and_validates():
    """실제 config/space_topology.yaml 이 검증을 통과해야 한다."""
    topology = load_topology_file()
    errors = validate_topology(topology)
    assert errors == [], "저장소의 통행 구조가 검증을 통과하지 못한다: " + "; ".join(errors)


def test_repo_topology_has_the_documented_skeleton():
    """§2.5 골격 — 출구 2개 + 우회로 1개 + 사다리 2개.

    출구가 1개로 줄면 "가스가 찬 쪽을 피해 다른 출구로 돌아간다"는 이 기능의 핵심이
    화면에 전혀 드러나지 않는다. 사람이 YAML 을 줄이다 이걸 깨는 것을 막는다.
    """
    topology = load_topology_file()
    assert len(topology.nav_nodes) == 8
    assert len(topology.nav_edges) == 8
    assert len(topology.exits) == 2
    assert sum(1 for e in topology.nav_edges if e.kind.value == "ladder") == 2
    # 프론트엔드 목 데이터(frontend/src/mocks/evacuation.ts)와 같은 그래프여야
    # 목 모드로 리허설한 화면과 실제 화면의 경로가 일치한다.
    assert {x.exit_id for x in topology.exits} == {"trunk-fwd", "trunk-aft"}


def test_repo_topology_is_ship_visual():
    """FILL 프리셋 좌표가 들어오면 거리가 왜곡되어 최근접 출구가 틀리게 나온다."""
    assert load_topology_file().coordinate_system == "ship-visual"


def test_repo_topology_marks_itself_provisional():
    """실측 미반영이라는 사실이 파일 안에 적혀 있어야 한다 (OQ-V5)."""
    text = topology_path().read_text(encoding="utf-8")
    assert "실측" in text and "가정값" in text


# ============================================================
# 2. 검증기 — 그래프 무결성
# ============================================================

@pytest.fixture
def raw() -> dict:
    """검증을 통과하는 최소 그래프. 각 테스트가 여기서 한 군데씩 망가뜨린다."""
    return {
        "version": 1,
        "coordinate_system": "ship-visual",
        "levels": [{"level_id": "L0", "name": "바닥", "height_m": 0.0}],
        "nav_nodes": [
            {"nav_node_id": "a", "kind": "floor", "x_m": 0, "y_m": 0, "z_m": 0, "level_id": "L0"},
            {"nav_node_id": "b", "kind": "floor", "x_m": 10, "y_m": 0, "z_m": 0, "level_id": "L0"},
            {"nav_node_id": "x", "kind": "exit", "x_m": 10, "y_m": 0, "z_m": 5, "level_id": "L0"},
        ],
        "nav_edges": [
            {"edge_id": "e1", "from_node_id": "a", "to_node_id": "b", "kind": "walk",
             "length_m": 10.0, "traverse_factor": 1.0, "bidirectional": True, "is_usable": True},
            {"edge_id": "e2", "from_node_id": "b", "to_node_id": "x", "kind": "ladder",
             "length_m": 5.0, "traverse_factor": 2.5, "bidirectional": True, "is_usable": True},
        ],
        "exits": [
            {"exit_id": "x1", "nav_node_id": "x", "kind": "ladder_out",
             "x_m": 10, "y_m": 0, "z_m": 5, "is_usable": True, "priority": 1},
        ],
    }


def _errors(raw: dict) -> list[str]:
    return validate_topology(NavTopology.model_validate(raw))


def test_baseline_fixture_is_valid(raw):
    assert _errors(raw) == []


def test_dangling_edge_reference_is_caught(raw):
    raw["nav_edges"][0]["to_node_id"] = "nope"
    errors = _errors(raw)
    assert any("nope" in e for e in errors)


def test_dangling_exit_reference_is_caught(raw):
    raw["exits"][0]["nav_node_id"] = "nope"
    assert any("출구" in e and "nope" in e for e in _errors(raw))


def test_self_loop_edge_is_caught(raw):
    raw["nav_edges"][0]["to_node_id"] = raw["nav_edges"][0]["from_node_id"]
    assert any("자기 자신" in e for e in _errors(raw))


def test_no_exits_is_caught(raw):
    raw["exits"] = []
    assert any("출구가 하나도 없다" in e for e in _errors(raw))


def test_all_exits_unusable_is_caught(raw):
    raw["exits"][0]["is_usable"] = False
    assert any("사용 가능한 출구가 하나도 없다" in e for e in _errors(raw))


def test_duplicate_node_id_is_caught(raw):
    raw["nav_nodes"].append(copy.deepcopy(raw["nav_nodes"][0]))
    assert any("중복" in e for e in _errors(raw))


def test_orphan_node_is_caught(raw):
    raw["nav_nodes"].append(
        {"nav_node_id": "lonely", "kind": "floor", "x_m": 1, "y_m": 1, "z_m": 0, "level_id": "L0"}
    )
    assert any("고아 노드" in e for e in _errors(raw))


def test_node_that_cannot_reach_an_exit_is_caught(raw):
    """출구와 이어지지 않은 섬. 고아는 아니지만 대피에는 쓸모가 없다."""
    raw["nav_nodes"] += [
        {"nav_node_id": "i1", "kind": "floor", "x_m": 90, "y_m": 0, "z_m": 0, "level_id": "L0"},
        {"nav_node_id": "i2", "kind": "floor", "x_m": 95, "y_m": 0, "z_m": 0, "level_id": "L0"},
    ]
    raw["nav_edges"].append(
        {"edge_id": "e3", "from_node_id": "i1", "to_node_id": "i2", "kind": "walk",
         "length_m": 5.0, "traverse_factor": 1.0, "bidirectional": True, "is_usable": True}
    )
    assert any("도달할 수 없는" in e for e in _errors(raw))


def test_unusable_edge_is_removed_from_the_graph(raw):
    """점검으로 닫힌 통로는 통행할 수 없다. 닫으면 출구가 끊긴다."""
    raw["nav_edges"][1]["is_usable"] = False
    errors = _errors(raw)
    assert errors, "닫힌 사다리 때문에 출구가 끊겼는데 통과했다"


def test_unknown_level_reference_is_caught(raw):
    raw["nav_nodes"][0]["level_id"] = "L9"
    assert any("정의되지 않은 층" in e for e in _errors(raw))


def test_wrong_coordinate_system_is_caught(raw):
    raw["coordinate_system"] = "demo-local"
    assert any("ship-visual" in e for e in _errors(raw))


# ============================================================
# 3. 로더 — 파일 단계의 실패
# ============================================================

def test_missing_file_raises_topology_error(tmp_path):
    with pytest.raises(TopologyError, match="없다"):
        load_topology_file(tmp_path / "nope.yaml")


def test_malformed_yaml_raises_topology_error(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("nav_nodes: [\n  - broken", encoding="utf-8")
    with pytest.raises(TopologyError, match="YAML"):
        load_topology_file(bad)


def test_non_mapping_yaml_raises_topology_error(tmp_path):
    bad = tmp_path / "list.yaml"
    bad.write_text("- a\n- b\n", encoding="utf-8")
    with pytest.raises(TopologyError, match="매핑"):
        load_topology_file(bad)


def test_zero_length_edge_is_rejected_at_parse_time(tmp_path, raw):
    """0 이나 음수 길이는 pydantic 이 잡는다. DB 에도 같은 CHECK 가 걸려 있다."""
    raw["nav_edges"][0]["length_m"] = 0
    bad = tmp_path / "zero.yaml"
    bad.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    with pytest.raises(TopologyError, match="형식 오류"):
        load_topology_file(bad)


# ============================================================
# 4. 서비스 — 실패해도 서버는 뜬다 (§6.3)
# ============================================================

@pytest.mark.asyncio
async def test_init_does_not_raise_when_topology_is_missing(tmp_path, monkeypatch):
    """토폴로지가 없어도 예외가 나가면 안 된다. 나가면 lifespan 이 죽어 서버 전체가
    기동에 실패하고, 센서 수집과 가스 경보까지 함께 멈춘다."""
    evacuation_service.reset_for_test()
    monkeypatch.setattr(
        evacuation_topology, "topology_path", lambda: tmp_path / "nope.yaml"
    )

    await evacuation_service.init()  # 예외가 나가면 테스트 실패

    status = evacuation_service.status()
    assert status.enabled is False
    assert status.reason and "없다" in status.reason
    assert evacuation_service.get_topology() is None


@pytest.mark.asyncio
async def test_init_reports_reason_when_validation_fails(tmp_path, monkeypatch, raw):
    evacuation_service.reset_for_test()
    raw["exits"] = []
    broken = tmp_path / "broken.yaml"
    broken.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr(evacuation_topology, "topology_path", lambda: broken)

    await evacuation_service.init()

    status = evacuation_service.status()
    assert status.enabled is False
    assert status.reason and "출구" in status.reason


@pytest.mark.asyncio
async def test_init_enables_and_counts_when_valid(tmp_path, monkeypatch, raw):
    evacuation_service.reset_for_test()
    good = tmp_path / "good.yaml"
    good.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr(evacuation_topology, "topology_path", lambda: good)

    persisted: list[NavTopology] = []

    async def fake_replace(topology: NavTopology) -> None:
        persisted.append(topology)

    monkeypatch.setattr(
        evacuation_service.nav_repository, "replace_topology", fake_replace
    )

    await evacuation_service.init()

    status = evacuation_service.status()
    assert status.enabled is True
    assert status.reason is None
    assert (status.node_count, status.edge_count, status.exit_count) == (3, 2, 1)
    assert len(persisted) == 1
    assert evacuation_service.get_topology() is not None


@pytest.mark.asyncio
async def test_init_disables_when_db_write_fails(tmp_path, monkeypatch, raw):
    """DB 반영이 실패해도 기동은 계속된다. 다만 경로는 켜지지 않는다 —
    검증만 통과하고 DB 가 비어 있으면 다음 조회가 빈 그래프를 돌려주고, 빈 그래프는
    "출구 없음"으로 읽혀 잘못된 no_safe_route 경보가 된다."""
    evacuation_service.reset_for_test()
    good = tmp_path / "good.yaml"
    good.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr(evacuation_topology, "topology_path", lambda: good)

    async def boom(topology: NavTopology) -> None:
        raise RuntimeError("pool is closed")

    monkeypatch.setattr(evacuation_service.nav_repository, "replace_topology", boom)

    await evacuation_service.init()

    status = evacuation_service.status()
    assert status.enabled is False
    assert status.reason and "pool is closed" in status.reason
    assert evacuation_service.get_topology() is None


def test_default_status_is_disabled():
    """init 이 돌기 전에는 꺼져 있어야 한다. 기본값이 enabled=True 면 init 실패
    후에도 켜진 것처럼 보인다."""
    evacuation_service.reset_for_test()
    assert evacuation_service.is_enabled() is False


# ============================================================
# 5. /health 노출 (§6.3)
# ============================================================

def test_health_reports_evacuation_status(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app import db
    from app.routers import health as health_router
    from app.services import mqtt_subscriber

    evacuation_service.reset_for_test()
    monkeypatch.setattr(mqtt_subscriber, "is_healthy", lambda: True)

    async def ok_ping() -> bool:
        return True

    monkeypatch.setattr(db, "ping", ok_ping)

    app = FastAPI()
    app.include_router(health_router.router)
    body = TestClient(app).get("/health").json()

    assert body["evacuation"]["enabled"] is False
    assert body["evacuation"]["reason"]
    # 경로가 꺼진 것이 전체 상태를 degraded 로 만들면 안 된다. 컨테이너
    # 헬스체크가 재시작 루프를 돈다.
    assert body["status"] == "ok"


# ============================================================
# is_provisional — 실측 여부는 데이터가 말한다 (OQ-V5, 이슈 #225)
# ============================================================

@pytest.mark.asyncio
async def test_provisional_defaults_to_true(tmp_path, monkeypatch, raw):
    """명시 없으면 가정값이다 — 실측이라고 말하는 건 데이터의 몫이다."""
    evacuation_service.reset_for_test()
    raw.pop("is_provisional", None)
    good = tmp_path / "p1.yaml"
    good.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr(evacuation_topology, "topology_path", lambda: good)

    async def fake_replace(topology: NavTopology) -> None:
        pass

    monkeypatch.setattr(evacuation_service.nav_repository, "replace_topology", fake_replace)
    await evacuation_service.init()

    assert evacuation_service.status().provisional is True
    assert evacuation_service.get_topology().is_provisional is True


@pytest.mark.asyncio
async def test_provisional_false_flows_to_status(tmp_path, monkeypatch, raw):
    """실측 완료 후 YAML 한 줄(is_provisional: false)로 배너·health 가 전환된다.

    코드 수정이 필요한 설계라면 실측 반영이 배포까지 몰리게 된다 — 이 테스트가
    그 회귀(하드코딩 복원)를 잡는다.
    """
    evacuation_service.reset_for_test()
    raw["is_provisional"] = False
    measured = tmp_path / "p2.yaml"
    measured.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr(evacuation_topology, "topology_path", lambda: measured)

    async def fake_replace(topology: NavTopology) -> None:
        pass

    monkeypatch.setattr(evacuation_service.nav_repository, "replace_topology", fake_replace)
    await evacuation_service.init()

    assert evacuation_service.status().provisional is False
    assert evacuation_service.get_topology().is_provisional is False


def test_repo_yaml_still_declares_itself_provisional():
    """저장소 골격은 서명 전까지 반드시 가정값이어야 한다 (OQ-V5).

    워크시트 서명 없이 false 로 뒤집히는 사고를 잡는 파수꾼이다.
    """
    import yaml as _yaml
    from app.services import evacuation_topology as et

    data = _yaml.safe_load(et.topology_path().read_text(encoding="utf-8"))
    assert data.get("is_provisional") is True, (
        "config/space_topology.yaml 이 가정값이 아니다 — 워크시트 서명(OQ-V5) 없이"
        " 실측으로 표기할 수 없다"
    )
