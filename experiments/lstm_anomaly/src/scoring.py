"""Threshold 결정과 실시간 상태 판정 (§6.2, §9.2).

여기서 정하는 상태는 **기존 안전 경보 등급과 완전히 별개다.** AlertLevel 로
변환하지 않고, 변환할 수 있는 함수도 두지 않는다. 그런 함수가 하나라도 있으면
언젠가 누가 호출한다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

import numpy as np

# §9.2 응답 상태. 앞의 넷은 "판단하지 않았다", 뒤의 셋은 "판단했다" 이다.
STATUS_MODEL_NOT_READY = "model_not_ready"
STATUS_INSUFFICIENT_DATA = "insufficient_data"
STATUS_STALE_DATA = "stale_data"
STATUS_FEATURE_MISMATCH = "feature_mismatch"
STATUS_NORMAL = "normal_pattern"
STATUS_CANDIDATE = "anomaly_candidate"
STATUS_ANOMALY = "anomaly"

# 판단하지 않은 상태들. 이것을 normal_pattern 으로 바꾸지 않는다 (§9.2 마지막 줄).
UNDECIDED_STATUSES = frozenset({
    STATUS_MODEL_NOT_READY,
    STATUS_INSUFFICIENT_DATA,
    STATUS_STALE_DATA,
    STATUS_FEATURE_MISMATCH,
})


@dataclass
class ThresholdArtifact:
    """threshold.json 의 내용 (§6.2)."""
    threshold: float
    quantile: float
    validation_score_stats: Dict[str, float]
    feature_error_stats: Dict[str, Dict[str, float]]
    n_validation_windows: int

    def to_dict(self) -> Dict[str, object]:
        return {
            "threshold": self.threshold,
            "threshold_quantile": self.quantile,
            "validation_score_stats": self.validation_score_stats,
            "feature_error_stats": self.feature_error_stats,
            "n_validation_windows": self.n_validation_windows,
        }


def fit_threshold(
    validation_scores: np.ndarray,
    validation_feature_errors: np.ndarray,
    features: Sequence[str],
    *,
    quantile: float = 0.99,
) -> ThresholdArtifact:
    """정상 validation 점수 분포만으로 threshold 를 정한다 (§6.2).

    test 를 쓰지 않는 것이 핵심이다. test 로 threshold 를 고르면 그 test 성능은
    더 이상 일반화 추정치가 아니라 fitting 결과다.
    """
    scores = np.asarray(validation_scores, dtype="float64")
    scores = scores[~np.isnan(scores)]
    if scores.size == 0:
        raise ValueError(
            "validation 점수가 없습니다. threshold 를 만들 근거가 없으므로 "
            "임의값을 쓰지 않고 실패시킵니다."
        )

    errors = np.asarray(validation_feature_errors, dtype="float64")
    feature_stats: Dict[str, Dict[str, float]] = {}
    for i, name in enumerate(features):
        column = errors[:, i]
        column = column[~np.isnan(column)]
        if column.size == 0:
            feature_stats[name] = {"observed": 0.0}
            continue
        feature_stats[name] = {
            "mean": float(column.mean()),
            "std": float(column.std()),
            "p50": float(np.percentile(column, 50)),
            "p99": float(np.percentile(column, 99)),
            "max": float(column.max()),
            "observed": float(column.size),
        }

    return ThresholdArtifact(
        threshold=float(np.quantile(scores, quantile)),
        quantile=quantile,
        validation_score_stats={
            "mean": float(scores.mean()),
            "std": float(scores.std()),
            "p50": float(np.percentile(scores, 50)),
            "p95": float(np.percentile(scores, 95)),
            "p99": float(np.percentile(scores, 99)),
            "max": float(scores.max()),
        },
        feature_error_stats=feature_stats,
        n_validation_windows=int(scores.size),
    )


class PersistenceGate:
    """연속 초과 조건 (§6.2 마지막 문단).

    한 번 튄 값으로 상태를 뒤집지 않는다. threshold 를 넘은 뒤에도
    consecutive_to_anomaly 회 연속이라야 anomaly 로 가고, 내려온 뒤에도
    consecutive_to_normal 회 연속이라야 normal_pattern 으로 돌아온다.

    점수가 NaN(판단 불가)이면 카운터를 **증가시키지도 초기화하지도 않는다.**
    데이터가 없는 동안을 '정상이 이어졌다' 로 세면 이상이 진행 중인데도 상태가
    복구되고, '이상이 이어졌다' 로 세면 센서가 꺼진 것만으로 경보가 뜬다.
    """

    def __init__(
        self,
        threshold: float,
        *,
        consecutive_to_anomaly: int = 3,
        consecutive_to_normal: int = 3,
    ) -> None:
        self.threshold = threshold
        self.consecutive_to_anomaly = consecutive_to_anomaly
        self.consecutive_to_normal = consecutive_to_normal
        self.status: str = STATUS_NORMAL
        self.exceedances = 0
        self.recoveries = 0

    def update(self, score: Optional[float]) -> str:
        if score is None or np.isnan(score):
            return self.status

        if score > self.threshold:
            self.exceedances += 1
            self.recoveries = 0
            if self.exceedances >= self.consecutive_to_anomaly:
                self.status = STATUS_ANOMALY
            elif self.status != STATUS_ANOMALY:
                self.status = STATUS_CANDIDATE
        else:
            self.recoveries += 1
            self.exceedances = 0
            if self.recoveries >= self.consecutive_to_normal:
                self.status = STATUS_NORMAL
        return self.status


def classify_windows(
    scores: np.ndarray,
    threshold: float,
    *,
    consecutive_to_anomaly: int = 3,
    consecutive_to_normal: int = 3,
) -> List[str]:
    """연속된 window 점수 열에 지속 조건을 적용한 상태 열."""
    gate = PersistenceGate(
        threshold,
        consecutive_to_anomaly=consecutive_to_anomaly,
        consecutive_to_normal=consecutive_to_normal,
    )
    out: List[str] = []
    for score in scores:
        if np.isnan(score):
            out.append(STATUS_INSUFFICIENT_DATA)
            continue
        out.append(gate.update(float(score)))
    return out
