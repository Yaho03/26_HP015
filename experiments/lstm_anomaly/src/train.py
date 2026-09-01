"""학습 · 평가 · artifact 저장 (§5, §6, §7, §8).

실행:
  experiments/lstm_anomaly/.venv/bin/python -m src.train \\
      --source <tap.txt 또는 dump.csv.gz> [--source ...] \\
      --out artifacts/run-YYYYMMDD

이 스크립트는 성능이 나쁘면 나쁘다고 쓴다. baseline 을 못 이기면
STATUS: REJECTED_BASELINE_NOT_BEATEN 을 남기고 끝낸다 (§7.2).
"""
from __future__ import annotations

import argparse
import json
import logging
import random
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import torch
import yaml
from torch.utils.data import DataLoader, TensorDataset

from src.anomaly_injection import inject
from src.baselines import ALL_BASELINES
from src.evaluate import evaluate
from src.model import LSTMAutoencoder, anomaly_scores, feature_errors, masked_loss
from src.pipeline import prepare, scaled
from src.scoring import fit_threshold
from src.windowing import node_split

logger = logging.getLogger("train")

STATUS_READY = "READY_FOR_RESEARCH_DISPLAY"
STATUS_DATA_PENDING = "MODEL_NOT_TRAINED_DATA_PENDING"
STATUS_BLOCKED = "BLOCKED_DATA_INSUFFICIENT"
STATUS_BASELINE = "REJECTED_BASELINE_NOT_BEATEN"
STATUS_LEAKAGE = "REJECTED_DATA_LEAKAGE_RISK"
STATUS_GENERALIZATION = "REJECTED_GENERALIZATION_FAILURE"


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.use_deterministic_algorithms(True, warn_only=True)


def git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return "unknown"


def _infer(model: LSTMAutoencoder, x: np.ndarray, mask: np.ndarray,
           cfg: dict, batch_size: int = 256):
    """복원 -> feature 오차 -> window 점수."""
    if x.shape[0] == 0:
        return np.zeros((0, x.shape[-1])), np.zeros((0,))
    errors: List[torch.Tensor] = []
    model_was_training = model.training
    model.train(False)
    with torch.no_grad():
        for start in range(0, x.shape[0], batch_size):
            xb = torch.from_numpy(x[start:start + batch_size])
            mb = torch.from_numpy(mask[start:start + batch_size])
            errors.append(feature_errors(
                model(xb), xb, mb,
                recent_steps=int(cfg["scoring"]["recent_window_steps"]),
                recent_weight=float(cfg["scoring"]["recent_weight"]),
            ))
    model.train(model_was_training)
    stacked = torch.cat(errors)
    return stacked.numpy(), anomaly_scores(stacked).numpy()


def train_model(prepared, cfg: dict) -> tuple:
    """정상 train window 로만 학습한다. 이상 라벨을 쓰지 않는다 (§2.1 비지도)."""
    features = prepared.features
    x_train = scaled(prepared.train, prepared.scaler)
    x_val = scaled(prepared.val, prepared.scaler)

    model = LSTMAutoencoder(
        len(features),
        hidden_size=int(cfg["model"]["hidden_size"]),
        latent_size=int(cfg["model"]["latent_size"]),
        num_layers=int(cfg["model"]["num_layers"]),
    )
    optimizer = torch.optim.Adam(model.parameters(), lr=float(cfg["train"]["learning_rate"]))
    loader = DataLoader(
        TensorDataset(torch.from_numpy(x_train), torch.from_numpy(prepared.train.observed)),
        batch_size=int(cfg["train"]["batch_size"]), shuffle=True,
    )
    loss_kind = "mae" if cfg["model"]["loss"] == "masked_mae" else "huber"

    best_val = float("inf")
    best_state = None
    patience = int(cfg["train"]["early_stopping_patience"])
    stale = 0
    history: List[Dict[str, float]] = []

    val_x = torch.from_numpy(x_val)
    val_mask = torch.from_numpy(prepared.val.observed)

    for epoch in range(int(cfg["train"]["epochs"])):
        model.train(True)
        total = 0.0
        for xb, mb in loader:
            optimizer.zero_grad()
            loss = masked_loss(model(xb), xb, mb, kind=loss_kind)
            loss.backward()
            optimizer.step()
            total += float(loss) * xb.size(0)
        train_loss = total / max(1, x_train.shape[0])

        model.train(False)
        with torch.no_grad():
            val_loss = float(masked_loss(model(val_x), val_x, val_mask, kind=loss_kind))
        history.append({"epoch": epoch, "train_loss": train_loss, "val_loss": val_loss})

        # early stopping 은 validation loss 만 본다 (§5). test 를 보면 그 순간
        # test 가 더 이상 held-out 이 아니다.
        if val_loss < best_val - 1e-6:
            best_val, stale = val_loss, 0
            best_state = {k: v.clone() for k, v in model.state_dict().items()}
        else:
            stale += 1
            if stale >= patience:
                logger.info("early stopping at epoch %d (best val %.6f)", epoch, best_val)
                break

    if best_state is not None:
        model.load_state_dict(best_state)
    return model, history, best_val


def run(sources: List[str], out_dir: Path, config_path: Path,
        *, allow_nonstationary: bool = False) -> Dict[str, object]:
    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    set_seed(int(cfg["seed"]))
    out_dir.mkdir(parents=True, exist_ok=True)

    prepared = prepare(sources, cfg)
    report = prepared.report
    (out_dir / "data_quality_report.txt").write_text(report.render(), encoding="utf-8")

    result: Dict[str, object] = {
        "status": None,
        "data_quality": {
            "status": report.status,
            "nodes": report.nodes,
            "features_valid": report.features_valid,
            "features_rejected": [asdict(v) for v in report.features_rejected],
            "notes": report.notes,
        },
        "features_used": prepared.features,
        "split": prepared.split_meta,
        "node_windows": prepared.node_windows,
        "exclusions": [asdict(e) for e in prepared.exclusions],
    }

    result["data_quality"]["is_stationary"] = report.is_stationary
    result["data_quality"]["drift_ratio_by_feature"] = report.drift_ratio_by_feature

    if len(prepared.features) < 2 or len(prepared.train) == 0 or len(prepared.val) == 0:
        result["status"] = STATUS_DATA_PENDING if not prepared.features else STATUS_BLOCKED
        result["reason"] = (
            f"유효 feature {len(prepared.features)}개, "
            f"train window {len(prepared.train)}개, val window {len(prepared.val)}개 — "
            f"학습 조건 미충족. 성능 수치를 만들어내지 않는다."
        )
        (out_dir / "metrics.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return result

    # 정상성 게이트. 기준선이 관측 기간 내내 흐르면 "반복되는 정상 패턴" 이 없고,
    # 과거로 학습해 미래를 판정한다는 전제 자체가 성립하지 않는다.
    # 여기서 멈추는 이유: 이 상태로도 숫자는 나온다. 그 숫자가 뜻하는 것은
    # 탐지 성능이 아니라 "기준선이 얼마나 흘렀는가" 인데, 표에 적히는 순간
    # 아무도 그 차이를 알 수 없게 된다 (§0.10).
    worst = max(report.drift_ratio_by_feature.values(), default=0.0)
    if not report.is_stationary and allow_nonstationary:
        # §9 "연구용 시연이 명시적으로 허용된 경우" 경로. 게이트를 끄더라도
        # 그 사실이 artifact 와 화면까지 따라가야 한다 — 수치만 떼어내 인용하면
        # 그것이 곧 §0.10 위반이다.
        result["data_limitation"] = {
            "nonstationary_override": True,
            "max_drift_ratio": worst,
            "meaning": (
                f"관측 기간 동안 기준선이 window 내 변동의 {worst:.1f}배만큼 이동했다. "
                f"아래 Precision/Recall 은 탐지 성능이 아니라 '기준선이 얼마나 흘렀는가' 를 "
                f"함께 반영한 값이며, 현장 성능으로 인용할 수 없다."
            ),
        }
    if not report.is_stationary and not allow_nonstationary:
        result["status"] = STATUS_BLOCKED
        result["reason"] = (
            f"기준선 이동이 지배적이라 학습을 진행하지 않는다 (최대 드리프트 {worst:.1f}x). "
            f"관측 기간 동안 정상값 자체가 흘러 반복되는 정상 패턴이 없다. "
            f"주입 이상(3~8x window 변동)이 자연 드리프트에 묻히므로 "
            f"어떤 Precision/Recall 을 내도 탐지 성능을 뜻하지 않는다. "
            f"필요한 것은 모델 조정이 아니라 센서 안정화 후의 더 긴 관측이다."
        )
        (out_dir / "metrics.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return result

    model, history, best_val = train_model(prepared, cfg)

    # threshold 는 validation 정상 점수로만 정한다 (§6.2).
    x_val = scaled(prepared.val, prepared.scaler)
    val_errors, val_scores = _infer(model, x_val, prepared.val.observed, cfg)
    threshold_art = fit_threshold(
        val_scores, val_errors, prepared.features,
        quantile=float(cfg["scoring"]["threshold_quantile"]),
    )

    # 이상 주입은 test 복사본에만 (§7).
    inj = cfg["anomaly_injection"]
    dirty_values, dirty_observed, labels, records = inject(
        prepared.test.values, prepared.test.observed, prepared.features,
        seed=int(inj["seed"]), contamination_ratio=float(inj["contamination_ratio"]),
    )
    # 주입본도 원본 window 의 node_ids 로 변환한다 — 노드별 scaler 이므로
    # 어느 노드 통계를 쓰느냐가 점수를 바꾼다.
    dirty_scaled = scaled(prepared.test, prepared.scaler, dirty_values, dirty_observed)

    _, test_scores = _infer(model, dirty_scaled, dirty_observed, cfg)
    lstm_metrics = evaluate(
        test_scores, labels, threshold_art.threshold,
        node_ids=prepared.test.node_ids, injection_records=records,
    )

    # baseline 은 같은 test 구간·같은 라벨·같은 threshold 규칙으로 잰다 (§7.2).
    x_train = scaled(prepared.train, prepared.scaler)
    baseline_results: Dict[str, Dict] = {}
    for cls in ALL_BASELINES:
        base = cls(
            recent_steps=int(cfg["scoring"]["recent_window_steps"]),
            recent_weight=float(cfg["scoring"]["recent_weight"]),
        ).fit(x_train, prepared.train.observed)
        base_val = base.score(x_val, prepared.val.observed)
        base_threshold = float(np.nanquantile(
            base_val, float(cfg["scoring"]["threshold_quantile"])
        ))
        base_metrics = evaluate(
            base.score(dirty_scaled, dirty_observed), labels, base_threshold,
            node_ids=prepared.test.node_ids, injection_records=records,
        )
        baseline_results[base.name] = {
            "threshold": base_threshold, **base_metrics.to_dict()
        }

    best_baseline = max(baseline_results.items(), key=lambda kv: kv[1]["f1"])
    beats_baseline = lstm_metrics.f1 > best_baseline[1]["f1"]

    # 노드 일반화 (§4.3-2). 학습 자체를 다시 하지 않고, 이미 학습된 모델이
    # 노드별로 고르게 동작하는지를 본다. 노드 하나만 유독 나쁘면 그 노드의
    # 분포가 학습에 반영되지 않았다는 뜻이다.
    per_node_f1 = {n: v["f1"] for n, v in lstm_metrics.by_node.items()}
    worst_node_f1 = min(per_node_f1.values()) if per_node_f1 else 0.0

    result.update({
        "training": {
            "epochs_run": len(history),
            "best_val_loss": best_val,
            "history": history[-10:],
        },
        "threshold": threshold_art.to_dict(),
        "lstm": lstm_metrics.to_dict(),
        "baselines": baseline_results,
        "best_baseline": {"name": best_baseline[0], "f1": best_baseline[1]["f1"]},
        "beats_baseline": beats_baseline,
        "injection": {
            "n_injected": int(labels.sum()),
            "n_test_windows": int(len(labels)),
            "records": [r.to_dict() for r in records[:50]],
        },
    })

    purge_ok = int(prepared.split_meta.get("purge_gap_s", 0)) > 0
    if not purge_ok:
        result["status"] = STATUS_LEAKAGE
        result["reason"] = "purge gap 을 적용하지 못해 train/val/test 사이 leakage 위험이 남는다."
    elif not beats_baseline:
        result["status"] = STATUS_BASELINE
        result["reason"] = (
            f"LSTM F1={lstm_metrics.f1:.4f} 이 최고 baseline "
            f"{best_baseline[0]} F1={best_baseline[1]['f1']:.4f} 을 넘지 못했다. "
            f"복잡도를 정당화할 근거가 없다."
        )
    elif per_node_f1 and worst_node_f1 < 0.5 * lstm_metrics.f1:
        result["status"] = STATUS_GENERALIZATION
        result["reason"] = (
            f"노드별 F1 편차가 크다 (최저 {worst_node_f1:.4f} vs 전체 {lstm_metrics.f1:.4f}). "
            f"특정 노드에만 맞춰졌을 가능성이 있다."
        )
    else:
        result["status"] = STATUS_READY
        result["reason"] = (
            "연구용 화면 표시 가능 상태다. 현장 안전 사용 승인이 아니다."
        )

    _save_artifacts(out_dir, model, prepared, threshold_art, cfg, config_path, sources, result)
    return result


def _save_artifacts(out_dir, model, prepared, threshold_art, cfg, config_path, sources, result):
    """§8 이 요구하는 artifact 일습."""
    torch.save(model.state_dict(), out_dir / "model.pt")

    (out_dir / "scaler.json").write_text(
        json.dumps(prepared.scaler.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "threshold.json").write_text(
        json.dumps(threshold_art.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # feature_manifest 가 단일 정본이다. 추론 시 입력 feature 이름과 **순서**를
    # 이것과 대조해 다르면 feature_mismatch 를 낸다 (§9.2).
    (out_dir / "feature_manifest.json").write_text(json.dumps({
        "model_version": "lstm-ae-v0.1.0",
        "features": prepared.features,
        "n_features": len(prepared.features),
        "sequence_length": int(cfg["windowing"]["sequence_length"]),
        "resample_interval_s": int(cfg["preprocessing"]["resample_interval_s"]),
        "nodes": prepared.report.nodes,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    (out_dir / "metrics.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "training_manifest.json").write_text(json.dumps({
        "model_version": "lstm-ae-v0.1.0",
        "git_commit": git_commit(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "random_seed": int(cfg["seed"]),
        "sources": [str(s) for s in sources],
        "nodes_used": prepared.report.nodes,
        "features_used": prepared.features,
        "features_rejected": [
            {"metric": v.metric, "reason": v.reason}
            for v in prepared.report.features_rejected
        ],
        "data_start_at": str(prepared.report.start_at),
        "data_end_at": str(prepared.report.end_at),
        "split": prepared.split_meta,
        "resample_interval_s": int(cfg["preprocessing"]["resample_interval_s"]),
        "window_length": int(cfg["windowing"]["sequence_length"]),
        "missing_data_rules": {
            "max_interpolate_gap_s": cfg["preprocessing"]["max_interpolate_gap_s"],
            "max_window_gap_s": cfg["preprocessing"]["max_window_gap_s"],
            "min_observed_ratio": cfg["preprocessing"]["min_observed_ratio"],
            "constant_run_reject_s": cfg["preprocessing"]["constant_run_reject_s"],
        },
        "scaler_kind": cfg["preprocessing"]["scaler"],
        "architecture": {
            "type": "LSTMAutoencoder",
            "hidden_size": cfg["model"]["hidden_size"],
            "latent_size": cfg["model"]["latent_size"],
            "num_layers": cfg["model"]["num_layers"],
            "loss": cfg["model"]["loss"],
        },
        "hyperparameters": cfg["train"],
        "threshold_method": (
            f"validation 정상 score 의 {cfg['scoring']['threshold_quantile']} 분위수. "
            f"test 를 사용하지 않음."
        ),
        "live_simulation_split": prepared.report.live_simulation_split,
        "config": cfg,
        "config_path": str(config_path),
        "status": result["status"],
        "is_research_only": True,
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="LSTM Autoencoder 이상탐지 학습")
    parser.add_argument("--source", action="append", required=True,
                        help="MQTT tap .txt 또는 sensor_data CSV(.gz). 여러 번 지정 가능")
    parser.add_argument("--out", default="artifacts/latest")
    parser.add_argument("--config", default="configs/default.yaml")
    parser.add_argument(
        "--allow-nonstationary", action="store_true",
        help="드리프트 게이트를 무시하고 학습한다. §9 의 '연구용 시연 명시적 허용' "
             "경로이며, 나온 수치는 탐지 성능이 아니라는 표시가 artifact 에 남는다.")
    args = parser.parse_args()

    result = run([Path(s) for s in args.source], Path(args.out), Path(args.config),
                 allow_nonstationary=args.allow_nonstationary)
    print(json.dumps({
        "status": result["status"],
        "reason": result.get("reason"),
        "features_used": result.get("features_used"),
        "lstm_f1": result.get("lstm", {}).get("f1"),
        "best_baseline": result.get("best_baseline"),
        "data_limitation": result.get("data_limitation"),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
