"""이슈 #70: 위치 필터링 (이상치 제거 + EMA) — TDD 테스트."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.services.location_filter import LocationFilter


def _ts(seconds: float) -> datetime:
    return datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc) + timedelta(seconds=seconds)


from datetime import timedelta


def test_filter_first_sample_passes_through():
    f = LocationFilter()
    result = f.update("wearable-01", 0.5, 0.5, 0.0, _ts(0))
    assert result is not None
    assert (result.x, result.y, result.z) == (0.5, 0.5, 0.0)


def test_filter_small_movement_passes():
    f = LocationFilter()
    f.update("wearable-01", 0.5, 0.5, 0.0, _ts(0))
    result = f.update("wearable-01", 0.55, 0.52, 0.0, _ts(0.5))
    assert result is not None
    assert 0.5 <= result.x <= 0.55


def test_filter_outlier_rejected():
    """이전 위치에서 MAX_JUMP_M(기본 1.0m) 초과 이동은 이상치로 판단해 스킵."""
    f = LocationFilter(max_jump_m=1.0)
    f.update("wearable-01", 0.5, 0.5, 0.0, _ts(0))
    result = f.update("wearable-01", 3.0, 3.0, 0.0, _ts(0.5))
    assert result is None


def test_filter_ema_smoothing():
    """EMA 로 smoothing. alpha=1.0 이면 raw 값 그대로, alpha=0 이면 변화 없음."""
    f = LocationFilter(alpha=0.5, max_jump_m=10.0)
    f.update("wearable-01", 0.0, 0.0, 0.0, _ts(0))
    result = f.update("wearable-01", 1.0, 0.0, 0.0, _ts(1))
    assert result is not None
    assert 0.4 < result.x < 0.6


def test_filter_independent_per_node():
    f = LocationFilter()
    f.update("wearable-01", 0.5, 0.5, 0.0, _ts(0))
    f.update("wearable-02", 1.5, 1.5, 0.0, _ts(0))
    r1 = f.update("wearable-01", 0.55, 0.55, 0.0, _ts(1))
    r2 = f.update("wearable-02", 1.55, 1.55, 0.0, _ts(1))
    assert r1 is not None and r2 is not None
    assert abs(r1.x - 0.55) < 0.1
    assert abs(r2.x - 1.55) < 0.1


def test_filter_outlier_does_not_corrupt_state():
    """이상치 이후 정상 샘플이 들어오면 정상 동작해야 함."""
    f = LocationFilter(max_jump_m=1.0)
    f.update("wearable-01", 0.5, 0.5, 0.0, _ts(0))
    outlier = f.update("wearable-01", 5.0, 5.0, 0.0, _ts(0.5))
    assert outlier is None
    normal = f.update("wearable-01", 0.6, 0.55, 0.0, _ts(1.0))
    assert normal is not None


def test_normal_walking_1_4mps_rejection_rate_under_one_percent():
    """#110: 1.4m/s 정상 보행은 1Hz 샘플에서도 이상치로 거부되면 안 됨."""
    f = LocationFilter(alpha=0.3, max_speed_mps=2.0)
    accepted = 0
    rejected = 0

    for i in range(101):
        result = f.update("wearable-01", 1.4 * i, 0.0, 0.0, _ts(i))
        if result is None:
            rejected += 1
        else:
            accepted += 1

    assert accepted == 101
    assert rejected / 101 < 0.01


def test_filter_rebases_after_five_consecutive_rejections():
    """#110: 연속 거부가 reject_limit에 도달하면 새 위치를 기준점으로 수용한다."""
    f = LocationFilter(alpha=1.0, max_speed_mps=1.0, reject_limit=5)
    f.update("wearable-01", 0.0, 0.0, 0.0, _ts(0))

    for i in range(1, 5):
        assert f.update("wearable-01", 100.0 + i, 0.0, 0.0, _ts(i)) is None

    rebased = f.update("wearable-01", 105.0, 0.0, 0.0, _ts(5))
    assert rebased is not None
    assert rebased.x == 105.0

    normal_after_rebase = f.update("wearable-01", 106.0, 0.0, 0.0, _ts(6))
    assert normal_after_rebase is not None


def test_filtered_position_dataclass():
    f = LocationFilter()
    result = f.update("wearable-01", 0.5, 0.5, 0.0, _ts(0))
    assert result is not None
    assert hasattr(result, "node_id")
    assert hasattr(result, "x")
    assert hasattr(result, "y")
    assert hasattr(result, "z")
    assert hasattr(result, "timestamp")
    assert result.node_id == "wearable-01"
