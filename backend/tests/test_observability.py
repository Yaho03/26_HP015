"""이슈 #88: 관측성 — 구조화 로깅, /health, 메트릭 카운터 — TDD 테스트."""
from __future__ import annotations

import pytest


def test_observability_module_importable():
    from app import observability
    assert hasattr(observability, "metrics")
    assert hasattr(observability, "setup_logging")


def test_metrics_singleton_has_counters():
    from app.observability import metrics
    assert hasattr(metrics, "messages_processed")
    assert hasattr(metrics, "messages_dropped_invalid")
    assert hasattr(metrics, "alerts_published")
    assert hasattr(metrics, "alerts_resolved")
    assert hasattr(metrics, "snapshot")


def test_metrics_increment():
    from app.observability import metrics
    initial = metrics.messages_processed
    metrics.increment("messages_processed")
    assert metrics.messages_processed == initial + 1


def test_metrics_snapshot_returns_dict():
    from app.observability import metrics
    snap = metrics.snapshot()
    assert isinstance(snap, dict)
    assert "messages_processed" in snap
    assert "alerts_published" in snap


def test_health_endpoint_reports_mqtt_db_status():
    from fastapi.testclient import TestClient
    from app.main import app
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "mqtt" in data
    assert "db" in data


def test_metrics_endpoint_exists():
    from fastapi.testclient import TestClient
    from app.main import app
    routes = [r.path for r in app.routes]
    assert "/api/metrics" in routes


def test_metrics_endpoint_returns_snapshot():
    from fastapi.testclient import TestClient
    from app.main import app
    client = TestClient(app)
    resp = client.get("/api/metrics")
    assert resp.status_code == 200
    assert "messages_processed" in resp.json()
