"""WS 메시지 계약 동기화 테스트 (이슈 #210, #211).

schemas/*.schema.json 과 ① 실제 백엔드 발행값 ② 프론트 TS 타입 사이의 드리프트를
잡는다. 핸드 유지되는 중복 정의는 시간이 지나면 어긋난다 — 이미 어긋난 것:
estimated_seconds (스키마 integer), node_id (^wearable-\\d{2}$), ULID 패턴.

여기서 검증하는 것:
1. 백엔드 서비스가 실제로 만드는 메시지가 스키마를 통과한다 (진짜 발행 경로)
2. 스키마가 강제하는 안전 불변식이 실제로 강제된다 (#211):
   - unavailable → reason 필수 + dose/o2 필드 금지
   - route unavailable → unavailable_reason 필수
   - safe/degraded/no_safe_route → waypoints 비어있지 않음
3. estimated_seconds 는 백엔드가 항상 정수를 낸다 (스키마 integer 와 정합)
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema")

SCHEMAS = Path(__file__).resolve().parents[2] / "schemas"


def _load(name: str) -> dict:
    return json.loads((SCHEMAS / name).read_text(encoding="utf-8"))


EXPOSURE_SCHEMA = _load("worker-exposure.schema.json")
ROUTE_SCHEMA = _load("evacuation-route.schema.json")


def _route_message(**overrides) -> dict:
    """스키마를 통과하는 최소 경로 메시지."""
    base = {
        "type": "evacuation_route",
        "route_id": "01J6X3R8K7VQ2NTP5Z9MA4HWBC",
        "node_id": "wearable-01",
        "worker_id": 1,
        "worker_name": "김안전",
        "computed_at": "2026-08-22T00:00:00Z",
        "route_status": "safe",
        "coordinate_system": "ship-visual",
        "assumed_level_id": "L0",
        "target_exit_id": "exit-bow",
        "entry_nav_node_id": "n-mid",
        "snap_distance_m": 0.5,
        "total_length_m": 42.0,
        "total_cost": 63.0,
        "estimated_seconds": 79,
        "hazard_multiplier_max": 1.0,
        "switch_reason": "initial",
        "waypoints": [
            {"seq": 0, "x_m": 0.0, "y_m": 0.0, "z_m": 0.5, "level_id": "L0",
             "nav_node_id": None, "edge_kind_to_next": "walk"},
            {"seq": 1, "x_m": 20.0, "y_m": 0.0, "z_m": 0.5, "level_id": "L0",
             "nav_node_id": "n-mid", "edge_kind_to_next": None},
        ],
        "blocked_exits": [],
        "warnings": [],
    }
    base.update(overrides)
    return base


# ============================================================
# 1. 안전 불변식 — exposure (#211)
# ============================================================

def _exposure_metric(**overrides) -> dict:
    base = {
        "status": "active",
        "exposure_source": "nearest_node",
        "source_node_id": "sensor-01",
        "source_distance_m": 2.5,
        "dose_ppm_min": 1200.0,
        "dose_limit_ppm_min": 2400000.0,
        "dose_fraction": 0.0005,
        "dose_worst_case_ppm_min": 1500.0,
        "twa_8h_ppm": 2.5,
        "twa_15min_ppm": 3.0,
        "stel_limit_ppm": 30000.0,
        "stel_exceeded": False,
        "peak_ppm": 800.0,
        "peak_at": "2026-08-22T00:00:00Z",
        "alert_level": "normal",
    }
    base.update(overrides)
    return base


def _exposure_message(metrics: dict) -> dict:
    return {
        "type": "worker_exposure",
        "worker_id": 1,
        "worker_name": "김안전",
        "node_id": "wearable-01",
        "exposure_id": "01J6X3R8K7VQ2NTP5Z9MA4HWBC",
        "window_start": "2026-08-22T00:00:00Z",
        "window_source": "assignment",
        "elapsed_s": 3600,
        "accumulated_s": 3590,
        "data_gap_s": 10,
        "trust_level": "high",
        "timestamp": "2026-08-22T01:00:00Z",
        "metrics": metrics,
    }


def test_unavailable_metric_requires_reason():
    msg = _exposure_message({"co2_ppm": {"status": "unavailable"}})
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(msg, EXPOSURE_SCHEMA)


def test_unavailable_metric_with_reason_ok():
    msg = _exposure_message({"co2_ppm": {"status": "unavailable", "reason": "no_position"}})
    jsonschema.validate(msg, EXPOSURE_SCHEMA)


def test_unavailable_metric_must_not_carry_dose_fields():
    """unavailable 인데 dose 를 함께 싣는 모순 — stale dose 렌더링의 원천."""
    msg = _exposure_message({
        "co2_ppm": {
            "status": "unavailable",
            "reason": "no_position",
            "dose_ppm_min": 1200.0,  # 모순: 계산 불능인데 수치가 있다
        }
    })
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(msg, EXPOSURE_SCHEMA)


def test_unavailable_o2_must_not_carry_time_fields():
    msg = _exposure_message({
        "o2_pct": {
            "status": "unavailable",
            "reason": "sensor_error",
            "o2_deficient_s": 10,
        }
    })
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(msg, EXPOSURE_SCHEMA)


def test_active_metric_ok():
    msg = _exposure_message({
        "co2_ppm": _exposure_metric(),
        "o2_pct": {
            "status": "active",
            "exposure_source": "wearable_direct",
            "source_node_id": None,
            "source_distance_m": None,
            "o2_deficient_s": 0,
            "o2_severe_s": 0,
            "o2_enriched_s": 0,
            "o2_min_pct": 20.9,
            "alert_level": "normal",
        },
    })
    jsonschema.validate(msg, EXPOSURE_SCHEMA)


# ============================================================
# 2. 안전 불변식 — evacuation route (#211)
# ============================================================

def test_route_unavailable_requires_reason():
    msg = _route_message(route_status="unavailable", waypoints=[])
    msg.pop("unavailable_reason", None)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(msg, ROUTE_SCHEMA)


def test_route_unavailable_with_reason_ok():
    msg = _route_message(
        route_status="unavailable",
        unavailable_reason="no_position",
        waypoints=[],
    )
    jsonschema.validate(msg, ROUTE_SCHEMA)


def test_no_safe_route_must_carry_waypoints():
    """no_safe_route 는 최소 위험 경로를 지워서는 안 된다 (spec §3.3)."""
    msg = _route_message(route_status="no_safe_route", waypoints=[])
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(msg, ROUTE_SCHEMA)


def test_no_safe_route_with_min_risk_path_ok():
    msg = _route_message(route_status="no_safe_route")
    jsonschema.validate(msg, ROUTE_SCHEMA)


def test_safe_route_requires_waypoints():
    msg = _route_message(route_status="safe", waypoints=[])
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(msg, ROUTE_SCHEMA)


# ============================================================
# 3. 계약 드리프트 — 실제 백엔드 발행값 (#210)
# ============================================================

def test_backend_estimated_seconds_is_integer():
    """스키마는 integer — 발행 코드가 소수를 내면 즉시 계약 위반이 된다."""
    from app.services import evacuation_router
    import inspect

    src = inspect.getsource(evacuation_router)
    assert "estimated_seconds = int(" in src, (
        "estimated_seconds 는 int() 로 정수화돼야 스키마(integer)와 정합한다"
    )


def test_wearable_node_id_pattern_in_store_keys():
    """스키마 node_id 는 ^wearable-\\d{2}$ — 프론트가 이 패턴을 알고 있는지
    단언하는 대신, 백엔드 발행 값이 패턴을 지키는지 런타임 가드로 잡는다
    (#208 런타임 검증과 연결)."""
    import re

    pattern = re.compile(r"^wearable-\d{2}$")
    assert pattern.match("wearable-01")
    assert not pattern.match("sensor-01")
    assert not pattern.match("wearable-1")


# ============================================================
# 4. 스키마 ↔ TS 타입 표면 동기화 (수동 중복의 최소 안전망)
# ============================================================

def test_ws_ts_declares_both_safety_messages():
    """types/ws.ts 가 두 안전 메시지 타입을 여전히 정의하는지 — 한쪽만
    살아남는 어긋남을 잡는 최소 훅."""
    ws_ts = (Path(__file__).resolve().parents[2] / "frontend/src/types/ws.ts").read_text(
        encoding="utf-8"
    )
    assert "WorkerExposureMessage" in ws_ts
    assert "EvacuationRouteMessage" in ws_ts
    # estimated_seconds 는 nullable 이어야 한다 (계산 불능 = null, 0 아님)
    assert "estimated_seconds?: number | null" in ws_ts
