"""활성 위험 구역 공급 (FR-803, 12_EVACUATION_ROUTE_SPEC §3.2).

경보가 뜬 고정 센서 노드의 자리를 원형 구역으로 본다.

── IDW 보간값을 쓰지 않는 이유 ─────────────────────────────────────────
ADR-005 가 IDW 를 **시각화 전용**으로 못박았다. 보간값은 측정된 적 없는 지점의
추정치이고, 그것으로 통행 가능/불가를 판정하면 추정을 근거로 사람을 특정 통로로
보내는 셈이 된다. 여기서는 센서 노드의 **실측 등급**만 쓴다.

── 반경에 대한 경고 ────────────────────────────────────────────────────
반경은 설정값(`evacuation_hazard_radius_m`)이고 근거가 확보되지 않았다.
05_DIGITAL_TWIN_SPEC §5.1 의 0.5m 는 축소 데모 공간 기준이라 60m 화물창에
그대로 쓰면 점이 된다 — 센서는 y=±3.25, 통행로는 y=0 이므로 어떤 경보가 떠도
경로에 영향을 주지 못한다. config.py 에 사유를 적어두었다.
"""
from __future__ import annotations

import logging

from app.config import settings
from app.models.alert import AlertLevel
from app.models.evacuation import HazardZone
from app.services import alert_service

logger = logging.getLogger(__name__)


def sensor_positions() -> dict[str, tuple[float, float]]:
    """설정 문자열 "id:x,y;id:x,y" 를 파싱한다. uwb_anchors 와 같은 규약이다.

    형식이 깨진 항목은 건너뛰고 경고만 남긴다. 센서 하나의 오타 때문에 위험 구역
    전체가 사라지면, 화면은 조용히 "위험 없음"으로 보인다.
    """
    out: dict[str, tuple[float, float]] = {}
    raw = settings.evacuation_sensor_positions or ""
    for chunk in raw.split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            node_id, coords = chunk.split(":", 1)
            x_text, y_text = coords.split(",", 1)
            out[node_id.strip()] = (float(x_text), float(y_text))
        except ValueError:
            logger.warning("evacuation_sensor_positions 항목을 읽을 수 없다: %r", chunk)
    return out


def zones_from_levels(levels: dict[str, AlertLevel]) -> list[HazardZone]:
    """노드별 경보 등급을 위험 구역으로 바꾼다.

    좌표를 모르는 노드는 구역을 만들 수 없다. 웨어러블처럼 고정 좌표가 없는
    노드가 여기 섞여 들어오는 것이 정상이므로 조용히 건너뛴다 — 위험 구역은
    "가스가 어디에 있는가"이고, 사람이 있는 자리가 아니다.
    """
    positions = sensor_positions()
    radius = settings.evacuation_hazard_radius_m
    zones: list[HazardZone] = []
    for node_id, level in levels.items():
        if level == AlertLevel.NORMAL:
            continue
        position = positions.get(node_id)
        if position is None:
            continue
        zones.append(
            HazardZone(
                zone_id=f"hz.{node_id}",
                center_x_m=position[0],
                center_y_m=position[1],
                radius_m=radius,
                level=level.value,
            )
        )
    return zones


def current_zones() -> tuple[list[HazardZone], bool]:
    """지금 활성인 위험 구역과 "위험 정보를 읽을 수 있었는가".

    두 번째 값이 False 면 경보 엔진이 아직 준비되지 않은 것이다. 이때 빈 목록을
    "위험 없음"과 같이 취급하면 경로가 근거 없이 안전해 보인다. 호출부는 이 값을
    warnings 의 hazard_data_missing 으로 전달해야 한다 (§6.1).
    """
    evaluator = alert_service.get_evaluator()
    if evaluator is None:
        return [], False
    return zones_from_levels(evaluator.node_levels()), True
