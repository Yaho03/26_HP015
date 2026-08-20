"""데모 시나리오 제어 API.

가장 중요한 계약은 "기본으로 꺼져 있다" 이다 — 인증(#116) 전에 열려 있으면
누구나 안전 시스템에 시뮬레이션 값을 주입할 수 있다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import settings
from app.routers import demo

REPO_ROOT = Path(__file__).resolve().parents[2]


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(demo.router)
    from tests.conftest import install_admin_auth

    install_admin_auth(app)
    return TestClient(app)


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setattr(settings, "demo_control_enabled", True)
    return _client()


@pytest.fixture
def disabled(monkeypatch):
    monkeypatch.setattr(settings, "demo_control_enabled", False)
    return _client()


def test_disabled_by_default():
    """코드상 기본값이 False 여야 한다.

    settings 인스턴스가 아니라 클래스 기본값을 본다 — 인스턴스는 로컬 .env 를
    반영하므로, 시연용으로 켜둔 개발 머신에서 이 테스트가 깨지면 안 된다.
    배포본에 .env 없이 올라갔을 때 꺼져 있는지가 지킬 계약이다.
    """
    from app.config import Settings

    assert Settings.model_fields["demo_control_enabled"].default is False


@pytest.mark.parametrize(
    "method,path",
    [("get", "/api/demo/scenarios"), ("get", "/api/demo/status"), ("post", "/api/demo/stop")],
)
def test_all_routes_404_when_disabled(disabled, method, path):
    assert getattr(disabled, method)(path).status_code == 404


def test_run_404_when_disabled(disabled):
    resp = disabled.post("/api/demo/run", json={"scenario": "normal_steady"})
    assert resp.status_code == 404


def test_lists_scenarios_when_enabled(enabled):
    names = [s["name"] for s in enabled.get("/api/demo/scenarios").json()]
    assert "normal_steady" in names
    assert "gas_spread" in names


def test_catalog_matches_actual_scenario_registry():
    """카탈로그 이름이 실제 시나리오와 어긋나면 실행 시점에 터진다."""
    inject_dir = REPO_ROOT / "experiments" / "inject"
    sys.path.insert(0, str(inject_dir))
    try:
        from scenarios import SCENARIOS  # type: ignore
    finally:
        sys.path.remove(str(inject_dir))
    assert {s.name for s in demo.CATALOG} == set(SCENARIOS.keys())


def test_unknown_scenario_is_rejected(enabled):
    resp = enabled.post("/api/demo/run", json={"scenario": "nope"})
    assert resp.status_code == 404


def test_invalid_node_id_is_rejected(enabled):
    """node_id 는 MQTT 토픽 경로에 그대로 실린다."""
    resp = enabled.post(
        "/api/demo/run",
        json={"scenario": "normal_steady", "node_ids": ["../../etc/passwd"]},
    )
    assert resp.status_code == 400


def test_duration_rejected_for_fixed_length_scenario(enabled):
    resp = enabled.post(
        "/api/demo/run", json={"scenario": "co2_warning", "duration_s": 60}
    )
    assert resp.status_code == 400


def test_duration_out_of_range_is_rejected(enabled):
    resp = enabled.post(
        "/api/demo/run", json={"scenario": "normal_steady", "duration_s": 99999}
    )
    assert resp.status_code == 422


def test_status_reports_idle_when_nothing_running(enabled):
    body = enabled.get("/api/demo/status").json()
    assert body["running"] is False
