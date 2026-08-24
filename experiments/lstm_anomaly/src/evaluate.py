"""평가 지표 (§7.1).

window 단위 평가를 쓴다. 이유: 주입 라벨이 window 단위로 붙고(§7 의 주입기가
window 를 통째로 오염시킨다), 실시간 서비스도 10초마다 window 하나를 판정하기
때문이다. point 단위로 재면 평가와 운용의 단위가 어긋나 수치를 옮겨 쓸 수 없다.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Sequence

import numpy as np

from src.scoring import STATUS_ANOMALY, classify_windows


@dataclass
class Metrics:
    precision: float
    recall: float
    f1: float
    false_positive_rate: float
    n_windows: int
    n_positive: int
    tp: int
    fp: int
    fn: int
    tn: int
    recall_by_type: Dict[str, float] = field(default_factory=dict)
    mean_detection_delay_steps: Optional[float] = None
    by_node: Dict[str, Dict[str, float]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


def _prf(predicted: np.ndarray, labels: np.ndarray) -> Dict[str, float]:
    tp = int(np.sum(predicted & labels))
    fp = int(np.sum(predicted & ~labels))
    fn = int(np.sum(~predicted & labels))
    tn = int(np.sum(~predicted & ~labels))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    # 정상 구간 오경보율 — 안전 시스템에서 가장 중요한 수치다. 아무리 recall 이
    # 높아도 정상에서 계속 울리면 사람이 화면을 끈다.
    fpr = fp / (fp + tn) if fp + tn else 0.0
    return {
        "precision": precision, "recall": recall, "f1": f1,
        "false_positive_rate": fpr, "tp": tp, "fp": fp, "fn": fn, "tn": tn,
    }


def evaluate(
    scores: np.ndarray,
    labels: np.ndarray,
    threshold: float,
    *,
    node_ids: Optional[np.ndarray] = None,
    injection_records: Optional[Sequence] = None,
    apply_persistence: bool = False,
    consecutive_to_anomaly: int = 3,
) -> Metrics:
    """점수와 라벨로 지표를 만든다.

    apply_persistence: 실시간 지속 조건(3회 연속)을 적용한 뒤 평가할지 여부.
    주입 평가에서는 window 가 시간순으로 이어져 있지 않으므로 기본은 끈다.
    끈 상태의 수치가 모델 자체의 분리력이고, 켠 수치가 운용 시 기대치다.
    """
    scores = np.asarray(scores, dtype="float64")
    labels = np.asarray(labels, dtype=bool)

    if apply_persistence:
        statuses = classify_windows(
            scores, threshold, consecutive_to_anomaly=consecutive_to_anomaly
        )
        predicted = np.array([s == STATUS_ANOMALY for s in statuses])
    else:
        # NaN 은 '이상' 으로 예측하지 않는다. 판단 불가를 탐지로 세면 센서가 꺼진
        # 것만으로 recall 이 올라간다.
        predicted = np.where(np.isnan(scores), False, scores > threshold)

    core = _prf(predicted, labels)
    metrics = Metrics(
        precision=core["precision"], recall=core["recall"], f1=core["f1"],
        false_positive_rate=core["false_positive_rate"],
        n_windows=int(labels.size), n_positive=int(labels.sum()),
        tp=core["tp"], fp=core["fp"], fn=core["fn"], tn=core["tn"],
    )

    if injection_records:
        by_type: Dict[str, List[bool]] = {}
        for record in injection_records:
            by_type.setdefault(record.anomaly_type, []).append(
                bool(predicted[record.window_index])
            )
        metrics.recall_by_type = {
            name: float(np.mean(hits)) for name, hits in sorted(by_type.items())
        }
        # 탐지 지연: 이상이 시작된 스텝부터 window 끝까지의 거리. 점수가 최근
        # 60초에 가중되므로, 이상이 window 끝에 가까울수록 빨리 잡힌다는 뜻이다.
        delays = [
            record.end_step - record.start_step
            for record in injection_records
            if predicted[record.window_index]
        ]
        metrics.mean_detection_delay_steps = float(np.mean(delays)) if delays else None

    if node_ids is not None:
        node_ids = np.asarray(node_ids)
        for node in sorted(set(node_ids.tolist())):
            mask = node_ids == node
            if not mask.any():
                continue
            metrics.by_node[str(node)] = _prf(predicted[mask], labels[mask])

    return metrics


def sweep_threshold(
    scores: np.ndarray, labels: np.ndarray, quantiles: Sequence[float]
) -> List[Dict[str, float]]:
    """threshold 민감도. **validation 정상 점수로만** 호출해야 한다.

    test 점수를 넣어 최적 threshold 를 고르는 데 쓰면 그 순간 leakage 다.
    이 함수는 그것을 막을 수 없으므로 호출부가 지켜야 한다.
    """
    scores = np.asarray(scores, dtype="float64")
    clean = scores[~np.isnan(scores)]
    out = []
    for q in quantiles:
        threshold = float(np.quantile(clean, q))
        row = {"quantile": q, "threshold": threshold}
        row.update(_prf(np.where(np.isnan(scores), False, scores > threshold),
                        np.asarray(labels, dtype=bool)))
        out.append(row)
    return out
