"""Threshold · 지속조건 · 평가 지표 계약."""
from __future__ import annotations

import numpy as np
import pytest

from src.anomaly_injection import InjectionRecord
from src.evaluate import evaluate
from src.scoring import (
    STATUS_ANOMALY,
    STATUS_CANDIDATE,
    STATUS_INSUFFICIENT_DATA,
    STATUS_NORMAL,
    UNDECIDED_STATUSES,
    PersistenceGate,
    classify_windows,
    fit_threshold,
)

FEATURES = ["a", "b"]


def _val(n=1000, seed=0):
    rng = np.random.default_rng(seed)
    scores = rng.normal(1.0, 0.2, n)
    errors = rng.normal(1.0, 0.2, (n, 2))
    return scores, errors


# ---------------- threshold ----------------

def test_threshold_is_the_requested_quantile_of_validation_scores():
    scores, errors = _val()
    art = fit_threshold(scores, errors, FEATURES, quantile=0.99)
    assert art.threshold == pytest.approx(np.quantile(scores, 0.99))
    assert art.quantile == 0.99


def test_threshold_records_required_artifact_fields():
    """§6.2 가 artifact 에 저장하라고 명시한 항목."""
    art = fit_threshold(*_val(), FEATURES).to_dict()
    for key in ("threshold", "threshold_quantile", "validation_score_stats",
                "feature_error_stats", "n_validation_windows"):
        assert key in art
    assert set(art["feature_error_stats"]) == set(FEATURES)


def test_threshold_without_validation_data_fails_loudly():
    """근거 없이 임의 threshold 를 만들어내지 않는다."""
    with pytest.raises(ValueError, match="근거"):
        fit_threshold(np.array([np.nan, np.nan]), np.zeros((2, 2)), FEATURES)


def test_threshold_ignores_nan_scores():
    scores = np.concatenate([np.full(10, np.nan), np.ones(100)])
    errors = np.ones((110, 2))
    assert np.isfinite(fit_threshold(scores, errors, FEATURES).threshold)


# ---------------- persistence ----------------

def test_three_consecutive_exceedances_required_for_anomaly():
    gate = PersistenceGate(1.0, consecutive_to_anomaly=3)
    assert gate.update(2.0) == STATUS_CANDIDATE
    assert gate.update(2.0) == STATUS_CANDIDATE
    assert gate.update(2.0) == STATUS_ANOMALY


def test_single_spike_does_not_trigger_anomaly():
    gate = PersistenceGate(1.0, consecutive_to_anomaly=3)
    gate.update(9.0)
    assert gate.update(0.1) == STATUS_CANDIDATE or gate.status != STATUS_ANOMALY
    assert gate.status != STATUS_ANOMALY


def test_three_consecutive_recoveries_required_to_return_normal():
    gate = PersistenceGate(1.0, consecutive_to_anomaly=3, consecutive_to_normal=3)
    for _ in range(3):
        gate.update(2.0)
    assert gate.status == STATUS_ANOMALY
    gate.update(0.1); gate.update(0.1)
    assert gate.status == STATUS_ANOMALY, "두 번 만에 복귀하면 플리커링이 생긴다"
    assert gate.update(0.1) == STATUS_NORMAL


def test_nan_score_neither_advances_nor_resets_the_counter():
    """데이터 없음을 '정상 지속' 으로도 '이상 지속' 으로도 세지 않는다."""
    gate = PersistenceGate(1.0, consecutive_to_anomaly=3)
    gate.update(2.0); gate.update(2.0)
    before = gate.exceedances
    assert gate.update(float("nan")) == STATUS_CANDIDATE
    assert gate.exceedances == before
    assert gate.update(2.0) == STATUS_ANOMALY


def test_classify_windows_marks_nan_as_insufficient_data_not_normal():
    statuses = classify_windows(np.array([np.nan, 0.1, 0.1]), threshold=1.0)
    assert statuses[0] == STATUS_INSUFFICIENT_DATA
    assert statuses[0] in UNDECIDED_STATUSES


def test_undecided_statuses_never_include_normal():
    """§9.2 — insufficient_data 를 normal 로 바꾸지 않는다."""
    assert STATUS_NORMAL not in UNDECIDED_STATUSES
    assert STATUS_ANOMALY not in UNDECIDED_STATUSES


# ---------------- evaluate ----------------

def test_perfect_separation_gives_f1_one():
    scores = np.array([0.1, 0.1, 5.0, 5.0])
    labels = np.array([False, False, True, True])
    m = evaluate(scores, labels, threshold=1.0)
    assert m.precision == 1.0 and m.recall == 1.0 and m.f1 == 1.0


def test_false_positive_rate_uses_normal_windows_only():
    scores = np.array([5.0, 0.1, 0.1, 0.1, 5.0])
    labels = np.array([False, False, False, False, True])
    m = evaluate(scores, labels, threshold=1.0)
    assert m.fp == 1 and m.tn == 3
    assert m.false_positive_rate == pytest.approx(0.25)


def test_nan_score_is_not_counted_as_detection():
    """판단 불가를 탐지로 세면 센서가 꺼진 것만으로 recall 이 올라간다."""
    scores = np.array([np.nan, np.nan])
    labels = np.array([True, True])
    assert evaluate(scores, labels, threshold=1.0).recall == 0.0


def test_recall_by_type_is_reported():
    scores = np.array([5.0, 0.1, 5.0])
    labels = np.array([True, True, True])
    records = [
        InjectionRecord(0, "spike", 0, 5, ["a"], 4.0, 1),
        InjectionRecord(1, "drift", 0, 30, ["a"], 3.0, 1),
        InjectionRecord(2, "spike", 0, 5, ["b"], 4.0, 1),
    ]
    m = evaluate(scores, labels, threshold=1.0, injection_records=records)
    assert m.recall_by_type == {"drift": 0.0, "spike": 1.0}


def test_per_node_metrics_are_reported():
    scores = np.array([5.0, 0.1, 5.0, 0.1])
    labels = np.array([True, False, True, False])
    nodes = np.array(["sensor-01", "sensor-01", "sensor-02", "sensor-02"])
    m = evaluate(scores, labels, threshold=1.0, node_ids=nodes)
    assert set(m.by_node) == {"sensor-01", "sensor-02"}
    assert m.by_node["sensor-01"]["recall"] == 1.0


def test_persistence_mode_suppresses_isolated_detections():
    scores = np.array([5.0, 0.1, 0.1, 0.1, 0.1])
    labels = np.array([True, False, False, False, False])
    strict = evaluate(scores, labels, threshold=1.0, apply_persistence=True)
    assert strict.tp == 0, "단발 초과가 지속조건을 통과하면 안 된다"


def test_metrics_serialize_to_dict():
    m = evaluate(np.array([5.0, 0.1]), np.array([True, False]), threshold=1.0)
    d = m.to_dict()
    for key in ("precision", "recall", "f1", "false_positive_rate", "tp", "fp", "fn", "tn"):
        assert key in d
