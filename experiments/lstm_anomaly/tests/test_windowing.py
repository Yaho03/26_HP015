"""Window 계약: 노드 경계도, split 경계도 넘지 않는다.

leakage 테스트가 이 파일의 존재 이유다. leakage 는 조용히 성능을 부풀리고
평가 결과 전체를 무의미하게 만든다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.windowing import WindowSet, concat, make_windows, node_split, time_split

BASE = pd.Timestamp("2026-08-24T02:00:00Z")
FEATURES = ["a", "b"]


def _index(n, interval_s=10):
    return pd.DatetimeIndex([BASE + pd.Timedelta(seconds=i * interval_s) for i in range(n)])


def _series(n, node="sensor-01", observed=True, seed=0):
    rng = np.random.default_rng(seed)
    values = rng.normal(0, 1, (n, len(FEATURES)))
    mask = np.full((n, len(FEATURES)), observed, dtype=bool)
    return values, mask, _index(n), node


def _make(n=300, seq=60, **kw):
    values, mask, index, node = _series(n, **{k: v for k, v in kw.items() if k in ("node", "seed")})
    kw = {k: v for k, v in kw.items() if k not in ("node", "seed")}
    return make_windows(values, mask, index, node, FEATURES, sequence_length=seq, **kw)


def test_window_shape_is_n_t_f():
    ws = _make(n=300, seq=60)
    assert ws.values.shape[1:] == (60, len(FEATURES))
    assert ws.values.shape[0] == 300 - 60 + 1


def test_too_short_series_produces_no_windows():
    assert len(_make(n=30, seq=60)) == 0


def test_window_never_mixes_nodes():
    a = _make(n=200, node="sensor-01", seed=1)
    b = _make(n=200, node="sensor-02", seed=2)
    merged = concat([a, b], FEATURES, 60)
    for window_nodes in merged.node_ids:
        assert isinstance(window_nodes, str)
    assert set(merged.node_ids) == {"sensor-01", "sensor-02"}
    assert len(merged) == len(a) + len(b)


def _longest_unobserved_run(mask_1d: np.ndarray) -> int:
    run = best = 0
    for flag in mask_1d:
        run = 0 if flag else run + 1
        best = max(best, run)
    return best


def test_no_surviving_window_contains_a_gap_over_the_limit():
    """공백을 '건드린' window 가 아니라 '한도를 넘는 연속 공백을 품은' window 를 버린다.

    한 스텝(10초) 결측은 보간으로 메울 수 있는 정상 범위다. 그것까지 버리면
    남는 데이터가 없다. 버려야 하는 것은 30초를 넘는 연속 단절이다.
    """
    n = 300
    values = np.random.default_rng(0).normal(0, 1, (n, 2))
    mask = np.ones((n, 2), dtype=bool)
    mask[100:120] = False        # 20스텝 x 10s = 200초 공백
    ws = make_windows(values, mask, _index(n), "sensor-01", FEATURES,
                      sequence_length=60, max_gap_s=30, min_observed_ratio=0.0)
    assert len(ws) > 0
    for window in ws.observed:
        assert _longest_unobserved_run(window.any(axis=1)) <= 3

    # 공백 안에서 시작해 한도를 넘는 단절을 안고 가는 window 는 사라져야 한다.
    # (공백 끝자락 116~119 에서 시작하면 남는 결측이 3스텝 이하라 정상 통과다.)
    starts = pd.to_datetime(ws.start_times, utc=True)
    offsets = ((starts - BASE).total_seconds() // 10).astype(int)
    assert not any(100 <= offset < 117 for offset in offsets)


def test_window_with_mostly_interpolated_data_is_dropped():
    n = 200
    values = np.zeros((n, 2))
    mask = np.ones((n, 2), dtype=bool)
    mask[:120] = False
    ws = make_windows(values, mask, _index(n), "sensor-01", FEATURES,
                      sequence_length=60, max_gap_s=100000, min_observed_ratio=0.7)
    starts = pd.to_datetime(ws.start_times, utc=True)
    offsets = ((starts - BASE).total_seconds() // 10).astype(int)
    assert all(offset >= 102 for offset in offsets)


def test_all_unobserved_window_is_dropped():
    n = 120
    ws = make_windows(np.zeros((n, 2)), np.zeros((n, 2), dtype=bool),
                      _index(n), "sensor-01", FEATURES, sequence_length=60)
    assert len(ws) == 0


# ---------------- split ----------------

def _long(n=3000):
    return _make(n=n, seq=60)


def test_split_is_chronological_not_shuffled():
    tr, va, te, _ = time_split(_long(), purge_gap_steps=60)
    assert pd.to_datetime(tr.start_times).max() < pd.to_datetime(va.start_times).min()
    assert pd.to_datetime(va.start_times).max() < pd.to_datetime(te.start_times).min()


def test_purge_gap_prevents_window_overlap_between_splits():
    """train 마지막 window 와 val 첫 window 가 한 스텝도 공유해선 안 된다."""
    seq, interval = 60, 10
    tr, va, te, meta = time_split(_long(), purge_gap_steps=seq, interval_s=interval)
    train_end = pd.to_datetime(tr.start_times).max() + pd.Timedelta(seconds=seq * interval)
    assert pd.to_datetime(va.start_times).min() >= train_end
    val_end = pd.to_datetime(va.start_times).max() + pd.Timedelta(seconds=seq * interval)
    assert pd.to_datetime(te.start_times).min() >= val_end
    assert meta["purge_gap_s"] == seq * interval


def test_split_ratio_is_roughly_honoured():
    tr, va, te, _ = time_split(_long(), purge_gap_steps=60)
    total = len(tr) + len(va) + len(te)
    assert 0.6 < len(tr) / total < 0.8


def test_purged_windows_are_reported():
    _, _, _, meta = time_split(_long(), purge_gap_steps=60)
    assert meta["purged_windows"] > 0


def test_short_span_records_purge_failure_note():
    """구간이 짧아 purge 를 못 넣으면 조용히 넘어가지 않고 기록한다."""
    _, _, _, meta = time_split(_make(n=200, seq=60), purge_gap_steps=600, interval_s=10)
    assert meta["purge_gap_s"] == 0
    assert any("leakage" in n for n in meta["notes"])


def test_empty_windowset_split_does_not_crash():
    empty = WindowSet(
        values=np.zeros((0, 60, 2), dtype="float32"),
        observed=np.zeros((0, 60, 2), dtype=bool),
        node_ids=np.array([], dtype=object),
        start_times=np.array([], dtype="datetime64[ns]"),
        features=FEATURES,
    )
    tr, va, te, meta = time_split(empty)
    assert len(tr) == len(va) == len(te) == 0
    assert "reason" in meta


def test_node_split_holds_out_exactly_one_node():
    merged = concat([
        _make(n=200, node="sensor-01", seed=1),
        _make(n=200, node="sensor-02", seed=2),
        _make(n=200, node="sensor-03", seed=3),
    ], FEATURES, 60)
    fit, holdout = node_split(merged, "sensor-03")
    assert set(holdout.node_ids) == {"sensor-03"}
    assert "sensor-03" not in set(fit.node_ids)
    assert len(fit) + len(holdout) == len(merged)
