"""LSTM Autoencoder 추론 — numpy 만 사용 (이슈: AI 이상징후 연구 기능).

**이 모듈은 안전 경보와 무관하다.** AlertLevel 을 만들지도, alert_service 나
alert_publisher 를 호출하지도 않는다.

torch 를 쓰지 않는 이유: 백엔드는 MQTT 수신과 안전 경보 판정을 하는 안전 필수
컨테이너다. 학습 프레임워크가 여기 들어가면 이미지가 수백 MB 늘고 기동 실패 지점이
하나 더 생기는데, 그 대가로 얻는 것이 없다. 이 모델은 LSTM 두 개와 Linear 세 개가
전부라 numpy 행렬곱으로 그대로 돌아간다.

가중치는 experiments/lstm_anomaly/src/export_weights.py 가 만든 .npz 를 읽는다.
PyTorch LSTM 의 게이트 순서(i, f, g, o)와 weight 레이아웃을 그대로 따른다 —
이 순서가 틀리면 예외 없이 조용히 엉뚱한 값이 나오므로, 등가성을 테스트로 고정한다.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


def _sigmoid(x: np.ndarray) -> np.ndarray:
    # 큰 음수에서 exp 가 overflow 하지 않도록 분기한다. RuntimeWarning 이 로그를
    # 뒤덮으면 진짜 문제를 놓친다.
    out = np.empty_like(x)
    positive = x >= 0
    out[positive] = 1.0 / (1.0 + np.exp(-x[positive]))
    exp_x = np.exp(x[~positive])
    out[~positive] = exp_x / (1.0 + exp_x)
    return out


def _lstm_forward(
    x: np.ndarray,
    weight_ih: np.ndarray,
    weight_hh: np.ndarray,
    bias_ih: np.ndarray,
    bias_hh: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray]:
    """단층 LSTM. x=[B, T, in] -> (출력 [B, T, hidden], 마지막 hidden [B, hidden]).

    PyTorch 규약: weight_ih=[4H, in], weight_hh=[4H, H], 게이트 순서 i|f|g|o.
    """
    batch, steps, _ = x.shape
    hidden_size = weight_hh.shape[1]
    h = np.zeros((batch, hidden_size), dtype="float32")
    c = np.zeros((batch, hidden_size), dtype="float32")
    outputs = np.empty((batch, steps, hidden_size), dtype="float32")

    w_ih_t = weight_ih.T
    w_hh_t = weight_hh.T
    bias = bias_ih + bias_hh

    for t in range(steps):
        gates = x[:, t, :] @ w_ih_t + h @ w_hh_t + bias
        i = _sigmoid(gates[:, 0:hidden_size])
        f = _sigmoid(gates[:, hidden_size:2 * hidden_size])
        g = np.tanh(gates[:, 2 * hidden_size:3 * hidden_size])
        o = _sigmoid(gates[:, 3 * hidden_size:4 * hidden_size])
        c = f * c + i * g
        h = o * np.tanh(c)
        outputs[:, t, :] = h

    return outputs, h


@dataclass
class ModelArtifact:
    """추론에 필요한 전부. feature 순서가 곧 계약이다."""
    features: List[str]
    sequence_length: int
    resample_interval_s: int
    model_version: str
    threshold: float
    weights: Dict[str, np.ndarray]
    scaler_global: Tuple[np.ndarray, np.ndarray]
    scaler_per_node: Dict[str, Tuple[np.ndarray, np.ndarray]]
    recent_window_steps: int = 6
    recent_weight: float = 0.7
    is_research_only: bool = True
    data_limitation: Optional[str] = None

    @property
    def n_features(self) -> int:
        return len(self.features)

    def scaler_for(self, node_id: str) -> Tuple[np.ndarray, np.ndarray]:
        return self.scaler_per_node.get(node_id, self.scaler_global)

    def knows_node(self, node_id: str) -> bool:
        return node_id in self.scaler_per_node


def load_artifact(artifact_dir: Path) -> ModelArtifact:
    """artifact 디렉토리를 읽는다. 하나라도 없으면 예외 — 반쪽 모델로 추론하지 않는다."""
    import json

    manifest = json.loads((artifact_dir / "feature_manifest.json").read_text(encoding="utf-8"))
    threshold = json.loads((artifact_dir / "threshold.json").read_text(encoding="utf-8"))
    scaler = json.loads((artifact_dir / "scaler.json").read_text(encoding="utf-8"))

    if scaler["features"] != manifest["features"]:
        raise ValueError(
            "scaler.json 과 feature_manifest.json 의 feature 순서가 다릅니다. "
            "이 상태로 추론하면 값이 엉뚱한 채널의 통계로 정규화됩니다."
        )

    with np.load(artifact_dir / "model_weights.npz") as data:
        weights = {k: data[k] for k in data.files if not k.startswith("_")}

    limitation = None
    training_manifest_path = artifact_dir / "training_manifest.json"
    if training_manifest_path.exists():
        training = json.loads(training_manifest_path.read_text(encoding="utf-8"))
        limitation = training.get("data_limitation")

    return ModelArtifact(
        features=list(manifest["features"]),
        sequence_length=int(manifest["sequence_length"]),
        resample_interval_s=int(manifest["resample_interval_s"]),
        model_version=str(manifest["model_version"]),
        threshold=float(threshold["threshold"]),
        weights=weights,
        scaler_global=(
            np.asarray(scaler["global"]["mean"], dtype="float32"),
            np.asarray(scaler["global"]["std"], dtype="float32"),
        ),
        scaler_per_node={
            node: (
                np.asarray(stats["mean"], dtype="float32"),
                np.asarray(stats["std"], dtype="float32"),
            )
            for node, stats in (scaler.get("per_node") or {}).items()
        },
        data_limitation=limitation,
    )


def reconstruct(artifact: ModelArtifact, x: np.ndarray) -> np.ndarray:
    """[B, T, F] -> [B, T, F]. 학습 때의 forward 와 같은 경로여야 한다."""
    w = artifact.weights
    _, hidden = _lstm_forward(
        x, w["encoder.weight_ih_l0"], w["encoder.weight_hh_l0"],
        w["encoder.bias_ih_l0"], w["encoder.bias_hh_l0"],
    )
    latent = hidden @ w["to_latent.weight"].T + w["to_latent.bias"]
    seeded = latent @ w["from_latent.weight"].T + w["from_latent.bias"]
    # latent 를 T 스텝으로 펼쳐 디코더에 넣는다. 디코더는 입력 시퀀스를 보지 않는다.
    repeated = np.repeat(seeded[:, None, :], x.shape[1], axis=1)
    decoded, _ = _lstm_forward(
        repeated, w["decoder.weight_ih_l0"], w["decoder.weight_hh_l0"],
        w["decoder.bias_ih_l0"], w["decoder.bias_hh_l0"],
    )
    return decoded @ w["output.weight"].T + w["output.bias"]


def feature_errors(
    artifact: ModelArtifact,
    prediction: np.ndarray,
    target: np.ndarray,
    mask: np.ndarray,
) -> np.ndarray:
    """window 별·feature 별 복원 오차 [B, F].

    최근 60초에 가중치를 몰아준다 — 방금 시작된 이상이 9분간의 정상에 희석되면
    실시간 탐지에서 그 지연은 그대로 탐지 실패다.

    채널이 window 내내 미관측이면 NaN 이다. 0 이 아니다 — 0 은 "완벽히 정상" 이라는
    뜻이라 꺼진 센서가 가장 정상적인 센서가 되어버린다.
    """
    steps = prediction.shape[1]
    recent = max(1, min(artifact.recent_window_steps, steps))
    weights = np.full(steps, (1.0 - artifact.recent_weight) / max(1, steps - recent),
                      dtype="float32")
    if steps > recent:
        weights[-recent:] = artifact.recent_weight / recent
    else:
        weights[:] = 1.0 / steps
    weights = weights.reshape(1, steps, 1)

    mask_f = mask.astype("float32")
    absolute = np.abs(prediction - target) * mask_f
    numerator = (absolute * weights).sum(axis=1)
    denominator = (mask_f * weights).sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(denominator > 0, numerator / denominator, np.nan)


def anomaly_score(errors: np.ndarray) -> np.ndarray:
    """[B, F] -> [B]. 전 채널이 NaN 이면 점수도 NaN — '정상' 이 아니라 '판단 불가'."""
    with np.errstate(invalid="ignore"):
        return np.nanmean(errors, axis=1)


def top_contributors(
    artifact: ModelArtifact, errors: np.ndarray, k: int = 3
) -> List[Dict[str, float]]:
    pairs = [
        {"metric": name, "error": round(float(value), 4)}
        for name, value in zip(artifact.features, errors.tolist())
        if not np.isnan(value)
    ]
    pairs.sort(key=lambda item: item["error"], reverse=True)
    return pairs[:k]
