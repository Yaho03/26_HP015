"""진단이 실제로 불량 센서를 걸러내는지 검증한다.

각 테스트는 2026-08-24 실측에서 관찰된 실제 고장 유형을 재현한 것이다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.data_quality import (
    MIN_FEATURES,
    STATUS_DATA_PARTIAL,
    STATUS_DATA_READY,
    STATUS_DATA_UNAVAILABLE,
    diagnose,
)

BASE = pd.Timestamp("2026-08-24T02:00:00Z")


def _rows(node: str, metric: str, values, *, step_s: int = 1, mode: str = "live"):
    return pd.DataFrame({
        "time": [BASE + pd.Timedelta(seconds=i * step_s) for i in range(len(values))],
        "node_id": node,
        "metric": metric,
        "value": np.asarray(values, dtype="float64"),
        "source_mode": mode,
    })


def _wobble(n: int, base: float, amp: float, seed: int = 0):
    rng = np.random.default_rng(seed)
    return base + rng.normal(0, amp, n)


def _healthy(nodes=("sensor-01", "sensor-02"), metrics=("a", "b"), n=200):
    parts = []
    for ni, node in enumerate(nodes):
        for mi, metric in enumerate(metrics):
            parts.append(_rows(node, metric, _wobble(n, 100 + 10 * mi, 5, seed=ni * 10 + mi)))
    return pd.concat(parts, ignore_index=True)


def test_healthy_multinode_data_is_ready():
    report = diagnose(_healthy())
    assert report.status == STATUS_DATA_READY
    assert set(report.features_valid) == {"a", "b"}
    assert report.features_rejected == []


def test_empty_input_is_unavailable():
    empty = pd.DataFrame(columns=["time", "node_id", "metric", "value", "source_mode"])
    assert diagnose(empty).status == STATUS_DATA_UNAVAILABLE


def test_stuck_at_feature_is_rejected():
    """sensor-04 gas_resistance_ohm 이 6,521 샘플 내내 176.6 이었던 실제 사례."""
    df = pd.concat([
        _healthy(metrics=("a", "b")),
        _rows("sensor-01", "stuck", np.full(200, 176.6)),
        _rows("sensor-02", "stuck", np.full(200, 176.6)),
    ], ignore_index=True)
    report = diagnose(df)
    assert "stuck" not in report.features_valid
    reason = next(v.reason for v in report.features_rejected if v.metric == "stuck")
    assert "stuck-at" in reason
    assert report.constant_runs["stuck"] == 200


def test_feature_dead_on_one_node_only_is_reported_with_that_node():
    """gas_resistance_ohm 실제 사례 — sensor-04 만 죽고 나머지는 정상 변동.

    feature 전체를 조용히 버리면 멀쩡한 3노드 데이터까지 함께 사라진다.
    어느 노드가 문제인지가 배제 사유에 반드시 남아야 한다.
    """
    df = pd.concat([
        _healthy(nodes=("sensor-01", "sensor-02", "sensor-03"), metrics=("a", "b")),
        _rows("sensor-01", "gasres", _wobble(200, 180000, 9000, seed=11)),
        _rows("sensor-02", "gasres", _wobble(200, 175000, 8000, seed=12)),
        _rows("sensor-03", "gasres", np.full(200, 176.6)),
    ], ignore_index=True)
    report = diagnose(df)
    verdict = next(v for v in report.features_rejected if v.metric == "gasres")
    assert verdict.dead_nodes == ["sensor-03"]
    assert "sensor-03" in verdict.reason
    assert "sensor-01" not in verdict.reason


def test_short_constant_run_does_not_kill_a_feature():
    """1초 주기에서 4분 정체는 센서 사망이 아니다. 구간 마스킹으로 처리할 일이다."""
    values = _wobble(2000, 200000, 8000, seed=21)
    values[500:740] = values[500]          # 240샘플 = 표본의 12%
    df = pd.concat([
        _healthy(metrics=("a", "b"), n=2000),
        _rows("sensor-01", "mq7", values),
        _rows("sensor-02", "mq7", _wobble(2000, 195000, 8000, seed=22)),
    ], ignore_index=True)
    report = diagnose(df)
    assert "mq7" in report.features_valid
    assert report.constant_runs["mq7"] >= 240


def test_iaq_index_rejected_when_accuracy_below_two():
    """08_SAFETY §2.1 — accuracy < 2 면 IAQ 값은 공기질을 뜻하지 않는다."""
    df = pd.concat([
        _healthy(metrics=("a", "b")),
        _rows("sensor-01", "iaq_index", _wobble(200, 60, 12, seed=31)),
        _rows("sensor-02", "iaq_index", _wobble(200, 58, 11, seed=32)),
        _rows("sensor-01", "iaq_accuracy", np.tile([0.0, 1.0], 100)),
        _rows("sensor-02", "iaq_accuracy", np.tile([0.0, 1.0], 100)),
    ], ignore_index=True)
    report = diagnose(df)
    assert "iaq_index" not in report.features_valid
    assert "iaq_accuracy" in next(
        v.reason for v in report.features_rejected if v.metric == "iaq_index"
    )


def test_iaq_index_accepted_when_accuracy_reaches_two():
    df = pd.concat([
        _healthy(metrics=("a", "b")),
        _rows("sensor-01", "iaq_index", _wobble(200, 60, 12, seed=33)),
        _rows("sensor-02", "iaq_index", _wobble(200, 58, 11, seed=34)),
        _rows("sensor-01", "iaq_accuracy", np.tile([2.0, 3.0], 100)),
        _rows("sensor-02", "iaq_accuracy", np.tile([2.0, 3.0], 100)),
    ], ignore_index=True)
    assert "iaq_index" in diagnose(df).features_valid


def test_near_constant_feature_is_rejected():
    """pressure_hpa 처럼 CV 0.05% 인 값은 복원 오차에 기여하지 못한다."""
    df = pd.concat([
        _healthy(metrics=("a", "b")),
        _rows("sensor-01", "flat", _wobble(200, 1013.0, 0.0001, seed=1)),
        _rows("sensor-02", "flat", _wobble(200, 1013.0, 0.0001, seed=2)),
    ], ignore_index=True)
    report = diagnose(df)
    assert "flat" not in report.features_valid
    assert "상수" in next(v.reason for v in report.features_rejected if v.metric == "flat")


def test_feature_missing_on_some_nodes_is_rejected():
    """co2_ppm 처럼 일부 노드에만 있는 지표는 4채널 공통 모델에 못 넣는다."""
    df = pd.concat([
        _healthy(metrics=("a", "b")),
        _rows("sensor-01", "partial", _wobble(200, 50, 3, seed=3)),
    ], ignore_index=True)
    report = diagnose(df)
    assert "partial" not in report.features_valid
    assert "누락" in next(v.reason for v in report.features_rejected if v.metric == "partial")


def test_all_null_feature_never_appears():
    """co2_ppm: null 은 로더가 행을 안 만드므로 진단 입력에 아예 없다."""
    report = diagnose(_healthy())
    assert "co2_ppm" not in report.features_valid
    assert all(v.metric != "co2_ppm" for v in report.features_rejected)


def test_single_valid_feature_is_partial_not_ready():
    df = pd.concat([
        _healthy(metrics=("a",)),
        _rows("sensor-01", "stuck", np.full(200, 1.0)),
        _rows("sensor-02", "stuck", np.full(200, 1.0)),
    ], ignore_index=True)
    report = diagnose(df)
    assert report.features_valid == ["a"]
    assert report.status == STATUS_DATA_PARTIAL
    assert any(str(MIN_FEATURES) in n for n in report.notes)


def test_candidate_feature_filter_limits_scope():
    report = diagnose(_healthy(metrics=("a", "b")), candidate_features=["a"])
    assert report.features_valid == ["a"]


def test_sampling_interval_median_is_measured():
    df = pd.concat([
        _rows("sensor-01", "a", _wobble(100, 10, 1, seed=1), step_s=10),
        _rows("sensor-02", "a", _wobble(100, 10, 1, seed=2), step_s=10),
    ], ignore_index=True)
    report = diagnose(df)
    assert report.sampling_interval_median_s["a"] == pytest.approx(10.0)


def test_longest_gap_is_measured():
    a = _rows("sensor-01", "a", _wobble(50, 10, 1, seed=1))
    b = _rows("sensor-01", "a", _wobble(50, 10, 1, seed=2))
    b["time"] = b["time"] + pd.Timedelta(seconds=300)
    df = pd.concat([a, b, _rows("sensor-02", "a", _wobble(100, 10, 1, seed=3))],
                   ignore_index=True)
    report = diagnose(df)
    assert report.longest_gap_by_feature_s["a"] >= 250


def test_duplicate_timestamps_are_counted():
    dup = _rows("sensor-01", "a", [1.0, 2.0])
    df = pd.concat([_healthy(), dup, dup], ignore_index=True)
    assert diagnose(df).duplicate_timestamps >= 2


def test_short_span_note_is_emitted():
    report = diagnose(_healthy(n=200))
    assert any("일반화" in n for n in report.notes)


def test_render_contains_required_status_block():
    text = diagnose(_healthy()).render()
    for key in ("STATUS:", "NODES:", "FEATURES_VALID:", "FEATURES_REJECTED:",
                "START_AT:", "END_AT:", "SAMPLING_INTERVAL_MEDIAN:",
                "VALID_RATIO_BY_FEATURE:", "LONGEST_GAP_BY_FEATURE:",
                "CONSTANT_RUNS:", "LIVE_SIMULATION_SPLIT:", "NOTES:"):
        assert key in text


def test_rejected_features_always_carry_a_reason():
    df = pd.concat([
        _healthy(metrics=("a", "b")),
        _rows("sensor-01", "stuck", np.full(200, 1.0)),
        _rows("sensor-02", "stuck", np.full(200, 1.0)),
    ], ignore_index=True)
    for verdict in diagnose(df).features_rejected:
        assert verdict.reason.strip(), f"{verdict.metric} 배제 사유가 비어 있다"
