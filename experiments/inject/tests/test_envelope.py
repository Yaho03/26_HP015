"""이슈 #82: 데모 데이터 주입 도구 — envelope 생성 TDD 테스트."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from envelope import build_envelope, build_connection_envelope


def test_build_envelope_has_required_fields():
    env = build_envelope(
        node_id="sensor-01",
        data={"co2_ppm": 1200},
        sampled_at=datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc),
    )
    for key in ("schema_version", "message_id", "node_id", "sampled_at", "data", "source_mode"):
        assert key in env, f"missing required field: {key}"


def test_build_envelope_message_id_is_ulid():
    import re
    env = build_envelope(
        node_id="sensor-01",
        data={"co2_ppm": 1200},
        sampled_at=datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc),
    )
    ulid_pattern = re.compile(r"^[0-7][0-9A-HJKMNP-TV-Z]{25}$")
    assert ulid_pattern.match(env["message_id"])


def test_build_envelope_default_source_mode_is_live():
    env = build_envelope(
        node_id="sensor-01",
        data={"co2_ppm": 1200},
        sampled_at=datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc),
    )
    assert env["source_mode"] == "live"
    assert env["simulation"] is None


def test_build_envelope_simulation_mode_includes_metadata():
    env = build_envelope(
        node_id="sensor-01",
        data={"co2_ppm": 1200},
        sampled_at=datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc),
        source_mode="simulation",
        run_id="demo-20260810-01",
        scenario_id="co2_warning",
    )
    assert env["source_mode"] == "simulation"
    assert env["simulation"] is not None
    assert env["simulation"]["run_id"] == "demo-20260810-01"
    assert env["simulation"]["scenario_id"] == "co2_warning"


def test_build_envelope_schema_version_is_1_1():
    env = build_envelope(
        node_id="sensor-01",
        data={},
        sampled_at=datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc),
    )
    assert env["schema_version"] == "1.1"


def test_build_envelope_sampled_at_is_iso8601():
    env = build_envelope(
        node_id="sensor-01",
        data={},
        sampled_at=datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc),
    )
    assert env["sampled_at"].endswith("Z")
    assert "2026-08-10T12:00:00" in env["sampled_at"]


def test_build_connection_envelope_has_required_fields():
    env = build_connection_envelope(
        node_id="sensor-01",
        status="online",
        reason="connect",
        timestamp=datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc),
    )
    for key in ("schema_version", "node_id", "status", "timestamp"):
        assert key in env
    assert env["status"] == "online"


def test_build_connection_envelope_includes_boot_id():
    env = build_connection_envelope(
        node_id="sensor-01",
        status="offline",
        reason="lwt",
        timestamp=datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc),
    )
    assert "boot_id" in env
