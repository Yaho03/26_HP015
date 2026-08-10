"""데모 시나리오 데이터 생성기 (이슈 #82).

5개 시나리오: CO₂ 경보, H₂S 경보, 낙하 감지, O₂ 저농도, 노드 오프라인.
각 시나리오는 (topic, payload) 튜플 리스트를 반환한다.
모든 메시지는 source_mode="simulation" + simulation 메타데이터 포함.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable

from envelope import build_connection_envelope, build_envelope

SCENARIOS: dict[str, Callable[..., list[tuple[str, dict]]]] = {}


def scenario(name: str):
    def deco(fn):
        SCENARIOS[name] = fn
        return fn
    return deco


@scenario("co2_warning")
def co2_warning(*, start: datetime, node_id: str, run_id: str = "demo") -> list[tuple[str, dict]]:
    levels = [
        (700, 0), (700, 1), (700, 2),
        (1100, 3), (1100, 4), (1100, 5), (1100, 6),
        (2100, 7), (2100, 8), (2100, 9), (2100, 10),
        (5500, 11), (5500, 12), (5500, 13),
        (700, 14), (700, 15), (700, 16), (700, 17), (700, 18),
    ]
    out: list[tuple[str, dict]] = []
    for co2, sec in levels:
        ts = start + timedelta(seconds=sec)
        env = build_envelope(
            node_id=node_id,
            data={"co2_ppm": co2, "temperature_c": 25.0, "humidity_pct": 50.0},
            sampled_at=ts,
            source_mode="simulation",
            run_id=run_id,
            scenario_id="co2_warning",
        )
        out.append((f"sensors/{node_id}/gas", env))
    return out


@scenario("h2s_warning")
def h2s_warning(*, start: datetime, node_id: str, run_id: str = "demo") -> list[tuple[str, dict]]:
    levels = [
        (0.3, 0), (0.3, 1), (0.3, 2),
        (1.5, 3), (1.5, 4), (1.5, 5), (1.5, 6),
        (6.0, 7), (6.0, 8), (6.0, 9), (6.0, 10),
        (11.0, 11), (11.0, 12), (11.0, 13),
        (0.3, 14), (0.3, 15), (0.3, 16), (0.3, 17),
    ]
    out: list[tuple[str, dict]] = []
    for h2s, sec in levels:
        ts = start + timedelta(seconds=sec)
        env = build_envelope(
            node_id=node_id,
            data={"h2s_ppm": h2s, "co2_ppm": 600},
            sampled_at=ts,
            source_mode="simulation",
            run_id=run_id,
            scenario_id="h2s_warning",
        )
        out.append((f"sensors/{node_id}/gas", env))
    return out


@scenario("fall_detection")
def fall_detection(*, start: datetime, node_id: str, run_id: str = "demo") -> list[tuple[str, dict]]:
    samples = [
        ((0.0, 0.0, 9.8), 0.0, False),
        ((0.0, 0.0, 9.8), 0.5, False),
        ((5.0, 5.0, 25.0), 1.0, True),
        ((0.0, 0.0, 9.8), 2.0, False),
        ((0.0, 0.0, 9.8), 3.0, False),
    ]
    out: list[tuple[str, dict]] = []
    for (ax, ay, az), t, fall in samples:
        ts = start + timedelta(seconds=t)
        env = build_envelope(
            node_id=node_id,
            data={
                "accel_x_g": ax,
                "accel_y_g": ay,
                "accel_z_g": az,
                "fall_detected": fall,
            },
            sampled_at=ts,
            source_mode="simulation",
            run_id=run_id,
            scenario_id="fall_detection",
        )
        out.append((f"wearable/{node_id}/imu", env))
    return out


@scenario("o2_low")
def o2_low(*, start: datetime, node_id: str, run_id: str = "demo") -> list[tuple[str, dict]]:
    levels = [
        (20.9, 0), (20.9, 1), (20.9, 2),
        (19.0, 3), (19.0, 4), (19.0, 5), (19.0, 6), (19.0, 7), (19.0, 8),
        (17.5, 9), (17.5, 10), (17.5, 11), (17.5, 12), (17.5, 13), (17.5, 14),
        (15.5, 15), (15.5, 16), (15.5, 17),
        (20.9, 18), (20.9, 19), (20.9, 20),
    ]
    out: list[tuple[str, dict]] = []
    for o2, sec in levels:
        ts = start + timedelta(seconds=sec)
        env = build_envelope(
            node_id=node_id,
            data={"o2_pct": o2, "heart_rate": 75},
            sampled_at=ts,
            source_mode="simulation",
            run_id=run_id,
            scenario_id="o2_low",
        )
        out.append((f"wearable/{node_id}/vital", env))
    return out


@scenario("node_offline")
def node_offline(*, start: datetime, node_id: str, run_id: str = "demo") -> list[tuple[str, dict]]:
    online_env = build_connection_envelope(
        node_id=node_id, status="online", reason="connect", timestamp=start,
    )
    offline_env = build_connection_envelope(
        node_id=node_id, status="offline", reason="lwt",
        timestamp=start + timedelta(seconds=5),
    )
    return [
        (f"nodes/{node_id}/connection", online_env),
        (f"nodes/{node_id}/connection", offline_env),
    ]
