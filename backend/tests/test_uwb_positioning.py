"""이슈 #69: 2D Least Squares 위치 계산 — TDD 테스트.

4개 UWB 앵커로부터의 거리 측정값을 받아 태그의 2D 위치를 추정한다.
APPENDIX_TECHNICAL.md 의 Least Squares 수학 참고.
"""
from __future__ import annotations

from typing import List, Tuple

import pytest

from app.services.uwb_positioning import least_squares_2d


Anchor = Tuple[float, float]


def _square_anchors(side: float = 1.0) -> List[Anchor]:
	return [
        (0.0, 0.0),
        (side, 0.0),
        (side, side),
        (0.0, side),
    ]


def test_single_anchor_raises():
    with pytest.raises(ValueError):
        least_squares_2d([(0.0, 0.0)], [1.0])


def test_two_anchors_raises():
    with pytest.raises(ValueError):
        least_squares_2d([(0.0, 0.0), (1.0, 0.0)], [1.0, 1.0])


def test_mismatched_lengths_raise():
    with pytest.raises(ValueError):
        least_squares_2d([(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)], [1.0, 1.0])


def test_negative_distance_raises():
    with pytest.raises(ValueError):
        least_squares_2d(_square_anchors(), [1.0, 1.0, 1.0, -0.5])


def test_center_of_square_returns_center():
    side = 2.0
    anchors = _square_anchors(side)
    cx, cy = side / 2, side / 2
    distances = [((cx - ax) ** 2 + (cy - ay) ** 2) ** 0.5 for ax, ay in anchors]
    x, y = least_squares_2d(anchors, distances)
    assert abs(x - cx) < 1e-6
    assert abs(y - cy) < 1e-6


def test_known_position_returns_expected():
    anchors = _square_anchors(2.0)
    true_x, true_y = 0.3, 1.7
    distances = [((true_x - ax) ** 2 + (true_y - ay) ** 2) ** 0.5 for ax, ay in anchors]
    x, y = least_squares_2d(anchors, distances)
    assert abs(x - true_x) < 1e-6
    assert abs(y - true_y) < 1e-6


def test_with_small_noise_stays_close():
    import random
    random.seed(42)
    anchors = _square_anchors(2.0)
    true_x, true_y = 1.2, 0.8
    distances = [
        ((true_x - ax) ** 2 + (true_y - ay) ** 2) ** 0.5 + random.gauss(0, 0.02)
        for ax, ay in anchors
    ]
    x, y = least_squares_2d(anchors, distances)
    assert abs(x - true_x) < 0.05
    assert abs(y - true_y) < 0.05


def test_three_anchors_works():
    anchors = [(0.0, 0.0), (2.0, 0.0), (0.0, 2.0)]
    true_x, true_y = 0.5, 0.5
    distances = [((true_x - ax) ** 2 + (true_y - ay) ** 2) ** 0.5 for ax, ay in anchors]
    x, y = least_squares_2d(anchors, distances)
    assert abs(x - true_x) < 1e-6
    assert abs(y - true_y) < 1e-6


def test_returns_float_tuple():
    anchors = _square_anchors()
    distances = [1.0, 1.0, 1.0, 1.0]
    result = least_squares_2d(anchors, distances)
    assert isinstance(result, tuple)
    assert len(result) == 2
    assert all(isinstance(v, float) for v in result)
