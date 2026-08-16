"""UWB 거리 → 좌표 변환 (이슈 #121, ADR-006).

`wearable/{node_id}/ranging` 으로 들어온 앵커별 거리를 최소제곱 삼변측량으로
2D 좌표로 바꾼 뒤, 기존 위치 경로(LocationFilter → WebSocket)에 그대로 흘린다.

설계 결정 (ADR-006): **노드가 거리를 발행하고 백엔드가 계산한다.**
태그가 좌표까지 계산해 보내면 앵커 배치를 바꿀 때마다 펌웨어를 다시 구워야 하고,
계산 근거(어느 앵커를 몇 개 썼는지)가 서버에 남지 않는다.

`wearable/{node_id}/location` 경로는 그대로 둔다 — 자체 측위를 하는 태그를 붙일
여지를 남긴다.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, List, Optional, Sequence, Tuple

from app.config import settings
from app.services import ingest
from app.services.uwb_positioning import least_squares_2d

logger = logging.getLogger(__name__)

Anchor = Tuple[float, float]

# 2D 최소제곱은 앵커 3개부터 풀린다 (uwb_positioning.least_squares_2d).
MIN_ANCHORS = 3

_anchors: Dict[str, Anchor] = {}
_callback_registered = False


def parse_anchors(spec: str) -> Dict[str, Anchor]:
    """`A1:0,0;A2:2.5,0` 형식을 파싱한다.

    앵커 좌표는 설치 정보라 텔레메트리에 싣지 않고 서버 설정으로 둔다.
    형식이 틀리면 조용히 넘기지 않고 예외를 낸다 — 좌표가 틀리면 위치 전체가
    틀리므로 부팅 시 크게 실패하는 편이 낫다.
    """
    anchors: Dict[str, Anchor] = {}
    for chunk in spec.split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        anchor_id, _, coords = chunk.partition(":")
        anchor_id = anchor_id.strip()
        if not anchor_id or not coords:
            raise ValueError(f"anchor spec must be 'id:x,y': {chunk!r}")
        x_raw, _, y_raw = coords.partition(",")
        if not y_raw:
            raise ValueError(f"anchor spec needs both x and y: {chunk!r}")
        try:
            position = (float(x_raw.strip()), float(y_raw.strip()))
        except ValueError as exc:
            raise ValueError(f"anchor coordinates must be numbers: {chunk!r}") from exc
        if anchor_id in anchors:
            raise ValueError(f"duplicate anchor id: {anchor_id!r}")
        anchors[anchor_id] = position
    return anchors


def position_from_ranges(
    ranges: Sequence[dict], anchors: Optional[Dict[str, Anchor]] = None
) -> Optional[Tuple[float, float]]:
    """앵커 거리 목록에서 2D 좌표를 추정한다. 못 풀면 None.

    측위 실패는 정상적인 상황이다(앵커 가림, 반사). 추측한 좌표를 내보내면
    작업자가 실제로 없는 곳에 표시되므로, 확신이 없으면 아무것도 내지 않는다.
    """
    table = _anchors if anchors is None else anchors
    if not table:
        return None

    known: List[Anchor] = []
    distances: List[float] = []
    for entry in ranges:
        if not isinstance(entry, dict):
            continue
        anchor_id = entry.get("anchor_id")
        distance = entry.get("distance_m")
        if not isinstance(anchor_id, str) or anchor_id not in table:
            continue
        if isinstance(distance, bool) or not isinstance(distance, (int, float)):
            continue
        if distance < 0:
            return None  # 음수 거리는 측정 오류다. 나머지로 계산하지 않는다.
        known.append(table[anchor_id])
        distances.append(float(distance))

    if len(known) < MIN_ANCHORS:
        return None

    try:
        return least_squares_2d(known, distances)
    except ValueError as exc:
        # 일직선 배치 등. 서비스가 죽을 이유는 아니다.
        logger.debug("trilateration failed: %s", exc)
        return None


def init() -> None:
    """앵커 설정을 읽고 ranging 콜백을 등록한다."""
    global _anchors, _callback_registered
    _anchors = parse_anchors(settings.uwb_anchors)
    if not _anchors:
        logger.info("UWB anchors not configured; ranging ingest stays idle")
    if _callback_registered:
        return
    ingest.set_ranging_callback(_on_ranging_ingested)
    _callback_registered = True


async def _on_ranging_ingested(
    node_id: str,
    ranges: Sequence[dict],
    sampled_at: datetime,
) -> None:
    position = position_from_ranges(ranges)
    if position is None:
        logger.debug("no position for %s from %d ranges", node_id, len(ranges))
        return

    # 계산된 좌표를 기존 위치 경로에 그대로 넘긴다. 필터·브로드캐스트를 다시
    # 구현하지 않는다. z 는 측위 대상이 아니라 바닥 고정값이다 (04_DATA_CONTRACT 4.4).
    from app.services import location_service

    x, y = position
    await location_service._on_location_ingested(node_id, x, y, 0.0, sampled_at)


def get_anchors() -> Dict[str, Anchor]:
    return dict(_anchors)
