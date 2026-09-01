"""데모 시나리오 데이터 생성기 (이슈 #82).

시나리오: 정상 상태, CO₂ 경보, H₂S 경보, 낙하 감지, O₂ 저농도, 노드 오프라인.
각 시나리오는 (topic, payload) 튜플 리스트를 반환한다.
모든 메시지는 source_mode="simulation" + simulation 메타데이터 포함.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Callable

from envelope import build_connection_envelope, build_envelope

SCENARIOS: dict[str, Callable[..., list[tuple[str, dict]]]] = {}

# 경보 L1 진입 임계값 (backend/migrations/005_thresholds.sql).
# normal_steady 가 이 값에 닿으면 "정상 상태" 시나리오가 아니게 된다.
NORMAL_CEILINGS = {
    "co2_ppm": 1000,
    "co_ppm": 25,
    "h2s_ppm": 1,
}


def scenario(name: str):
    def deco(fn):
        SCENARIOS[name] = fn
        return fn
    return deco


# demo-local 축소 실험 공간 (05_DIGITAL_TWIN_SPEC 2절: 2.5m x 2.0m x 1.5m).
DEMO_SPACE_WIDTH_M = 2.5
DEMO_SPACE_DEPTH_M = 2.0
DEMO_WALL_MARGIN_M = 0.3

# 09_DEMO_SCENARIOS Scenario 3 성공 기준 — 위치 업데이트 5Hz 이상.
LOCATION_HZ = 5
# 밀폐공간 내 조심스러운 보행. 이 속도여야 LocationFilter 가 이상치로 버리지 않는다.
WALK_SPEED_MPS = 0.4

# 가스 확산 시나리오. 누출원(sensor-03)에서 거리순으로 도달 시각과 정점 농도가 다르다.
# 센서 배치는 05_DIGITAL_TWIN_SPEC 3.1.2 의 ship-visual 좌표를 따른다:
#   S03(10,+5) 누출원 · S01(10,-5) 10m · S04(50,+5) 40m · S02(50,-5) 41m
# 이 시차가 있어야 IDW 히트맵이 번지는 것처럼 보인다. 확산 모델이 아니라 데이터
# 시나리오이며, 히트맵은 여전히 순간 공간 보간이다 (08_SAFETY_AND_LIMITATIONS 3.1).
GAS_SPREAD_BASELINE_PPM = 600
GAS_SPREAD_PROFILE = {
    "sensor-03": (0, 5500),
    "sensor-01": (15, 2400),
    "sensor-04": (35, 1400),
    "sensor-02": (45, 900),
}
_SPREAD_RISE_S = 30
_SPREAD_HOLD_S = 20
_SPREAD_DECAY_S = 45

# UWB 앵커 배치 — 백엔드 settings.uwb_anchors 기본값과 같아야 한다 (이슈 #121).
UWB_ANCHORS = {
    "A1": (0.0, 0.0),
    "A2": (DEMO_SPACE_WIDTH_M, 0.0),
    "A3": (DEMO_SPACE_WIDTH_M, DEMO_SPACE_DEPTH_M),
    "A4": (0.0, DEMO_SPACE_DEPTH_M),
}
# 실제 DS-TWR 거리 오차. EXP-2 측정 기준 ±5cm 수준.
UWB_RANGE_NOISE_M = 0.05

_GAS_PERIOD_S = 1
_ENV_PERIOD_S = 5


def _node_index(node_id: str) -> int:
    """sensor-03 → 3. 알 수 없는 형식이면 1."""
    tail = node_id.rsplit("-", 1)[-1]
    return int(tail) if tail.isdigit() else 1


def _wobble(metric: str, sec: int, amplitude: float) -> float:
    """지표마다 위상이 다른 완만한 흔들림.

    시연을 반복 재현할 수 있어야 하므로 random 을 쓰지 않는다.
    """
    phase = sum(ord(c) for c in metric) % 17
    return amplitude * math.sin((sec + phase) / 7.0)


@scenario("normal_steady")
def normal_steady(
    *,
    start: datetime,
    node_id: str,
    run_id: str = "demo",
    duration_seconds: int = 60,
) -> list[tuple[str, dict]]:
    """Scenario 1 정상 상태 모니터링 (09_DEMO_SCENARIOS 3절).

    모든 값이 L1 진입 임계값(NORMAL_CEILINGS) 아래에서 완만하게 흔들린다.
    가스는 1초, 온습도는 5초 주기 (10_UI_FLOW 3.2 갱신 주기).
    노드마다 기준값을 달리해 카드 4장이 서로 구분되게 한다.
    """
    idx = _node_index(node_id)
    # 연결 상태 발행은 ScenarioRunner 가 맡는다 — 이 시나리오만 online 을 알리면
    # 나머지 시나리오를 틀 때 노드가 전부 "연결 끊김" 으로 남는다.
    out: list[tuple[str, dict]] = []

    for sec in range(duration_seconds + 1):
        ts = start + timedelta(seconds=sec)

        if sec % _GAS_PERIOD_S == 0:
            gas = build_envelope(
                node_id=node_id,
                data={
                    "co2_ppm": round(480 + idx * 55 + _wobble("co2_ppm", sec, 22)),
                    "co_ppm": round(1.5 + idx * 0.8 + _wobble("co_ppm", sec, 0.4), 1),
                    "h2s_ppm": round(0.05 + idx * 0.04 + _wobble("h2s_ppm", sec, 0.02), 2),
                    "gas_resistance_ohm": round(
                        90000 - idx * 6000 + _wobble("gas_resistance_ohm", sec, 1800)
                    ),
                },
                sampled_at=ts,
                source_mode="simulation",
                run_id=run_id,
                scenario_id="normal_steady",
            )
            out.append((f"sensors/{node_id}/gas", gas))

        if sec % _ENV_PERIOD_S == 0:
            env = build_envelope(
                node_id=node_id,
                data={
                    "temperature_c": round(23.5 + idx * 0.6 + _wobble("temperature_c", sec, 0.3), 1),
                    "humidity_pct": round(46.0 + idx * 2.0 + _wobble("humidity_pct", sec, 1.5), 1),
                    "pressure_hpa": round(1013.2 + _wobble("pressure_hpa", sec, 0.4), 2),
                },
                sampled_at=ts,
                source_mode="simulation",
                run_id=run_id,
                scenario_id="normal_steady",
            )
            out.append((f"sensors/{node_id}/env", env))

        if node_id == "sensor-01":
            out.extend(_worker_exposure_context(
                ts=ts, sec=sec, run_id=run_id, scenario_id="normal_steady",
            ))

    return out


def _walk_loop() -> list[tuple[tuple[float, float], tuple[float, float], float]]:
    """벽에서 여유를 둔 사각 순회 경로를 (시작점, 끝점, 길이) 구간 목록으로 반환."""
    lo_x, hi_x = DEMO_WALL_MARGIN_M, DEMO_SPACE_WIDTH_M - DEMO_WALL_MARGIN_M
    lo_y, hi_y = DEMO_WALL_MARGIN_M, DEMO_SPACE_DEPTH_M - DEMO_WALL_MARGIN_M
    corners = [(lo_x, lo_y), (hi_x, lo_y), (hi_x, hi_y), (lo_x, hi_y)]
    segments = []
    for i, a in enumerate(corners):
        b = corners[(i + 1) % len(corners)]
        segments.append((a, b, math.hypot(b[0] - a[0], b[1] - a[1])))
    return segments


def _point_on_loop(distance_m: float) -> tuple[float, float]:
    """경로 시작점에서 distance_m 만큼 걸어간 지점. 경로 끝에 닿으면 순환한다."""
    segments = _walk_loop()
    perimeter = sum(length for _, _, length in segments)
    remaining = distance_m % perimeter
    for (ax, ay), (bx, by), length in segments:
        if remaining <= length:
            f = remaining / length
            return ax + (bx - ax) * f, ay + (by - ay) * f
        remaining -= length
    return segments[0][0]


def _worker_exposure_context(
    *,
    ts: datetime,
    sec: int,
    run_id: str,
    scenario_id: str,
    fixed_position: tuple[float, float] | None = None,
) -> list[tuple[str, dict]]:
    """가스 데모 중 누적 노출량과 탈출로 계산에 필요한 작업자 입력.

    프론트가 가짜 노출량을 만들지 않도록, 데모도 실제 적산 경로를 통과한다.
    위치는 최근접 고정 센서를 결정하고 정상 O₂ 값은 네 번째 노출 지표를 채운다.
    """
    x, y = fixed_position or _point_on_loop(sec * WALK_SPEED_MPS)
    location = build_envelope(
        node_id="wearable-01",
        data={
            "x_m": round(x, 3), "y_m": round(y, 3), "z_m": 0.0,
            "coordinate_system": "model-local", "method": "ds_twr",
            "anchor_count": 4, "quality_score": 0.9, "is_filtered": True,
        },
        sampled_at=ts, source_mode="simulation", run_id=run_id,
        scenario_id=scenario_id, sequence=sec,
        quality={
            "message_status": "complete", "time_synced": True,
            "sensors": {"dwm1000": "valid"},
        },
    )
    vital = build_envelope(
        node_id="wearable-01",
        data={"o2_pct": 20.9, "heart_rate": 75},
        sampled_at=ts, source_mode="simulation", run_id=run_id,
        scenario_id=scenario_id, sequence=sec,
    )
    return [
        ("wearable/wearable-01/location", location),
        ("wearable/wearable-01/vital", vital),
    ]


@scenario("worker_walk")
def worker_walk(
    *,
    start: datetime,
    node_id: str,
    run_id: str = "demo",
    duration_seconds: int = 60,
) -> list[tuple[str, dict]]:
    """Scenario 3 작업자 위치 추적 (09_DEMO_SCENARIOS 3절).

    demo-local 공간 안쪽을 사각으로 순회한다. z_m 은 항상 0.0 —
    04_DATA_CONTRACT 4.4 와 PRD "측위는 2D 고정" 에 따른다.
    """
    step_m = WALK_SPEED_MPS / LOCATION_HZ
    out: list[tuple[str, dict]] = []

    for i in range(duration_seconds * LOCATION_HZ):
        x, y = _point_on_loop(i * step_m)
        env = build_envelope(
            node_id=node_id,
            data={
                "x_m": round(x, 3),
                "y_m": round(y, 3),
                "z_m": 0.0,
                "coordinate_system": "model-local",
                "method": "ds_twr",
                # 앵커 하나가 간헐적으로 빠지는 현실적인 상황을 섞는다.
                "anchor_count": 4 if i % 20 else 3,
                "quality_score": round(0.75 + _wobble("quality_score", i, 0.12), 2),
                "is_filtered": True,
            },
            sampled_at=start + timedelta(seconds=i / LOCATION_HZ),
            source_mode="simulation",
            run_id=run_id,
            scenario_id="worker_walk",
            sequence=i,
            quality={
                "message_status": "complete",
                "time_synced": True,
                "sensors": {"dwm1000": "valid"},
            },
        )
        out.append((f"wearable/{node_id}/location", env))

    return out


def _spread_level(sec: int, delay_s: int, peak_ppm: int) -> int:
    """도달 지연 → 상승 → 유지 → 감쇠 → 정상 복귀 한 사이클."""
    t = sec - delay_s
    if t <= 0 or t >= _SPREAD_RISE_S + _SPREAD_HOLD_S + _SPREAD_DECAY_S:
        return GAS_SPREAD_BASELINE_PPM
    span = peak_ppm - GAS_SPREAD_BASELINE_PPM
    if t < _SPREAD_RISE_S:
        return round(GAS_SPREAD_BASELINE_PPM + span * (t / _SPREAD_RISE_S))
    if t < _SPREAD_RISE_S + _SPREAD_HOLD_S:
        return peak_ppm
    decayed = (t - _SPREAD_RISE_S - _SPREAD_HOLD_S) / _SPREAD_DECAY_S
    return round(GAS_SPREAD_BASELINE_PPM + span * (1 - decayed))


@scenario("gas_spread")
def gas_spread(
    *,
    start: datetime,
    node_id: str,
    run_id: str = "demo",
    duration_seconds: int = 180,
) -> list[tuple[str, dict]]:
    """가스 확산 시연 — 노드마다 도달 시각과 정점이 다른 CO₂ 상승.

    4개 노드를 동시에 주입하면 히트맵이 누출원에서 바깥으로 번지는 것처럼 보인다.
    프로파일에 없는 노드는 정상값만 낸다.
    """
    delay_s, peak_ppm = GAS_SPREAD_PROFILE.get(node_id, (0, GAS_SPREAD_BASELINE_PPM))
    idx = _node_index(node_id)
    out: list[tuple[str, dict]] = []

    for sec in range(duration_seconds + 1):
        env = build_envelope(
            node_id=node_id,
            data={
                "co2_ppm": _spread_level(sec, delay_s, peak_ppm),
                "co_ppm": round(1.5 + idx * 0.8 + _wobble("co_ppm", sec, 0.4), 1),
                "h2s_ppm": round(0.05 + idx * 0.04 + _wobble("h2s_ppm", sec, 0.02), 2),
                "gas_resistance_ohm": round(
                    90000 - idx * 6000 + _wobble("gas_resistance_ohm", sec, 1800)
                ),
            },
            sampled_at=start + timedelta(seconds=sec),
            source_mode="simulation",
            run_id=run_id,
            scenario_id="gas_spread",
        )
        out.append((f"sensors/{node_id}/gas", env))

        # 4개 센서 프로세스가 작업자 값을 중복 발행하지 않도록 누출원만 담당한다.
        if node_id == "sensor-03":
            out.extend(_worker_exposure_context(
                ts=start + timedelta(seconds=sec), sec=sec,
                run_id=run_id, scenario_id="gas_spread",
            ))

    return out


@scenario("exposure_h2s_danger")
def exposure_h2s_danger(
    *,
    start: datetime,
    node_id: str,
    run_id: str = "demo",
    duration_seconds: int = 45,
) -> list[tuple[str, dict]]:
    """촬영용 H₂S 누적 노출 위험.

    네 노드가 매초 최신값을 보내므로 3D 분포가 끊기지 않는다. sensor-03만 낮은
    H₂S 농도에 지속 노출시키고, 누적 시간 압축은 메인 백엔드의 simulation 전용
    분기에서 적용한다. 실제 센서 적산식에는 영향을 주지 않는다.
    """
    idx = _node_index(node_id)
    out: list[tuple[str, dict]] = []
    for sec in range(duration_seconds + 1):
        ts = start + timedelta(seconds=sec)
        h2s = 4.0 if node_id == "sensor-03" else round(0.05 + idx * 0.04, 2)
        env = build_envelope(
            node_id=node_id,
            data={
                "co2_ppm": 700 + idx * 35,
                "co_ppm": round(1.5 + idx * 0.8, 1),
                "h2s_ppm": h2s,
                "gas_resistance_ohm": 90000 - idx * 6000,
            },
            sampled_at=ts,
            source_mode="simulation",
            run_id=run_id,
            scenario_id="exposure_h2s_danger",
        )
        out.append((f"sensors/{node_id}/gas", env))
        if node_id == "sensor-03":
            out.extend(_worker_exposure_context(
                ts=ts,
                sec=sec,
                run_id=run_id,
                scenario_id="exposure_h2s_danger",
                fixed_position=(2.2, 1.7),
            ))
    return out


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
        out.extend(_worker_exposure_context(
            ts=ts, sec=sec, run_id=run_id, scenario_id="co2_warning",
        ))
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
        out.extend(_worker_exposure_context(
            ts=ts, sec=sec, run_id=run_id, scenario_id="h2s_warning",
        ))
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


@scenario("worker_walk_uwb")
def worker_walk_uwb(
    *,
    start: datetime,
    node_id: str,
    run_id: str = "demo",
    duration_seconds: int = 60,
) -> list[tuple[str, dict]]:
    """작업자 순회 — 좌표 대신 **앵커 거리**를 발행한다 (이슈 #121, ADR-006).

    worker_walk 는 태그가 계산한 좌표를 그대로 보내지만, 이 시나리오는 실제
    UWB 노드처럼 거리만 보내고 백엔드가 삼변측량하게 한다. 하드웨어 없이
    프로덕션 측위 경로를 그대로 태우는 것이 목적이다.
    """
    step_m = WALK_SPEED_MPS / LOCATION_HZ
    out: list[tuple[str, dict]] = []

    for i in range(duration_seconds * LOCATION_HZ):
        x, y = _point_on_loop(i * step_m)
        ranges = []
        for idx, (anchor_id, (ax, ay)) in enumerate(UWB_ANCHORS.items()):
            # 앵커 하나가 간헐적으로 가려지는 상황을 섞는다. 3개면 아직 풀린다.
            if i % 20 == 0 and idx == 3:
                continue
            true_d = math.hypot(x - ax, y - ay)
            noise = UWB_RANGE_NOISE_M * math.sin(i * 0.7 + idx * 1.9)
            ranges.append(
                {"anchor_id": anchor_id, "distance_m": round(max(0.0, true_d + noise), 3)}
            )

        env = build_envelope(
            node_id=node_id,
            data={"ranges": ranges, "method": "ds_twr"},
            sampled_at=start + timedelta(seconds=i / LOCATION_HZ),
            source_mode="simulation",
            run_id=run_id,
            scenario_id="worker_walk_uwb",
        )
        out.append((f"wearable/{node_id}/ranging", env))

    return out
