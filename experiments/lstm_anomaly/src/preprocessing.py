"""리샘플링 · 결측 처리 · 스케일링 (§4.1).

이 단계의 산출물은 값 배열 하나가 아니라 **값 + 관측 마스크** 쌍이다.
마스크가 없으면 보간으로 채운 값과 센서가 실제로 보낸 값을 모델이 구분하지 못하고,
loss 가 "우리가 만들어낸 직선" 을 정상 패턴으로 학습한다 (§5 masked loss).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

# 평균으로 리샘플링하면 안 되는 지표. 상태/플래그성 값은 평균이 존재하지 않는 중간값을
# 만들어낸다 (accuracy 0 과 2 의 평균 1 은 어떤 센서 상태도 아니다).
_LAST_VALUE_METRICS = {"iaq_accuracy", "fall_detected", "anchor_count", "is_filtered"}


@dataclass
class NodeSeries:
    """한 노드의 전처리 결과."""
    node_id: str
    index: pd.DatetimeIndex
    values: np.ndarray            # [T, F] — 결측은 보간되거나 0으로 채워짐
    observed: np.ndarray          # [T, F] bool — True 면 실제 관측(보간 아님)
    features: List[str]

    def __len__(self) -> int:
        return len(self.index)


@dataclass
class ExclusionLog:
    """무엇을 왜 뺐는지. §3 "임의로 삭제하지 말고 제외 규칙과 개수를 기록" 요구사항."""
    rule: str
    node_id: str
    feature: str
    n_samples: int


def _agg_for(feature: str) -> str:
    return "last" if feature in _LAST_VALUE_METRICS else "mean"


def _mask_constant_runs(
    values: pd.Series, *, min_run: int
) -> np.ndarray:
    """min_run 이상 이어진 동일값 구간을 '관측되지 않음' 으로 표시한다.

    센서가 죽어 마지막 값을 반복하는 것은 측정이 아니다. 그것을 정상 패턴으로
    학습하면 모델은 "이 채널은 가만히 있는 게 정상" 이라고 배우고, 진짜 stuck-at
    이상이 왔을 때 오차를 0 으로 낸다 — 탐지하려던 바로 그 고장에 눈이 먼다.
    """
    observed = np.ones(len(values), dtype=bool)
    array = values.to_numpy()
    if array.size == 0:
        return observed
    finite = ~np.isnan(array)
    if not finite.any():
        return np.zeros(len(values), dtype=bool)

    change = np.flatnonzero(np.diff(array) != 0)
    starts = np.concatenate(([0], change + 1))
    ends = np.concatenate((change + 1, [array.size]))
    for start, end in zip(starts, ends):
        if end - start >= min_run and not np.isnan(array[start]):
            observed[start:end] = False
    return observed


def resample_node(
    wide: pd.DataFrame,
    *,
    interval_s: int,
    max_interpolate_gap_s: int,
    constant_run_reject_s: int,
) -> Tuple[pd.DataFrame, pd.DataFrame, List[ExclusionLog]]:
    """한 노드의 wide 프레임을 고정 간격으로 리샘플링하고 관측 마스크를 만든다.

    반환: (값, 관측여부, 제외기록)

    보간 한도가 필요한 이유: 30초 끊긴 구간을 선형 보간으로 이으면 모델은 그
    구간에서 완벽하게 매끄러운 직선을 보게 되고, 그것이 정상이라고 배운다.
    실제로 그 시간 동안 무슨 일이 있었는지는 아무도 모른다.
    """
    if wide.empty:
        return wide, wide.astype(bool), []

    rule = f"{interval_s}s"
    agg = {col: _agg_for(col) for col in wide.columns}
    resampled = wide.resample(rule).agg(agg)

    # 리샘플 버킷에 원본 관측이 하나라도 있었는지. 이게 진짜 관측 여부의 근거다.
    observed = wide.notna().resample(rule).sum() > 0
    observed = observed.reindex(resampled.index, fill_value=False)

    exclusions: List[ExclusionLog] = []
    node_id = str(wide.attrs.get("node_id", "?"))

    # 짧은 공백만 보간한다. limit 은 스텝 수 단위다.
    limit = max(1, max_interpolate_gap_s // interval_s)
    filled = resampled.interpolate(method="time", limit=limit, limit_area="inside")

    min_run = max(2, constant_run_reject_s // interval_s)
    for column in filled.columns:
        alive = _mask_constant_runs(filled[column], min_run=min_run)
        killed = int((observed[column].to_numpy() & ~alive).sum())
        if killed:
            exclusions.append(ExclusionLog(
                rule=f"constant_run>={constant_run_reject_s}s", node_id=node_id,
                feature=column, n_samples=killed,
            ))
        observed[column] = observed[column].to_numpy() & alive

    # 보간되지 않고 남은 결측은 관측이 아니다. 값은 0 으로 두되 마스크가 0 이라
    # loss 에 들어가지 않는다.
    still_missing = filled.isna()
    long_gaps = int((still_missing & ~observed).sum().sum())
    if long_gaps:
        exclusions.append(ExclusionLog(
            rule=f"gap>{max_interpolate_gap_s}s", node_id=node_id,
            feature="(all)", n_samples=long_gaps,
        ))
    filled = filled.fillna(0.0)
    observed = observed & ~still_missing

    return filled, observed, exclusions


def _masked_stats(values: np.ndarray, observed: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """관측된 값만으로 feature 별 평균·표준편차를 낸다.

    0 으로 채운 결측이 통계에 섞이면 스케일 자체가 결측 패턴을 반영하게 되고,
    같은 scaler 를 쓰는 추론 시점에서 분포가 어긋난다.
    """
    masked = np.where(observed, values, np.nan)
    with np.errstate(invalid="ignore"):
        mean = np.nanmean(masked, axis=0)
        std = np.nanstd(masked, axis=0)
    mean = np.nan_to_num(mean, nan=0.0)
    std = np.nan_to_num(std, nan=1.0)
    # 표준편차 0 인 채널을 그대로 나누면 inf 가 된다. 진단에서 상수 채널을
    # 걸렀더라도 train 구간 안에서만 상수인 경우가 남을 수 있다.
    std[std < 1e-12] = 1.0
    return mean, std


class Scaler:
    """**노드별** 표준화. train 구간에서만 fit 한다 (§4.1, §5).

    노드별로 나눈 이유 — 이것은 튜닝이 아니라 이 하드웨어에서의 필수 조건이다.
    2026-08-24 실측에서 노드 간 baseline 차이가 노드 내 시간 변동을 압도했다:

        mq136_rs_ohm  노드 평균 5,083 ~ 40,470 (8배)
                      global std 13,294  vs  window 내 std 686  ->  비율 0.05

    global scaler 를 쓰면 각 노드의 정상 변동이 0.05σ 로 눌린다. 그 상태에서는
    (a) 모델이 시간 패턴 대신 "이건 몇 번 노드인가" 를 표현하는 데 용량을 쓰고
    (b) 실제로 의미 있는 크기의 이상도 0.2~0.4σ 가 되어 threshold 근처에도 못 간다.
    실측으로 확인했다 — global scaler 에서는 z-score baseline 조차 4~8σ spike 의
    recall 이 0.19 였다.

    MQ 계열은 개체 편차가 크고 R0 를 센서마다 따로 잡아야 한다는 것이
    08_SAFETY_AND_LIMITATIONS §2.2/§5.1 에 이미 명시돼 있다. 노드별 정규화는
    그 문서가 말하는 "개별 센서별 보정" 을 통계적으로 하는 것과 같다.

    대가: 처음 보는 노드는 자기 통계가 없다. 그 경우 global fallback 을 쓰되
    manifest 에 fallback 을 썼다는 사실이 남고, 서비스는 그 노드를
    insufficient_data 로 다룰 수 있다. 추측한 스케일로 정상/이상을 단정하는 것보다
    낫다.
    """

    def __init__(self, features: Sequence[str]) -> None:
        self.features = list(features)
        # global fallback — 학습에 참여한 전체 노드 통계
        self.mean_: Optional[np.ndarray] = None
        self.std_: Optional[np.ndarray] = None
        # node_id -> (mean, std)
        self.per_node_: Dict[str, Tuple[np.ndarray, np.ndarray]] = {}

    def fit(
        self,
        values: np.ndarray,
        observed: np.ndarray,
        node_ids: Optional[np.ndarray] = None,
    ) -> "Scaler":
        self.mean_, self.std_ = _masked_stats(values, observed)
        self.per_node_ = {}
        if node_ids is not None:
            node_ids = np.asarray(node_ids)
            for node in sorted(set(node_ids.tolist())):
                mask = node_ids == node
                if mask.sum() == 0:
                    continue
                self.per_node_[str(node)] = _masked_stats(values[mask], observed[mask])
        return self

    def _stats_for(self, node_id: Optional[str]) -> Tuple[np.ndarray, np.ndarray]:
        if self.mean_ is None or self.std_ is None:
            raise RuntimeError("Scaler.fit 을 먼저 호출해야 합니다")
        if node_id is not None and node_id in self.per_node_:
            return self.per_node_[node_id]
        return self.mean_, self.std_

    def known_node(self, node_id: str) -> bool:
        """이 노드의 통계를 학습 때 본 적이 있는가. 서비스가 fallback 여부를 알아야 한다."""
        return node_id in self.per_node_

    def transform(
        self, values: np.ndarray, node_ids: Optional[np.ndarray] = None
    ) -> np.ndarray:
        if node_ids is None:
            mean, std = self._stats_for(None)
            return (values - mean) / std

        node_ids = np.asarray(node_ids)
        out = np.empty_like(values, dtype="float64")
        for node in set(node_ids.tolist()):
            mask = node_ids == node
            mean, std = self._stats_for(str(node))
            out[mask] = (values[mask] - mean) / std
        return out

    def inverse_transform(
        self, values: np.ndarray, node_ids: Optional[np.ndarray] = None
    ) -> np.ndarray:
        if node_ids is None:
            mean, std = self._stats_for(None)
            return values * std + mean

        node_ids = np.asarray(node_ids)
        out = np.empty_like(values, dtype="float64")
        for node in set(node_ids.tolist()):
            mask = node_ids == node
            mean, std = self._stats_for(str(node))
            out[mask] = values[mask] * std + mean
        return out

    def to_dict(self) -> Dict[str, object]:
        if self.mean_ is None or self.std_ is None:
            raise RuntimeError("Scaler.fit 을 먼저 호출해야 합니다")
        return {
            "kind": "standard_per_node",
            "features": self.features,
            "global": {
                "mean": [float(x) for x in self.mean_],
                "std": [float(x) for x in self.std_],
            },
            "per_node": {
                node: {"mean": [float(x) for x in mean], "std": [float(x) for x in std]}
                for node, (mean, std) in sorted(self.per_node_.items())
            },
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, object]) -> "Scaler":
        scaler = cls(list(payload["features"]))  # type: ignore[arg-type]
        glob = payload["global"]  # type: ignore[index]
        scaler.mean_ = np.asarray(glob["mean"], dtype="float64")  # type: ignore[index]
        scaler.std_ = np.asarray(glob["std"], dtype="float64")  # type: ignore[index]
        scaler.per_node_ = {
            node: (
                np.asarray(stats["mean"], dtype="float64"),
                np.asarray(stats["std"], dtype="float64"),
            )
            for node, stats in (payload.get("per_node") or {}).items()  # type: ignore[union-attr]
        }
        return scaler
