"""이슈 #83: 데모 시나리오 통합 — playlist runner TDD 테스트."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from demo_runner import PLAYLISTS, DemoPlaylistRunner


class FakeRunner:
    def __init__(self):
        self.run_calls: list[tuple[str, str, str]] = []
        self.stopped = False

    async def run_scenario(self, name: str, *, node_id: str, run_id: str = "demo"):
        self.run_calls.append((name, node_id, run_id))

    def stop(self):
        self.stopped = True


def test_playlists_registered():
    expected_keys = {"demo", "gas", "wearable", "connection"}
    assert expected_keys.issubset(set(PLAYLISTS.keys()))


def test_demo_playlist_has_5_scenarios():
    assert len(PLAYLISTS["demo"]) == 5


def test_demo_playlist_includes_all_scenarios():
    scenarios = {item[0] for item in PLAYLISTS["demo"]}
    assert "co2_warning" in scenarios
    assert "h2s_warning" in scenarios
    assert "fall_detection" in scenarios
    assert "o2_low" in scenarios
    assert "node_offline" in scenarios


@pytest.mark.asyncio
async def test_playlist_runner_executes_all_items_in_order():
    fake = FakeRunner()
    runner = DemoPlaylistRunner(scenario_runner=fake, gap_seconds=0)
    items = [
        ("co2_warning", "sensor-01", "label1"),
        ("o2_low", "wearable-01", "label2"),
    ]
    await runner.run_playlist(items, run_id="test-run")
    assert fake.run_calls == [
        ("co2_warning", "sensor-01", "test-run"),
        ("o2_low", "wearable-01", "test-run"),
    ]


@pytest.mark.asyncio
async def test_playlist_runner_propagates_run_id(monkeypatch):
    fake = FakeRunner()
    runner = DemoPlaylistRunner(scenario_runner=fake, gap_seconds=0)
    items = [("co2_warning", "sensor-01", "label")]
    await runner.run_playlist(items, run_id="custom-run-001")
    assert all(call[2] == "custom-run-001" for call in fake.run_calls)


@pytest.mark.asyncio
async def test_playlist_runner_stop_interrupts(monkeypatch):
    fake = FakeRunner()
    runner = DemoPlaylistRunner(scenario_runner=fake, gap_seconds=0)

    async def _slow_scenario(name, *, node_id, run_id="demo"):
        if runner._stopped:
            return
        fake.run_calls.append((name, node_id, run_id))

    fake.run_scenario = _slow_scenario  # type: ignore

    items = [
        ("co2_warning", "sensor-01", "1"),
        ("h2s_warning", "sensor-01", "2"),
        ("o2_low", "wearable-01", "3"),
    ]
    runner._stopped = True
    await runner.run_playlist(items)
    assert fake.run_calls == []


@pytest.mark.asyncio
async def test_playlist_runner_gap_between_scenarios():
    import asyncio
    fake = FakeRunner()
    runner = DemoPlaylistRunner(scenario_runner=fake, gap_seconds=0.05)
    items = [
        ("co2_warning", "sensor-01", "1"),
        ("o2_low", "wearable-01", "2"),
    ]
    start = datetime.now(timezone.utc)
    await runner.run_playlist(items)
    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    assert elapsed >= 0.05
