"""UWB 거리 → 좌표 변환 서비스 (이슈 #121).

기존 wearable/*/location 은 태그가 계산한 좌표를 그대로 신뢰한다.
여기서는 ADR-006 (b) 안 — 노드가 앵커까지의 거리를 발행하고 백엔드가 계산 — 을
프로덕션 경로에 연결한다.
"""
from __future__ import annotations

import math

import pytest

from app.services import uwb_service

# 데모 공간(2.5 x 2.0m) 네 모서리. experiments/uwb 와 같은 배치.
DEMO_ANCHORS = "A1:0,0;A2:2.5,0;A3:2.5,2.0;A4:0,2.0"


def ranges_from(x: float, y: float, anchors: dict[str, tuple[float, float]]):
    """참 좌표에서 각 앵커까지의 정확한 거리."""
    return [
        {"anchor_id": aid, "distance_m": math.dist((x, y), pos)}
        for aid, pos in anchors.items()
    ]


class TestParseAnchors:
    def test_parses_demo_layout(self):
        anchors = uwb_service.parse_anchors(DEMO_ANCHORS)
        assert anchors == {
            "A1": (0.0, 0.0),
            "A2": (2.5, 0.0),
            "A3": (2.5, 2.0),
            "A4": (0.0, 2.0),
        }

    def test_tolerates_whitespace(self):
        assert uwb_service.parse_anchors(" A1 : 0 , 0 ; A2:1,1 ") == {
            "A1": (0.0, 0.0),
            "A2": (1.0, 1.0),
        }

    def test_empty_spec_gives_no_anchors(self):
        assert uwb_service.parse_anchors("") == {}

    @pytest.mark.parametrize("bad", ["A1", "A1:0", "A1:a,b", "A1:0,0;A1:1,1"])
    def test_rejects_malformed(self, bad):
        with pytest.raises(ValueError):
            uwb_service.parse_anchors(bad)


class TestPositionFromRanges:
    def setup_method(self):
        self.anchors = uwb_service.parse_anchors(DEMO_ANCHORS)

    @pytest.mark.parametrize("truth", [(1.25, 1.0), (0.4, 0.3), (2.1, 1.7)])
    def test_recovers_true_position(self, truth):
        """오차 없는 거리를 넣으면 원래 좌표가 나와야 한다."""
        got = uwb_service.position_from_ranges(ranges_from(*truth, self.anchors), self.anchors)
        assert got is not None
        assert got[0] == pytest.approx(truth[0], abs=1e-6)
        assert got[1] == pytest.approx(truth[1], abs=1e-6)

    def test_three_anchors_is_enough(self):
        rs = ranges_from(1.0, 1.0, self.anchors)[:3]
        got = uwb_service.position_from_ranges(rs, self.anchors)
        assert got is not None
        assert got[0] == pytest.approx(1.0, abs=1e-6)

    def test_two_anchors_is_not_enough(self):
        """3개 미만이면 2D 해가 유일하지 않다. 추측하지 않고 버린다."""
        rs = ranges_from(1.0, 1.0, self.anchors)[:2]
        assert uwb_service.position_from_ranges(rs, self.anchors) is None

    def test_unknown_anchor_id_is_ignored(self):
        rs = ranges_from(1.0, 1.0, self.anchors)
        rs.append({"anchor_id": "GHOST", "distance_m": 9.9})
        got = uwb_service.position_from_ranges(rs, self.anchors)
        assert got is not None
        assert got[0] == pytest.approx(1.0, abs=1e-6)

    def test_dropping_to_two_known_anchors_returns_none(self):
        rs = [
            {"anchor_id": "GHOST1", "distance_m": 1.0},
            {"anchor_id": "GHOST2", "distance_m": 1.0},
            {"anchor_id": "A1", "distance_m": 1.0},
            {"anchor_id": "A2", "distance_m": 1.0},
        ]
        assert uwb_service.position_from_ranges(rs, self.anchors) is None

    def test_negative_distance_is_rejected(self):
        rs = ranges_from(1.0, 1.0, self.anchors)
        rs[0]["distance_m"] = -1.0
        assert uwb_service.position_from_ranges(rs, self.anchors) is None

    def test_measurement_noise_stays_close(self):
        """실제 UWB 는 오차가 있다. ±5cm 면 추정도 그 언저리여야 한다."""
        rs = ranges_from(1.25, 1.0, self.anchors)
        for i, r in enumerate(rs):
            r["distance_m"] += 0.05 if i % 2 == 0 else -0.05
        got = uwb_service.position_from_ranges(rs, self.anchors)
        assert got is not None
        assert math.dist(got, (1.25, 1.0)) < 0.30

    def test_no_anchors_configured_returns_none(self):
        rs = ranges_from(1.0, 1.0, self.anchors)
        assert uwb_service.position_from_ranges(rs, {}) is None

    def test_malformed_range_entry_is_ignored(self):
        rs = ranges_from(1.0, 1.0, self.anchors)
        rs.append({"anchor_id": "A1"})            # distance 없음
        rs.append({"distance_m": 1.0})            # anchor_id 없음
        rs.append({"anchor_id": "A2", "distance_m": "가까움"})
        got = uwb_service.position_from_ranges(rs, self.anchors)
        assert got is not None
        assert got[0] == pytest.approx(1.0, abs=1e-6)

    def test_collinear_anchors_return_none(self):
        """일직선 배치는 해가 없다. 예외를 밖으로 던지지 않는다."""
        line = {"L1": (0.0, 0.0), "L2": (1.0, 0.0), "L3": (2.0, 0.0)}
        rs = [{"anchor_id": a, "distance_m": 1.0} for a in line]
        assert uwb_service.position_from_ranges(rs, line) is None
