"""AI 이상징후 서비스 — 안전 분리와 fail-safe 계약 (§9.2, §9.4, §12).

이 파일의 절반은 "무엇을 하지 않는가" 를 고정한다. AI 기능이 안전 경보 경로로
새어드는 것을 막는 것이 이 기능의 가장 중요한 요구사항이기 때문이다.
"""
from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from app.services import ai_anomaly_service as svc
from app.services.ai_anomaly_model import ModelArtifact

ARTIFACT_DIR = Path(__file__).resolve().parents[2] / "experiments/lstm_anomaly/artifacts/demo"
FEATURES = ["humidity_pct", "mq136_rs_ohm", "mq2_rs_ohm", "mq7_rs_ohm", "temperature_c"]


# ---------------- 안전 분리 (§9.4) ----------------

def _executable_source(module) -> str:
    """주석과 docstring 을 걷어낸 실행 코드만 남긴다.

    검사 대상은 "코드가 안전 경보를 호출하는가" 이지 "설명에 그 낱말이 나오는가" 가
    아니다. 왜 호출하면 안 되는지를 적은 주석까지 걸리면, 통과시키려고 그 설명을
    지우게 된다 — 규칙을 지키려다 규칙의 근거를 잃는다.
    """
    import ast

    tree = ast.parse(inspect.getsource(module))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = node.body
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                node.body = body[1:] or [ast.Pass()]
    return ast.unparse(ast.fix_missing_locations(tree))


def test_service_never_calls_alert_modules():
    """AI 가 안전 경보를 건드릴 수 있는 통로 자체를 만들지 않는다."""
    source = _executable_source(svc)
    for forbidden in ("alert_service", "alert_publisher", "alert_engine",
                      "AlertLevel", "level1_caution", "level2_warning", "level3_critical"):
        assert forbidden not in source, f"{forbidden} 가 AI 서비스 코드에 등장한다"


def test_repository_never_touches_alert_events():
    from app.repositories import ai_anomaly_repository
    assert "alert_events" not in _executable_source(ai_anomaly_repository)


def test_ai_statuses_are_disjoint_from_alert_levels():
    ai = {svc.STATUS_NORMAL, svc.STATUS_CANDIDATE, svc.STATUS_ANOMALY,
          svc.STATUS_MODEL_NOT_READY, svc.STATUS_INSUFFICIENT_DATA,
          svc.STATUS_STALE_DATA, svc.STATUS_FEATURE_MISMATCH}
    alert = {"normal", "level1_caution", "level2_warning", "level3_critical"}
    assert ai & alert == set()


def test_undecided_statuses_never_include_normal_pattern():
    """§9.2 — insufficient_data / stale_data 를 정상으로 바꾸지 않는다."""
    assert svc.STATUS_NORMAL not in svc.UNDECIDED
    assert svc.STATUS_ANOMALY not in svc.UNDECIDED
    assert svc.STATUS_STALE_DATA in svc.UNDECIDED


def test_ingest_does_not_call_ai_service():
    """AI 예외가 센서 수집 경로로 전파될 수 없다 (§9.4)."""
    from app.services import ingest
    assert "ai_anomaly" not in _executable_source(ingest)


# ---------------- fail-safe (§9.1, §9.2, §12) ----------------

@pytest.fixture(autouse=True)
def clean_state():
    svc.reset_state()
    yield
    svc.reset_state()
    svc._artifact = None
    svc._broadcast = None


def test_missing_artifact_dir_does_not_raise(monkeypatch, tmp_path):
    """모델 파일이 없어도 서버 기동이 유지되어야 한다 (§12 백엔드 1번)."""
    monkeypatch.setattr(svc.settings, "ai_anomaly_artifact_dir", str(tmp_path / "nope"))
    svc.init()
    assert svc.artifact() is None


def test_corrupt_artifact_does_not_raise(monkeypatch, tmp_path):
    (tmp_path / "feature_manifest.json").write_text("{ not json", encoding="utf-8")
    monkeypatch.setattr(svc.settings, "ai_anomaly_artifact_dir", str(tmp_path))
    svc.init()
    assert svc.artifact() is None


@pytest.mark.asyncio
async def test_no_model_reports_model_not_ready(monkeypatch):
    captured = {}

    async def fake_insert(result):
        captured["stored"] = result

    monkeypatch.setattr(svc.ai_anomaly_repository, "insert", fake_insert)
    svc._artifact = None
    result = await svc.evaluate_node("sensor-01")
    assert result["status"] == svc.STATUS_MODEL_NOT_READY
    assert result["score"] is None, "판단하지 않았는데 점수를 내면 안 된다"
    assert result["is_research_only"] is True
    assert captured["stored"]["status"] == svc.STATUS_MODEL_NOT_READY


# ---------------- 지속 조건 (§6.2) ----------------

def _fake_artifact(threshold: float = 1.0) -> ModelArtifact:
    return ModelArtifact(
        features=list(FEATURES), sequence_length=60, resample_interval_s=10,
        model_version="test", threshold=threshold, weights={},
        scaler_global=(np.zeros(5, dtype="float32"), np.ones(5, dtype="float32")),
        scaler_per_node={},
    )


def test_three_consecutive_exceedances_required(monkeypatch):
    svc._artifact = _fake_artifact(1.0)
    assert svc._advance_state("sensor-01", 5.0)[0] == svc.STATUS_CANDIDATE
    assert svc._advance_state("sensor-01", 5.0)[0] == svc.STATUS_CANDIDATE
    assert svc._advance_state("sensor-01", 5.0)[0] == svc.STATUS_ANOMALY


def test_three_consecutive_recoveries_required(monkeypatch):
    svc._artifact = _fake_artifact(1.0)
    for _ in range(3):
        svc._advance_state("sensor-01", 5.0)
    svc._advance_state("sensor-01", 0.1)
    svc._advance_state("sensor-01", 0.1)
    assert svc._state["sensor-01"]["status"] == svc.STATUS_ANOMALY
    assert svc._advance_state("sensor-01", 0.1)[0] == svc.STATUS_NORMAL


def test_node_states_are_independent(monkeypatch):
    """한 노드의 이상이 다른 노드 상태를 바꾸면 안 된다."""
    svc._artifact = _fake_artifact(1.0)
    for _ in range(3):
        svc._advance_state("sensor-01", 5.0)
    assert svc._advance_state("sensor-02", 0.1)[0] == svc.STATUS_NORMAL
    assert svc._state["sensor-01"]["status"] == svc.STATUS_ANOMALY


# ---------------- 실제 artifact 로 추론 ----------------

@pytest.mark.skipif(not ARTIFACT_DIR.is_dir(), reason="학습 artifact 없음")
def test_real_artifact_loads_and_scores():
    from app.services.ai_anomaly_model import (
        anomaly_score, feature_errors, load_artifact, reconstruct, top_contributors,
    )
    artifact = load_artifact(ARTIFACT_DIR)
    assert artifact.n_features == len(artifact.features)

    rng = np.random.default_rng(0)
    x = rng.normal(0, 1, (2, artifact.sequence_length, artifact.n_features)).astype("float32")
    mask = np.ones_like(x, dtype=bool)
    prediction = reconstruct(artifact, x)
    assert prediction.shape == x.shape, "입출력 shape 이 같아야 한다"

    errors = feature_errors(artifact, prediction, x, mask)
    assert errors.shape == (2, artifact.n_features)
    scores = anomaly_score(errors)
    assert np.isfinite(scores).all()
    top = top_contributors(artifact, errors[0])
    assert top and top[0]["error"] >= top[-1]["error"]
    assert all(t["metric"] in artifact.features for t in top)


@pytest.mark.skipif(not ARTIFACT_DIR.is_dir(), reason="학습 artifact 없음")
def test_fully_unobserved_channel_scores_nan_not_zero():
    """꺼진 센서가 '완벽히 정상' 이 되면 안 된다."""
    from app.services.ai_anomaly_model import feature_errors, load_artifact, reconstruct
    artifact = load_artifact(ARTIFACT_DIR)
    x = np.zeros((1, artifact.sequence_length, artifact.n_features), dtype="float32")
    mask = np.ones_like(x, dtype=bool)
    mask[:, :, 0] = False
    errors = feature_errors(artifact, reconstruct(artifact, x), x, mask)
    assert np.isnan(errors[0, 0])
    assert not np.isnan(errors[0, 1])


@pytest.mark.skipif(not ARTIFACT_DIR.is_dir(), reason="학습 artifact 없음")
def test_scaler_and_manifest_feature_order_match():
    from app.services.ai_anomaly_model import load_artifact
    artifact = load_artifact(ARTIFACT_DIR)
    assert artifact.features == FEATURES


# ---------------- window 구성 ----------------

def _rows(now, metrics_, *, step_s=10, n=60, value=1.0, mode="live"):
    out = []
    for i in range(n):
        t = now - timedelta(seconds=(n - i) * step_s)
        for m in metrics_:
            out.append({"time": t, "metric": m, "value": value, "source_mode": mode})
    return out


def test_window_marks_missing_channel_unobserved():
    svc._artifact = _fake_artifact()
    now = datetime.now(timezone.utc)
    rows = _rows(now, FEATURES[:4])          # 마지막 채널이 통째로 빠졌다
    values, observed, mode = svc._build_window(rows, now)
    assert values.shape == (1, 60, 5)
    assert not observed[0, :, 4].any()
    assert observed[0, :, 0].any()
    assert mode == "live"


def test_window_reports_simulation_source_mode():
    svc._artifact = _fake_artifact()
    now = datetime.now(timezone.utc)
    _, _, mode = svc._build_window(_rows(now, FEATURES, mode="simulation"), now)
    assert mode == "simulation"
