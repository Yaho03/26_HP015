"""Multivariate LSTM Autoencoder (§5).

작게 시작한다. 2.4시간짜리 데이터에 큰 모델을 얹으면 학습이 아니라 암기가 되고,
validation loss 는 좋아 보이는데 새 노드에서 무너진다.

feature 수를 생성자 인자로 받는 이유: §2.2 마지막 규칙 — 코드에 6 을 박지 않고
artifact manifest 에서 읽는다. 센서가 죽으면 채널 수가 바뀌는데, 하드코딩하면
그때마다 코드를 고쳐야 하고 manifest 와 어긋나도 아무도 모른다.
"""
from __future__ import annotations

from typing import Optional

import torch
from torch import Tensor, nn


class LSTMAutoencoder(nn.Module):
    def __init__(
        self,
        n_features: int,
        *,
        hidden_size: int = 32,
        latent_size: int = 16,
        num_layers: int = 1,
    ) -> None:
        super().__init__()
        if n_features < 1:
            raise ValueError("n_features 는 1 이상이어야 합니다")
        self.n_features = n_features
        self.hidden_size = hidden_size
        self.latent_size = latent_size
        self.num_layers = num_layers

        self.encoder = nn.LSTM(
            n_features, hidden_size, num_layers=num_layers, batch_first=True
        )
        self.to_latent = nn.Linear(hidden_size, latent_size)
        self.from_latent = nn.Linear(latent_size, hidden_size)
        self.decoder = nn.LSTM(
            hidden_size, hidden_size, num_layers=num_layers, batch_first=True
        )
        self.output = nn.Linear(hidden_size, n_features)
        # num_layers=1 에 dropout 을 걸지 않는다 (§5). PyTorch 도 그 조합에는
        # 경고만 내고 아무 일도 하지 않는다 — 있으나 마나 한 설정을 두지 않는다.

    def forward(self, x: Tensor) -> Tensor:
        """[B, T, F] -> [B, T, F]. 입력과 출력 shape 이 반드시 같다."""
        _, (hidden, _) = self.encoder(x)
        latent = self.to_latent(hidden[-1])                 # [B, latent]
        seeded = self.from_latent(latent)                   # [B, hidden]
        # latent 하나를 T 스텝으로 펼쳐 디코더에 넣는다. 디코더가 입력 시퀀스를
        # 직접 보지 못하게 하는 것이 핵심이다 — 보게 하면 autoencoder 가 아니라
        # 항등 함수를 배우고 복원 오차가 이상 여부와 무관해진다.
        repeated = seeded.unsqueeze(1).expand(-1, x.size(1), -1)
        decoded, _ = self.decoder(repeated)
        return self.output(decoded)


def masked_loss(
    prediction: Tensor,
    target: Tensor,
    mask: Tensor,
    *,
    kind: str = "mae",
    huber_delta: float = 1.0,
) -> Tensor:
    """관측된 지점에서만 오차를 센다 (§5 마지막 규칙).

    보간값과 0 으로 채운 결측이 loss 에 들어가면, 모델은 우리가 만들어낸 직선과
    0 을 정상 패턴으로 학습한다. 결측이 많은 채널일수록 그 영향이 커져서, 결국
    "센서가 꺼져 있는 상태" 를 가장 정상적인 상태로 배우게 된다.
    """
    mask = mask.to(prediction.dtype)
    denominator = mask.sum()
    if denominator.item() == 0:
        return prediction.sum() * 0.0

    error = prediction - target
    if kind == "mae":
        per_element = error.abs()
    elif kind == "huber":
        absolute = error.abs()
        per_element = torch.where(
            absolute <= huber_delta,
            0.5 * error.pow(2),
            huber_delta * (absolute - 0.5 * huber_delta),
        )
    else:
        raise ValueError(f"알 수 없는 loss: {kind}")

    return (per_element * mask).sum() / denominator


def feature_errors(
    prediction: Tensor,
    target: Tensor,
    mask: Tensor,
    *,
    recent_steps: int = 6,
    recent_weight: float = 0.7,
) -> Tensor:
    """window 별·feature 별 복원 오차 [B, F] (§6.1).

    10분 전체를 균등 평균하지 않는 이유: 방금 시작된 이상은 9분간의 정상에 희석돼
    threshold 를 못 넘는다. 실시간 탐지에서 그 지연은 그대로 탐지 실패다.
    최근 recent_steps 스텝에 recent_weight 만큼 가중치를 몰아준다.
    """
    mask = mask.to(prediction.dtype)
    absolute = (prediction - target).abs() * mask

    steps = prediction.size(1)
    recent_steps = max(1, min(recent_steps, steps))
    weights = torch.full((steps,), (1.0 - recent_weight) / max(1, steps - recent_steps),
                         dtype=prediction.dtype, device=prediction.device)
    if steps > recent_steps:
        weights[-recent_steps:] = recent_weight / recent_steps
    else:
        weights[:] = 1.0 / steps
    weights = weights.view(1, steps, 1)

    numerator = (absolute * weights).sum(dim=1)
    denominator = (mask * weights).sum(dim=1)
    # 그 채널이 window 내내 미관측이면 오차를 0 으로 두지 않는다 — 0 은 "완벽하게
    # 정상" 이라는 뜻이라, 꺼진 센서가 가장 정상적인 센서가 되어버린다. 상위
    # 호출자가 insufficient_data 로 처리하도록 NaN 을 남긴다.
    return torch.where(denominator > 0, numerator / denominator,
                       torch.full_like(numerator, float("nan")))


def anomaly_scores(
    errors: Tensor, weights: Optional[Tensor] = None
) -> Tensor:
    """feature 오차 [B, F] -> window 점수 [B] (§6.1).

    NaN(미관측 채널)은 평균에서 뺀다. 전 채널이 NaN 이면 점수도 NaN 이고,
    그것은 '정상' 이 아니라 '판단 불가' 로 다뤄야 한다 (§0.9).
    """
    if weights is None:
        weights = torch.ones(errors.size(-1), dtype=errors.dtype, device=errors.device)
    weights = weights.view(1, -1)
    valid = ~torch.isnan(errors)
    filled = torch.where(valid, errors, torch.zeros_like(errors))
    weight_sum = (weights * valid.to(errors.dtype)).sum(dim=1)
    total = (filled * weights).sum(dim=1)
    return torch.where(weight_sum > 0, total / weight_sum,
                       torch.full_like(total, float("nan")))


def top_contributors(
    errors: Tensor, features: list, k: int = 3
) -> list:
    """window 별 상위 기여 feature (§6.1). WebSocket payload 의 top_contributors."""
    result = []
    for row in errors:
        pairs = [
            {"metric": name, "error": float(value)}
            for name, value in zip(features, row.tolist())
            if value == value  # NaN 제외
        ]
        pairs.sort(key=lambda item: item["error"], reverse=True)
        result.append(pairs[:k])
    return result
