"""목 토폴로지 ↔ 실제 YAML 동기화 잠금 (이슈 #225).

config/space_topology.yaml 상단 주석의 요구: "이 그래프는 frontend/src/mocks/
evacuation.ts 의 목 토폴로지와 같아야 한다. 둘이 갈라지면 목 모드로 리허설한
화면과 실제 화면의 경로가 달라진다."

요구만 적혀 있고 잠금 장치가 없었다. 실측 반영 때 YAML 이 바뀌면 목 은 데모
골격으로 남는데, 그 순간부터 이 테스트는 **의도적으로 실패한다** — 목 을
같이 갱신하거나, 목 을 '데모 골격' 으로 명시적으로 분리하는 결정을 강제한다.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from app.services import evacuation_topology as et

REPO_ROOT = Path(__file__).resolve().parents[2]
MOCK_TS = REPO_ROOT / "frontend/src/mocks/evacuation.ts"


@pytest.fixture(scope="module")
def yaml_topology() -> dict:
    return yaml.safe_load(et.topology_path().read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def mock_source() -> str:
    assert MOCK_TS.exists(), "목 토폴로지 파일이 이동했다 — 경로를 갱신하라"
    return MOCK_TS.read_text(encoding="utf-8")


def _mock_ids(source: str, key: str) -> set[str]:
    return set(re.findall(rf'{key}:\s*"([^"]+)"', source))


def test_node_ids_in_sync(yaml_topology, mock_source):
    yaml_ids = {n["nav_node_id"] for n in yaml_topology["nav_nodes"]}
    mock_ids = _mock_ids(mock_source, "nav_node_id")
    assert yaml_ids == mock_ids, (
        "YAML 과 목 토폴로지의 노드가 다르다 — 목 모드 리허설과 실제 화면의 "
        "경로가 어긋난다. 실측 반영으로 YAML 이 바뀐 거라면 목 도 같이 갱신하거나 "
        "'데모 골격' 분리를 명시적으로 결정하라"
    )


def test_edge_ids_in_sync(yaml_topology, mock_source):
    yaml_ids = {e["edge_id"] for e in yaml_topology["nav_edges"]}
    mock_ids = _mock_ids(mock_source, "edge_id")
    assert yaml_ids == mock_ids


def test_exit_ids_in_sync(yaml_topology, mock_source):
    yaml_ids = {e["exit_id"] for e in yaml_topology["exits"]}
    mock_ids = _mock_ids(mock_source, "exit_id")
    assert yaml_ids == mock_ids


def test_mock_declares_itself_provisional(mock_source):
    """목 도 실측이 아니다 — is_provisional: true 여야 한다 (OQ-V5)."""
    assert re.search(r"is_provisional:\s*true", mock_source), (
        "목 토폴로지가 가정값임을 선언하지 않았다"
    )


def test_coordinate_systems_match(yaml_topology, mock_source):
    assert yaml_topology["coordinate_system"] == "ship-visual"
    assert re.search(r'coordinate_system:\s*"ship-visual"', mock_source)
