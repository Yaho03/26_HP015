"""전체 파이프라인 end-to-end 검증.

이 파일이 필요한 이유: 2026-08-24 실측은 드리프트가 지배적이라 파이프라인이
BLOCKED_DATA_INSUFFICIENT 를 낸다. 그것이 옳은 판정인지, 아니면 **무엇을 넣어도
거절하는 코드**를 만든 것인지는 실측만으로는 구분할 수 없다.

그래서 정상 패턴이 실제로 반복되는 합성 데이터를 만들어, 같은 파이프라인이
학습에 성공하고 주입 이상을 탐지하는지 확인한다. 이게 통과해야만
실측에 대한 거절이 데이터 문제라는 주장이 성립한다.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import yaml

from src.data_loader import load_sources
from src.data_quality import diagnose
from src.train import STATUS_BLOCKED, STATUS_READY, run

BASE_TS = np.datetime64("2026-08-24T00:00:00")


def _write_tap(path: Path, *, hours: float, drift_pct: float, seed: int = 0) -> Path:
    """4노드 센서 tap 로그를 만든다.

    정상 패턴 = 노드별 고유 baseline + 공통 일주기성 진동 + 채널 간 고정 관계 + 노이즈.
    drift_pct 로 관측 기간 동안의 단조 이동을 넣는다 — 0 이면 정상(定常) 데이터다.
    """
    rng = np.random.default_rng(seed)
    nodes = ["sensor-01", "sensor-02", "sensor-03", "sensor-04"]
    # 노드별 baseline 을 크게 벌린다 — 실측에서 관찰된 8배 차이를 재현한다.
    baselines = {
        "sensor-01": dict(mq7=240000.0, mq136=34000.0, mq2=17700.0, t=26.4, h=54.7),
        "sensor-02": dict(mq7=239000.0, mq136=32000.0, mq2=18600.0, t=25.8, h=56.2),
        "sensor-03": dict(mq7=202000.0, mq136=5100.0, mq2=22600.0, t=27.0, h=54.2),
        "sensor-04": dict(mq7=343000.0, mq136=40500.0, mq2=5300.0, t=27.3, h=53.8),
    }
    n = int(hours * 3600)
    lines = []
    for node in nodes:
        b = baselines[node]
        phase = rng.uniform(0, 2 * np.pi)
        t = np.arange(n)
        # 10분 주기 진동 — 반복되는 정상 패턴. LSTM 이 배울 대상이다.
        cycle = np.sin(2 * np.pi * t / 600.0 + phase)
        ramp = np.linspace(0.0, drift_pct / 100.0, n)
        for i in range(0, n, 1):
            ts = (BASE_TS + np.timedelta64(i, "s")).astype("datetime64[ms]")
            wob = rng.normal(0, 0.004)
            # mq136 과 mq2 는 같은 진동을 공유한다 — cross_feature_break 가 깨뜨릴 관계.
            data = {
                "mq7_rs_ohm":   b["mq7"] * (1 + 0.02 * cycle[i] + ramp[i] + wob),
                "mq136_rs_ohm": b["mq136"] * (1 + 0.03 * cycle[i] + ramp[i] + rng.normal(0, 0.004)),
                "mq2_rs_ohm":   b["mq2"] * (1 + 0.03 * cycle[i] + ramp[i] + rng.normal(0, 0.004)),
                "mq7_r0_ohm": None,
                "co2_ppm": None,
            }
            lines.append(
                f"sensors/{node}/gas " + json.dumps({
                    "schema_version": "1.1",
                    "message_id": f"01M{node[-2:]}G{i:020d}",
                    "node_id": node,
                    "sampled_at": str(ts) + "Z",
                    "source_mode": "live",
                    "data": data,
                })
            )
            if i % 3 == 0:
                env = {
                    "temperature_c": b["t"] * (1 + 0.01 * cycle[i] + ramp[i] * 0.2) + rng.normal(0, 0.02),
                    "humidity_pct": b["h"] * (1 + 0.02 * cycle[i] + ramp[i] * 0.2) + rng.normal(0, 0.05),
                }
                lines.append(
                    f"sensors/{node}/env " + json.dumps({
                        "schema_version": "1.1",
                        "message_id": f"01M{node[-2:]}E{i:020d}",
                        "node_id": node,
                        "sampled_at": str(ts) + "Z",
                        "source_mode": "live",
                        "data": env,
                    })
                )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def stationary_tap(tmp_path_factory) -> Path:
    return _write_tap(tmp_path_factory.mktemp("e2e") / "stationary.txt",
                      hours=3.0, drift_pct=0.0, seed=7)


@pytest.fixture(scope="module")
def drifting_tap(tmp_path_factory) -> Path:
    return _write_tap(tmp_path_factory.mktemp("e2e") / "drift.txt",
                      hours=3.0, drift_pct=40.0, seed=7)


def _config(tmp_path: Path, **overrides) -> Path:
    cfg = yaml.safe_load(Path("configs/default.yaml").read_text(encoding="utf-8"))
    cfg["train"]["epochs"] = 12          # e2e 검증용 — 수렴 자체가 목적이 아니다
    cfg["train"]["early_stopping_patience"] = 5
    for key, value in overrides.items():
        section, _, field = key.partition(".")
        cfg[section][field] = value
    path = tmp_path / "cfg.yaml"
    path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    return path


# ---------------- 진단 단계 ----------------

def test_stationary_data_passes_the_drift_gate(stationary_tap):
    report = diagnose(load_sources([stationary_tap]))
    assert report.is_stationary, report.drift_ratio_by_feature
    assert report.status == "DATA_READY"


def test_drifting_data_fails_the_drift_gate(drifting_tap):
    """실측(최대 25.8x)과 같은 성질의 데이터는 거절되어야 한다."""
    report = diagnose(load_sources([drifting_tap]))
    assert not report.is_stationary
    assert max(report.drift_ratio_by_feature.values()) > 3.0


def test_null_only_channels_never_reach_features(stationary_tap):
    """co2_ppm 이 100% null 인 실측 상황 재현."""
    report = diagnose(load_sources([stationary_tap]))
    assert "co2_ppm" not in report.features_valid
    assert "mq7_r0_ohm" not in report.features_valid


# ---------------- 학습 단계 ----------------

@pytest.fixture(scope="module")
def stationary_result(stationary_tap, tmp_path_factory):
    out = tmp_path_factory.mktemp("run")
    return run([stationary_tap], out / "art", _config(out)), out / "art"


def test_stationary_data_actually_trains(stationary_result):
    """거절만 하는 코드가 아니라는 증명. 이게 실패하면 실측 거절도 못 믿는다."""
    result, _ = stationary_result
    assert result["status"] != STATUS_BLOCKED, result.get("reason")
    assert result["lstm"]["f1"] > 0.0
    assert result["training"]["epochs_run"] > 0


def test_lstm_detects_injected_anomalies_above_chance(stationary_result):
    result, _ = stationary_result
    lstm = result["lstm"]
    # 30% 오염이므로 무작위 추측의 precision 은 0.3 이다. 그보다는 나아야 한다.
    assert lstm["precision"] > 0.3, lstm
    assert lstm["recall"] > 0.2, lstm


def test_false_positive_rate_is_measured_on_clean_windows(stationary_result):
    result, _ = stationary_result
    assert 0.0 <= result["lstm"]["false_positive_rate"] <= 1.0
    assert result["lstm"]["tn"] > 0


def test_all_three_baselines_are_reported(stationary_result):
    """§7.2 — LSTM 을 단독으로 내놓지 않는다."""
    result, _ = stationary_result
    assert set(result["baselines"]) == {"zscore", "rolling", "pca"}
    for metrics in result["baselines"].values():
        assert "f1" in metrics and "threshold" in metrics


def test_status_reflects_baseline_comparison(stationary_result):
    result, _ = stationary_result
    beat = result["beats_baseline"]
    assert (result["status"] == STATUS_READY) == (
        beat and result["split"]["purge_gap_s"] > 0
        and result["status"] != "REJECTED_GENERALIZATION_FAILURE"
    ) or result["status"].startswith("REJECTED")


def test_purge_gap_was_applied(stationary_result):
    result, _ = stationary_result
    assert result["split"]["purge_gap_s"] > 0
    assert result["split"]["purged_windows"] > 0


# ---------------- artifact ----------------

def test_all_required_artifacts_are_written(stationary_result):
    """§8 이 요구하는 파일 일습."""
    _, art = stationary_result
    for name in ("model.pt", "scaler.json", "threshold.json", "feature_manifest.json",
                 "metrics.json", "training_manifest.json", "data_quality_report.txt"):
        assert (art / name).exists(), f"{name} 이 없다"


def test_training_manifest_has_required_fields(stationary_result):
    _, art = stationary_result
    manifest = json.loads((art / "training_manifest.json").read_text(encoding="utf-8"))
    for key in ("model_version", "git_commit", "random_seed", "nodes_used",
                "features_used", "features_rejected", "data_start_at", "data_end_at",
                "split", "resample_interval_s", "window_length", "missing_data_rules",
                "scaler_kind", "architecture", "hyperparameters", "threshold_method",
                "live_simulation_split"):
        assert key in manifest, f"training_manifest 에 {key} 가 없다"
    assert manifest["is_research_only"] is True


def test_feature_manifest_matches_scaler_feature_order(stationary_result):
    """추론 시 이 둘이 어긋나면 값이 엉뚱한 채널의 통계로 정규화된다."""
    _, art = stationary_result
    features = json.loads((art / "feature_manifest.json").read_text(encoding="utf-8"))["features"]
    scaler = json.loads((art / "scaler.json").read_text(encoding="utf-8"))["features"]
    assert features == scaler


def test_scaler_artifact_carries_per_node_stats(stationary_result):
    _, art = stationary_result
    scaler = json.loads((art / "scaler.json").read_text(encoding="utf-8"))
    assert scaler["kind"] == "standard_per_node"
    assert len(scaler["per_node"]) >= 2


def test_threshold_came_from_validation_only(stationary_result):
    _, art = stationary_result
    threshold = json.loads((art / "threshold.json").read_text(encoding="utf-8"))
    assert threshold["n_validation_windows"] > 0
    assert threshold["threshold_quantile"] == 0.99


def test_drifting_data_produces_no_performance_numbers(drifting_tap, tmp_path):
    """§0.10 — 검증되지 않은 결과를 성능처럼 내놓지 않는다."""
    result = run([drifting_tap], tmp_path / "art", _config(tmp_path))
    assert result["status"] == STATUS_BLOCKED
    assert "lstm" not in result
    assert "baselines" not in result
