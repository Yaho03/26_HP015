"""주입기 계약: 재현 가능하고, 원본을 건드리지 않는다."""
from __future__ import annotations

import numpy as np
import pytest

from src.anomaly_injection import ANOMALY_TYPES, inject

FEATURES = ["mq7_rs_ohm", "mq136_rs_ohm", "mq2_rs_ohm", "temperature_c", "humidity_pct"]


def _clean(n=140, t=60, f=5, seed=0):
    rng = np.random.default_rng(seed)
    values = rng.normal(100.0, 5.0, (n, t, f))
    observed = np.ones((n, t, f), dtype=bool)
    return values, observed


def test_same_seed_reproduces_identical_output():
    v, o = _clean()
    a = inject(v, o, FEATURES, seed=777)
    b = inject(v, o, FEATURES, seed=777)
    assert np.array_equal(a[0], b[0])
    assert np.array_equal(a[2], b[2])
    assert [r.to_dict() for r in a[3]] == [r.to_dict() for r in b[3]]


def test_different_seed_changes_output():
    v, o = _clean()
    a = inject(v, o, FEATURES, seed=1)
    b = inject(v, o, FEATURES, seed=2)
    assert not np.array_equal(a[0], b[0])


def test_input_arrays_are_not_mutated():
    """test 원본이 오염되면 정상 구간 오경보율을 잴 기준이 사라진다."""
    v, o = _clean()
    v_before, o_before = v.copy(), o.copy()
    inject(v, o, FEATURES, seed=5)
    assert np.array_equal(v, v_before)
    assert np.array_equal(o, o_before)


def test_only_labelled_windows_are_modified():
    v, o = _clean()
    values, observed, labels, _ = inject(v, o, FEATURES, seed=5)
    clean_idx = ~labels
    assert np.array_equal(values[clean_idx], v[clean_idx])
    assert np.array_equal(observed[clean_idx], o[clean_idx])


def test_every_labelled_window_actually_changed():
    """라벨만 붙고 값이 그대로면 recall 이 구조적으로 0 이 된다."""
    v, o = _clean()
    values, observed, labels, _ = inject(v, o, FEATURES, seed=9)
    for i in np.flatnonzero(labels):
        changed = not np.array_equal(values[i], v[i])
        masked = not np.array_equal(observed[i], o[i])
        assert changed or masked, f"window {i} 는 라벨만 붙고 변하지 않았다"


def test_contamination_ratio_is_respected():
    v, o = _clean(n=200)
    _, _, labels, _ = inject(v, o, FEATURES, seed=3, contamination_ratio=0.25)
    assert labels.sum() == 50


def test_zero_contamination_produces_no_anomalies():
    v, o = _clean()
    _, _, labels, records = inject(v, o, FEATURES, seed=3, contamination_ratio=0.0)
    assert not labels.any() and records == []


@pytest.mark.parametrize("anomaly_type", ANOMALY_TYPES)
def test_each_type_can_be_injected_alone(anomaly_type):
    v, o = _clean(n=30)
    values, observed, labels, records = inject(
        v, o, FEATURES, seed=11, contamination_ratio=1.0, types=[anomaly_type]
    )
    assert labels.all()
    assert {r.anomaly_type for r in records} == {anomaly_type}
    for i in range(len(labels)):
        assert not np.array_equal(values[i], v[i]) or not np.array_equal(observed[i], o[i])


def test_all_types_appear_when_ratio_is_high():
    """유형별 recall 을 내려면 각 유형이 최소 1건은 있어야 한다."""
    v, o = _clean(n=210)
    _, _, _, records = inject(v, o, FEATURES, seed=13, contamination_ratio=1.0)
    assert {r.anomaly_type for r in records} == set(ANOMALY_TYPES)


def test_dropout_turns_off_observation_mask():
    v, o = _clean(n=20)
    _, observed, _, records = inject(
        v, o, FEATURES, seed=17, contamination_ratio=1.0, types=["dropout"]
    )
    record = records[0]
    channel = FEATURES.index(record.target_features[0])
    span = observed[record.window_index, record.start_step:record.end_step, channel]
    assert not span.any()


def test_stuck_at_holds_one_value():
    v, o = _clean(n=20)
    values, _, _, records = inject(
        v, o, FEATURES, seed=19, contamination_ratio=1.0, types=["stuck_at"]
    )
    record = records[0]
    channel = FEATURES.index(record.target_features[0])
    span = values[record.window_index, record.start_step:record.end_step, channel]
    assert np.allclose(span, span[0])


def test_cross_feature_break_moves_channels_in_opposite_directions():
    v, o = _clean(n=40)
    values, _, _, records = inject(
        v, o, FEATURES, seed=23, contamination_ratio=1.0, types=["cross_feature_break"]
    )
    record = next(r for r in records if len(r.target_features) >= 2)
    i = record.window_index
    deltas = [
        float(np.mean(values[i, record.start_step:record.end_step, FEATURES.index(f)]
                      - v[i, record.start_step:record.end_step, FEATURES.index(f)]))
        for f in record.target_features
    ]
    assert min(deltas) < 0 < max(deltas), "관계 파괴인데 모든 채널이 같은 방향으로 갔다"


def test_records_carry_required_metadata():
    v, o = _clean(n=40)
    _, _, _, records = inject(v, o, FEATURES, seed=29)
    for r in records:
        d = r.to_dict()
        for key in ("anomaly_type", "start_step", "end_step",
                    "target_features", "magnitude", "seed"):
            assert key in d
        assert r.end_step > r.start_step
        assert r.target_features
        assert set(r.target_features) <= set(FEATURES)


def test_unknown_type_is_rejected():
    v, o = _clean(n=5)
    with pytest.raises(ValueError, match="알 수 없는"):
        inject(v, o, FEATURES, seed=1, types=["explode"])


def test_empty_input_is_handled():
    values = np.zeros((0, 60, 5))
    observed = np.zeros((0, 60, 5), dtype=bool)
    v, o, labels, records = inject(values, observed, FEATURES, seed=1)
    assert len(labels) == 0 and records == []


def test_constant_channel_still_receives_a_visible_anomaly():
    """표준편차 0 채널에 스케일 0 을 곱하면 주입 자체가 무효가 된다."""
    values = np.full((10, 60, 5), 50.0)
    observed = np.ones((10, 60, 5), dtype=bool)
    out, _, labels, _ = inject(
        values, observed, FEATURES, seed=31, contamination_ratio=1.0, types=["spike"]
    )
    for i in np.flatnonzero(labels):
        assert not np.array_equal(out[i], values[i])
