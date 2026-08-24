"""비교 baseline (§7.2).

LSTM autoencoder 를 단독으로 내놓지 않는다. 복잡한 모델이 단순한 규칙을 못 이기면
그 복잡도는 비용일 뿐이고, 그 사실을 숨기면 남는 것은 근거 없는 자신감뿐이다.

세 baseline 모두 LSTM 과 **완전히 같은 인터페이스**를 갖는다: 정상 train 으로 fit,
validation 정상 분포로 threshold, test 에서 window 점수. 이렇게 해야 같은 자로
잰 비교가 된다.
"""
from __future__ import annotations

from typing import Optional

import numpy as np


def _masked_recent_mean(
    per_step: np.ndarray, mask: np.ndarray, recent_steps: int, recent_weight: float
) -> np.ndarray:
    """[N, T, F] -> [N, F]. model.feature_errors 와 같은 가중 방식을 쓴다."""
    n_steps = per_step.shape[1]
    recent_steps = max(1, min(recent_steps, n_steps))
    weights = np.full(n_steps, (1.0 - recent_weight) / max(1, n_steps - recent_steps))
    if n_steps > recent_steps:
        weights[-recent_steps:] = recent_weight / recent_steps
    else:
        weights[:] = 1.0 / n_steps
    weights = weights.reshape(1, n_steps, 1)

    numerator = (per_step * mask * weights).sum(axis=1)
    denominator = (mask * weights).sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        out = np.where(denominator > 0, numerator / denominator, np.nan)
    return out


def _reduce(errors: np.ndarray) -> np.ndarray:
    """[N, F] -> [N]. NaN 채널은 빼고 평균."""
    with np.errstate(invalid="ignore"):
        return np.nanmean(errors, axis=1)


class ZScoreBaseline:
    """feature 별 z-score (§7.2-1).

    가장 단순한 기준선. 각 채널의 정상 평균·표준편차에서 몇 시그마 떨어졌는지만 본다.
    채널 사이 관계를 전혀 모르므로 cross_feature_break 는 원리상 잡지 못한다 —
    그 차이가 LSTM 을 쓸 근거가 있는지를 가른다.
    """

    name = "zscore"

    def __init__(self, recent_steps: int = 6, recent_weight: float = 0.7) -> None:
        self.recent_steps = recent_steps
        self.recent_weight = recent_weight
        self.mean_: Optional[np.ndarray] = None
        self.std_: Optional[np.ndarray] = None

    def fit(self, values: np.ndarray, observed: np.ndarray) -> "ZScoreBaseline":
        flat = values.reshape(-1, values.shape[-1])
        flat_mask = observed.reshape(-1, observed.shape[-1])
        masked = np.where(flat_mask, flat, np.nan)
        with np.errstate(invalid="ignore"):
            self.mean_ = np.nanmean(masked, axis=0)
            self.std_ = np.nanstd(masked, axis=0)
        self.mean_ = np.nan_to_num(self.mean_, nan=0.0)
        self.std_ = np.nan_to_num(self.std_, nan=1.0)
        self.std_[self.std_ < 1e-12] = 1.0
        return self

    def feature_errors(self, values: np.ndarray, observed: np.ndarray) -> np.ndarray:
        deviation = np.abs(values - self.mean_) / self.std_
        return _masked_recent_mean(deviation, observed, self.recent_steps, self.recent_weight)

    def score(self, values: np.ndarray, observed: np.ndarray) -> np.ndarray:
        return _reduce(self.feature_errors(values, observed))


class RollingStatBaseline:
    """이동 평균/표준편차 기반 규칙 (§7.2-2).

    06_ALERT_RULES 8.2 의 2단계(추세 표시)에 해당하는 수준이다. window 안에서
    앞부분 통계로 뒷부분을 예측하고 그 편차를 본다 — "평소와 다르게 움직인다" 를
    시계열 안에서 국소적으로 판정한다.
    """

    name = "rolling"

    def __init__(self, window: int = 12, recent_steps: int = 6, recent_weight: float = 0.7) -> None:
        self.window = window
        self.recent_steps = recent_steps
        self.recent_weight = recent_weight
        self.scale_: Optional[np.ndarray] = None

    def _residual(self, values: np.ndarray) -> np.ndarray:
        n_steps = values.shape[1]
        w = max(2, min(self.window, n_steps - 1))
        # 앞선 w 스텝 이동평균을 예측값으로 쓴다. 미래를 보지 않는다.
        cumulative = np.cumsum(values, axis=1)
        padded = np.concatenate([np.zeros_like(values[:, :1]), cumulative], axis=1)
        rolling = (padded[:, w:] - padded[:, :-w]) / w         # [N, T-w+1, F]
        prediction = np.concatenate([values[:, :w], rolling[:, :-1]], axis=1)
        return np.abs(values - prediction)

    def fit(self, values: np.ndarray, observed: np.ndarray) -> "RollingStatBaseline":
        residual = self._residual(values)
        masked = np.where(observed, residual, np.nan)
        with np.errstate(invalid="ignore"):
            scale = np.nanstd(masked.reshape(-1, values.shape[-1]), axis=0)
        scale = np.nan_to_num(scale, nan=1.0)
        scale[scale < 1e-12] = 1.0
        self.scale_ = scale
        return self

    def feature_errors(self, values: np.ndarray, observed: np.ndarray) -> np.ndarray:
        residual = self._residual(values) / self.scale_
        return _masked_recent_mean(residual, observed, self.recent_steps, self.recent_weight)

    def score(self, values: np.ndarray, observed: np.ndarray) -> np.ndarray:
        return _reduce(self.feature_errors(values, observed))


class PCABaseline:
    """PCA 복원 오차 (§7.2-3).

    LSTM autoencoder 와 같은 발상(저차원으로 눌렀다 되살리고 그 차이를 본다)을
    **시간 구조 없이** 구현한 것이다. 두 결과의 차이가 곧 "시간 순서를 모델링해서
    실제로 얻은 것" 의 크기다. 이 baseline 을 못 이기면 LSTM 을 쓸 이유가 없다.
    """

    name = "pca"

    def __init__(self, n_components: int = 3, recent_steps: int = 6, recent_weight: float = 0.7) -> None:
        self.n_components = n_components
        self.recent_steps = recent_steps
        self.recent_weight = recent_weight
        self.mean_: Optional[np.ndarray] = None
        self.components_: Optional[np.ndarray] = None

    def fit(self, values: np.ndarray, observed: np.ndarray) -> "PCABaseline":
        flat = values.reshape(-1, values.shape[-1])
        usable = flat[observed.reshape(-1, observed.shape[-1]).all(axis=1)]
        if usable.shape[0] < 2:
            usable = flat
        self.mean_ = usable.mean(axis=0)
        centered = usable - self.mean_
        # SVD 를 직접 쓴다 — sklearn PCA 와 결과가 같고 의존이 하나 줄어든다.
        _, _, vt = np.linalg.svd(centered, full_matrices=False)
        k = max(1, min(self.n_components, vt.shape[0]))
        self.components_ = vt[:k]
        return self

    def feature_errors(self, values: np.ndarray, observed: np.ndarray) -> np.ndarray:
        flat = values.reshape(-1, values.shape[-1]) - self.mean_
        projected = flat @ self.components_.T @ self.components_
        residual = np.abs(flat - projected).reshape(values.shape)
        return _masked_recent_mean(residual, observed, self.recent_steps, self.recent_weight)

    def score(self, values: np.ndarray, observed: np.ndarray) -> np.ndarray:
        return _reduce(self.feature_errors(values, observed))


ALL_BASELINES = (ZScoreBaseline, RollingStatBaseline, PCABaseline)
