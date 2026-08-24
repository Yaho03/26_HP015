"""전처리 계약: 보간값과 실측값이 절대 섞이지 않는다."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.preprocessing import Scaler, resample_node

BASE = pd.Timestamp("2026-08-24T02:00:00Z")


def _wide(seconds, values, column="a"):
    return pd.DataFrame(
        {column: values},
        index=pd.DatetimeIndex([BASE + pd.Timedelta(seconds=s) for s in seconds]),
    )


def _resample(wide, **kw):
    kw.setdefault("interval_s", 10)
    kw.setdefault("max_interpolate_gap_s", 20)
    kw.setdefault("constant_run_reject_s", 600)
    return resample_node(wide, **kw)


def test_resamples_to_fixed_interval():
    wide = _wide(range(0, 60), np.arange(60, dtype="float64"))
    values, observed, _ = _resample(wide)
    assert (values.index.to_series().diff().dropna() == pd.Timedelta(seconds=10)).all()
    assert len(values) == 6


def test_bucket_mean_is_used_for_continuous_metric():
    wide = _wide([0, 1, 2], [10.0, 20.0, 30.0])
    values, _, _ = _resample(wide)
    assert values.iloc[0]["a"] == pytest.approx(20.0)


def test_state_metric_uses_last_not_mean():
    """iaq_accuracy 0 과 2 의 평균 1 은 존재하지 않는 센서 상태다."""
    wide = _wide([0, 5], [0.0, 2.0], column="iaq_accuracy")
    values, _, _ = _resample(wide)
    assert values.iloc[0]["iaq_accuracy"] == 2.0


def test_short_gap_is_interpolated_and_marked_unobserved():
    # 0s 와 30s 만 관측 → 10s, 20s 는 보간 대상 (한도 20s 이내)
    wide = _wide([0, 30], [0.0, 30.0])
    values, observed, _ = _resample(wide)
    assert values.iloc[1]["a"] == pytest.approx(10.0)
    assert observed.iloc[0]["a"]
    assert not observed.iloc[1]["a"], "보간값이 관측으로 표시되면 masked loss 가 무의미해진다"


def test_long_gap_is_not_interpolated():
    wide = _wide([0, 600], [0.0, 600.0])
    values, observed, _ = _resample(wide)
    middle = observed["a"].to_numpy()[1:-1]
    assert not middle.any()
    assert not np.isnan(values["a"].to_numpy()).any(), "결측은 0으로 채우고 마스크로 구분한다"


def test_long_constant_run_is_masked_out():
    """sensor-04 gas_resistance_ohm 이 전 구간 176.6 이던 실제 사례."""
    n = 200
    wide = _wide(range(0, n * 10, 10), np.full(n, 176.6))
    _, observed, logs = _resample(wide, constant_run_reject_s=600)
    assert not observed["a"].any()
    assert any("constant_run" in log.rule for log in logs)


def test_short_constant_run_survives():
    values = np.arange(200, dtype="float64")
    values[10:15] = values[10]        # 50초 정체 < 600초 기준
    wide = _wide(range(0, 2000, 10), values)
    _, observed, _ = _resample(wide, constant_run_reject_s=600)
    assert observed["a"].sum() > 190


def test_exclusions_are_counted_not_silent():
    """§3 — 임의로 삭제하지 말고 제외 규칙과 개수를 기록한다."""
    n = 100
    wide = _wide(range(0, n * 10, 10), np.full(n, 5.0))
    _, _, logs = _resample(wide, constant_run_reject_s=300)
    assert logs and all(log.n_samples > 0 for log in logs)


def test_empty_input_is_handled():
    values, observed, logs = _resample(pd.DataFrame())
    assert values.empty and logs == []


# ---------------- Scaler ----------------

def test_scaler_ignores_unobserved_values():
    """0 으로 채운 결측이 평균에 섞이면 스케일이 결측 패턴을 반영하게 된다."""
    values = np.array([[10.0], [0.0], [10.0], [0.0]])
    observed = np.array([[True], [False], [True], [False]])
    scaler = Scaler(["a"]).fit(values, observed)
    assert scaler.mean_[0] == pytest.approx(10.0)


def test_scaler_transform_roundtrip():
    values = np.array([[1.0], [2.0], [3.0], [4.0]])
    observed = np.ones_like(values, dtype=bool)
    scaler = Scaler(["a"]).fit(values, observed)
    assert scaler.inverse_transform(scaler.transform(values)) == pytest.approx(values)


def test_scaler_handles_constant_channel_without_inf():
    values = np.full((10, 1), 7.0)
    observed = np.ones_like(values, dtype=bool)
    scaler = Scaler(["a"]).fit(values, observed)
    assert np.isfinite(scaler.transform(values)).all()


def test_scaler_serialization_roundtrip():
    values = np.array([[1.0, 100.0], [2.0, 200.0], [3.0, 300.0]])
    observed = np.ones_like(values, dtype=bool)
    original = Scaler(["a", "b"]).fit(values, observed)
    restored = Scaler.from_dict(original.to_dict())
    assert restored.transform(values) == pytest.approx(original.transform(values))
    assert restored.features == ["a", "b"]


def test_scaler_requires_fit_before_transform():
    with pytest.raises(RuntimeError):
        Scaler(["a"]).transform(np.zeros((2, 1)))


# ---------------- 노드별 scaler ----------------
#
# 2026-08-24 실측에서 노드 간 baseline 차이가 노드 내 변동을 8배까지 압도했다.
# global scaler 를 쓰면 각 노드의 정상 변동이 0.05σ 로 눌려 이상이 안 보인다.

def _two_nodes():
    """노드 평균이 크게 다르고, 노드 내 변동은 작은 실제 상황을 재현."""
    a = np.array([[5000.0], [5100.0], [4900.0], [5000.0]])
    b = np.array([[40000.0], [40100.0], [39900.0], [40000.0]])
    values = np.concatenate([a, b])
    observed = np.ones_like(values, dtype=bool)
    nodes = np.array(["sensor-01"] * 4 + ["sensor-04"] * 4)
    return values, observed, nodes


def test_per_node_scaling_centres_each_node_separately():
    values, observed, nodes = _two_nodes()
    scaler = Scaler(["a"]).fit(values, observed, nodes)
    out = scaler.transform(values, nodes)
    assert out[:4].mean() == pytest.approx(0.0, abs=1e-9)
    assert out[4:].mean() == pytest.approx(0.0, abs=1e-9)


def test_global_scaling_would_flatten_within_node_variation():
    """왜 노드별이어야 하는지를 수치로 고정한다. 이 격차가 곧 탐지 실패의 원인이었다."""
    values, observed, nodes = _two_nodes()
    scaler = Scaler(["a"]).fit(values, observed, nodes)
    per_node_spread = float(np.std(scaler.transform(values, nodes)[:4]))
    global_spread = float(np.std(scaler.transform(values)[:4]))
    assert per_node_spread > 10 * global_spread


def test_unknown_node_falls_back_to_global_stats():
    values, observed, nodes = _two_nodes()
    scaler = Scaler(["a"]).fit(values, observed, nodes)
    unknown = np.array(["sensor-99"] * len(values))
    assert scaler.transform(values, unknown) == pytest.approx(scaler.transform(values))
    assert not scaler.known_node("sensor-99")
    assert scaler.known_node("sensor-01")


def test_per_node_inverse_transform_roundtrips():
    values, observed, nodes = _two_nodes()
    scaler = Scaler(["a"]).fit(values, observed, nodes)
    out = scaler.transform(values, nodes)
    assert scaler.inverse_transform(out, nodes) == pytest.approx(values)


def test_per_node_stats_survive_serialization():
    values, observed, nodes = _two_nodes()
    original = Scaler(["a"]).fit(values, observed, nodes)
    restored = Scaler.from_dict(original.to_dict())
    assert restored.known_node("sensor-04")
    assert restored.transform(values, nodes) == pytest.approx(original.transform(values, nodes))


def test_per_node_fit_ignores_unobserved_values():
    values = np.array([[5000.0], [0.0], [5100.0], [0.0]])
    observed = np.array([[True], [False], [True], [False]])
    nodes = np.array(["sensor-01"] * 4)
    scaler = Scaler(["a"]).fit(values, observed, nodes)
    assert scaler.per_node_["sensor-01"][0][0] == pytest.approx(5050.0)
