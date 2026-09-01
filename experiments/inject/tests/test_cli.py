"""CLI 인자 처리 — 브로커 인증 / 다중 노드 / duration."""
from __future__ import annotations

import json

import pytest

import cli
from cli import parse_args, resolve_nodes, scenario_kwargs_for


def test_node_id_accepts_comma_separated_list():
    args = parse_args(["--scenario", "normal_steady", "--node-id", "sensor-01,sensor-02,sensor-03"])
    assert resolve_nodes(args) == ["sensor-01", "sensor-02", "sensor-03"]


def test_node_id_single_still_works():
    args = parse_args(["--scenario", "co2_warning", "--node-id", "sensor-01"])
    assert resolve_nodes(args) == ["sensor-01"]


def test_node_id_strips_whitespace_and_drops_empties():
    args = parse_args(["--scenario", "normal_steady", "--node-id", "sensor-01, sensor-02 ,"])
    assert resolve_nodes(args) == ["sensor-01", "sensor-02"]


def test_credentials_default_to_environment(monkeypatch):
    monkeypatch.setenv("MQTT_USERNAME", "hp015")
    monkeypatch.setenv("MQTT_PASSWORD", "from-env")
    args = parse_args(["--scenario", "co2_warning"])
    assert args.username == "hp015"
    assert args.password == "from-env"


def test_explicit_credentials_override_environment(monkeypatch):
    monkeypatch.setenv("MQTT_USERNAME", "from-env")
    args = parse_args(["--scenario", "co2_warning", "--username", "explicit"])
    assert args.username == "explicit"


def test_duration_only_applies_to_scenarios_that_accept_it():
    args = parse_args(["--scenario", "normal_steady", "--duration", "30"])
    assert scenario_kwargs_for("normal_steady", args) == {"duration_seconds": 30}


def test_duration_ignored_when_not_given():
    args = parse_args(["--scenario", "normal_steady"])
    assert scenario_kwargs_for("normal_steady", args) == {}


def test_duration_rejected_for_fixed_length_scenario():
    args = parse_args(["--scenario", "co2_warning", "--duration", "30"])
    with pytest.raises(SystemExit):
        scenario_kwargs_for("co2_warning", args)


@pytest.mark.asyncio
async def test_dry_run_publishes_for_every_node(capsys):
    rc = await cli._run(
        parse_args([
            "--scenario", "normal_steady",
            "--node-id", "sensor-01,sensor-02,sensor-03,sensor-04",
            "--duration", "3",
            "--delay", "0",
            "--dry-run",
        ])
    )
    assert rc == 0
    out = capsys.readouterr().out
    for node in ("sensor-01", "sensor-02", "sensor-03", "sensor-04"):
        assert f"sensors/{node}/gas" in out


@pytest.mark.asyncio
async def test_dry_run_payloads_are_valid_json_envelopes(capsys):
    await cli._run(
        parse_args([
            "--scenario", "normal_steady", "--node-id", "sensor-01",
            "--duration", "2", "--delay", "0", "--dry-run",
        ])
    )
    lines = [l for l in capsys.readouterr().out.splitlines() if l.startswith("[dry-run]")]
    assert lines
    for line in lines:
        topic, raw = line[len("[dry-run] "):].split(": ", 1)
        payload = json.loads(raw)
        assert payload["schema_version"] == "1.1"
        # 연결 상태는 측정값이 아니라 별도 계약(node-connection.schema.json)이다.
        # additionalProperties=false 라 source_mode/simulation 을 실을 수 없다.
        if topic.endswith("/connection"):
            assert payload["status"] in ("online", "offline")
            assert payload["boot_id"]
            continue
        assert payload["source_mode"] == "simulation"
        assert payload["simulation"]["scenario_id"] == "normal_steady"
