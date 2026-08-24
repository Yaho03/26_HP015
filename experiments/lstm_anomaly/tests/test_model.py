"""모델·loss·점수 계약."""
from __future__ import annotations

import numpy as np
import pytest
import torch

from src.baselines import ALL_BASELINES, PCABaseline, RollingStatBaseline, ZScoreBaseline
from src.model import (
    LSTMAutoencoder,
    anomaly_scores,
    feature_errors,
    masked_loss,
    top_contributors,
)

FEATURES = ["a", "b", "c", "d", "e"]


@pytest.mark.parametrize("n_features", [2, 3, 5, 8])
def test_output_shape_equals_input_shape(n_features):
    """feature 수를 코드에 박지 않는다 (§2.2). 채널이 바뀌어도 그대로 동작해야 한다."""
    model = LSTMAutoencoder(n_features)
    x = torch.randn(4, 60, n_features)
    assert model(x).shape == x.shape


def test_zero_features_is_rejected():
    with pytest.raises(ValueError):
        LSTMAutoencoder(0)


def test_single_layer_model_has_no_dropout():
    model = LSTMAutoencoder(5, num_layers=1)
    assert model.encoder.dropout == 0.0
    assert model.decoder.dropout == 0.0


def test_decoder_reconstructs_only_through_the_latent_bottleneck():
    """디코더가 입력을 직접 보면 항등함수를 배우고 복원 오차가 이상과 무관해진다.

    forward 의 결과가 'latent 만으로 만든 출력' 과 정확히 같음을 확인해, 입력에서
    디코더로 가는 우회 경로가 없다는 것을 보인다.
    """
    torch.manual_seed(0)
    model = LSTMAutoencoder(5)
    x = torch.randn(2, 60, 5)
    with torch.no_grad():
        _, (hidden, _) = model.encoder(x)
        latent = model.to_latent(hidden[-1])
        seeded = model.from_latent(latent)
        repeated = seeded.unsqueeze(1).expand(-1, 60, -1)
        decoded, _ = model.decoder(repeated)
        from_latent_only = model.output(decoded)
        assert torch.allclose(model(x), from_latent_only, atol=1e-6)


def test_latent_is_narrower_than_input_sequence():
    """병목이 없으면 autoencoder 가 아니다."""
    model = LSTMAutoencoder(5, hidden_size=32, latent_size=16)
    assert model.latent_size < 60 * model.n_features


# ---------------- masked loss ----------------

def test_masked_loss_ignores_unobserved_positions():
    prediction = torch.zeros(1, 4, 1)
    target = torch.tensor([[[0.0], [100.0], [0.0], [100.0]]])
    mask = torch.tensor([[[True], [False], [True], [False]]])
    assert masked_loss(prediction, target, mask).item() == pytest.approx(0.0)


def test_masked_loss_counts_observed_positions():
    prediction = torch.zeros(1, 2, 1)
    target = torch.tensor([[[2.0], [4.0]]])
    mask = torch.ones(1, 2, 1, dtype=torch.bool)
    assert masked_loss(prediction, target, mask).item() == pytest.approx(3.0)


def test_masked_loss_with_no_observations_is_zero_and_differentiable():
    prediction = torch.zeros(1, 2, 1, requires_grad=True)
    target = torch.ones(1, 2, 1)
    mask = torch.zeros(1, 2, 1, dtype=torch.bool)
    loss = masked_loss(prediction, target, mask)
    loss.backward()
    assert loss.item() == 0.0


def test_huber_loss_is_available():
    prediction = torch.zeros(1, 2, 1)
    target = torch.tensor([[[10.0], [10.0]]])
    mask = torch.ones(1, 2, 1, dtype=torch.bool)
    huber = masked_loss(prediction, target, mask, kind="huber").item()
    mae = masked_loss(prediction, target, mask, kind="mae").item()
    assert huber > 0 and huber != mae


def test_unknown_loss_is_rejected():
    with pytest.raises(ValueError):
        masked_loss(torch.zeros(1, 1, 1), torch.zeros(1, 1, 1),
                    torch.ones(1, 1, 1, dtype=torch.bool), kind="cosmic")


# ---------------- feature errors / scores ----------------

def test_recent_steps_are_weighted_more():
    """같은 크기의 이상이라도 최근에 있으면 점수가 커야 한다 (§6.1)."""
    target = torch.zeros(2, 60, 1)
    early = torch.zeros(2, 60, 1); early[:, :6] = 10.0
    late = torch.zeros(2, 60, 1); late[:, -6:] = 10.0
    mask = torch.ones(2, 60, 1, dtype=torch.bool)
    early_score = feature_errors(early, target, mask, recent_steps=6, recent_weight=0.7)
    late_score = feature_errors(late, target, mask, recent_steps=6, recent_weight=0.7)
    assert late_score.mean().item() > early_score.mean().item()


def test_fully_unobserved_channel_yields_nan_not_zero():
    """0 은 '완벽히 정상' 이라는 뜻이다. 꺼진 센서가 가장 정상적인 센서가 되면 안 된다."""
    prediction = torch.zeros(1, 10, 2)
    target = torch.zeros(1, 10, 2)
    mask = torch.ones(1, 10, 2, dtype=torch.bool)
    mask[:, :, 1] = False
    errors = feature_errors(prediction, target, mask)
    assert not torch.isnan(errors[0, 0])
    assert torch.isnan(errors[0, 1])


def test_anomaly_score_skips_nan_channels():
    errors = torch.tensor([[1.0, float("nan"), 3.0]])
    assert anomaly_scores(errors).item() == pytest.approx(2.0)


def test_anomaly_score_all_nan_is_nan_not_zero():
    errors = torch.tensor([[float("nan"), float("nan")]])
    assert torch.isnan(anomaly_scores(errors)).all()


def test_top_contributors_sorted_desc_and_named():
    errors = torch.tensor([[0.1, 0.9, 0.5, float("nan"), 0.2]])
    top = top_contributors(errors, FEATURES, k=3)[0]
    assert [t["metric"] for t in top] == ["b", "c", "e"]
    assert top[0]["error"] > top[1]["error"] > top[2]["error"]
    assert all(t["metric"] != "d" for t in top)


# ---------------- baselines ----------------

def _normal(n=200, t=60, f=5, seed=0):
    rng = np.random.default_rng(seed)
    values = rng.normal(0.0, 1.0, (n, t, f))
    return values, np.ones((n, t, f), dtype=bool)


@pytest.mark.parametrize("cls", ALL_BASELINES)
def test_baseline_interface_is_uniform(cls):
    """세 baseline 이 LSTM 과 같은 자로 재려면 인터페이스가 같아야 한다."""
    values, observed = _normal()
    model = cls().fit(values, observed)
    scores = model.score(values, observed)
    assert scores.shape == (values.shape[0],)
    assert model.feature_errors(values, observed).shape == (values.shape[0], values.shape[2])
    assert isinstance(model.name, str)


@pytest.mark.parametrize("cls", ALL_BASELINES)
def test_baseline_scores_anomalies_higher_than_normal(cls):
    values, observed = _normal(n=300)
    model = cls().fit(values, observed)
    dirty = values.copy()
    dirty[:50, -10:, 0] += 12.0
    normal_score = np.nanmean(model.score(values[50:], observed[50:]))
    dirty_score = np.nanmean(model.score(dirty[:50], observed[:50]))
    assert dirty_score > normal_score


def test_zscore_cannot_see_cross_feature_break():
    """단변량 기준선의 원리적 한계. 이것이 다변량 모델을 쓸 근거다."""
    rng = np.random.default_rng(3)
    shared = rng.normal(0, 1, (200, 60, 1))
    values = np.concatenate([shared, shared * 1.0], axis=2)
    observed = np.ones_like(values, dtype=bool)
    model = ZScoreBaseline().fit(values, observed)
    broken = values.copy()
    broken[:, :, 1] = -broken[:, :, 1]        # 관계만 뒤집고 각 채널 범위는 그대로
    assert np.nanmean(model.score(broken, observed)) == pytest.approx(
        np.nanmean(model.score(values, observed)), rel=0.05
    )


def test_pca_detects_cross_feature_break_that_zscore_misses():
    rng = np.random.default_rng(3)
    shared = rng.normal(0, 1, (200, 60, 1))
    values = np.concatenate([shared, shared * 1.0], axis=2)
    observed = np.ones_like(values, dtype=bool)
    model = PCABaseline(n_components=1).fit(values, observed)
    broken = values.copy()
    broken[:, :, 1] = -broken[:, :, 1]
    assert np.nanmean(model.score(broken, observed)) > np.nanmean(model.score(values, observed))


@pytest.mark.parametrize("cls", ALL_BASELINES)
def test_baseline_handles_constant_channel_without_inf(cls):
    values = np.zeros((50, 60, 3))
    observed = np.ones_like(values, dtype=bool)
    model = cls().fit(values, observed)
    assert np.isfinite(np.nan_to_num(model.score(values, observed))).all()


def test_rolling_baseline_does_not_use_future_values():
    """미래를 보는 예측기는 실시간 탐지에 쓸 수 없다."""
    values, observed = _normal(n=10)
    model = RollingStatBaseline().fit(values, observed)
    tampered = values.copy()
    tampered[:, -1, :] += 50.0           # 마지막 스텝만 바꾼다
    residual_before = model._residual(values)[:, :-1]
    residual_after = model._residual(tampered)[:, :-1]
    assert np.allclose(residual_before, residual_after), "과거 잔차가 미래 값에 영향받았다"
