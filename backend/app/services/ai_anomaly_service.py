"""AI 이상징후 실시간 탐지 (연구용, §9).

**안전 분리 — 이 파일이 지키는 규칙 (§9.4)**
  - alert_service / alert_publisher / 웨어러블 진동 publisher 를 호출하지 않는다.
  - AI 상태를 AlertLevel 로 변환하지 않는다. 변환 함수 자체를 두지 않는다.
  - 결과는 alert_events 가 아니라 ai_anomaly_results 에 쓴다.
  - 이 서비스의 예외는 ingest 콜백으로 전파되지 않는다 — ingest 를 아예 건드리지 않고
    독립 주기 태스크로 DB 를 읽는다. ingest 콜백에 붙이면 AI 예외가 센서 수집과
    경보 판정을 막을 수 있다.

**판단하지 않은 것을 정상이라 말하지 않는다 (§0.9, §9.2)**
  데이터가 모자라거나, 오래됐거나, feature 가 어긋나면 그렇게 보고한다.
  밀폐공간에서 센서가 죽었는데 화면이 "정상" 으로 남는 것은 미검출보다 위험하다.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

from app.config import settings
from app.observability import metrics
from app.repositories import ai_anomaly_repository
from app.services import ai_anomaly_model as engine
from app.services.ai_anomaly_model import ModelArtifact

logger = logging.getLogger(__name__)

# §9.2 응답 상태. 앞의 넷은 "판단하지 않았다" 이고 normal_pattern 으로 바뀌지 않는다.
STATUS_MODEL_NOT_READY = "model_not_ready"
STATUS_INSUFFICIENT_DATA = "insufficient_data"
STATUS_STALE_DATA = "stale_data"
STATUS_FEATURE_MISMATCH = "feature_mismatch"
STATUS_NORMAL = "normal_pattern"
STATUS_CANDIDATE = "anomaly_candidate"
STATUS_ANOMALY = "anomaly"

UNDECIDED = frozenset({
    STATUS_MODEL_NOT_READY, STATUS_INSUFFICIENT_DATA,
    STATUS_STALE_DATA, STATUS_FEATURE_MISMATCH,
})

EVAL_INTERVAL_S = 10
STALE_AFTER_S = 30
MIN_OBSERVED_RATIO = 0.7
CONSECUTIVE_TO_ANOMALY = 3
CONSECUTIVE_TO_NORMAL = 3

_artifact: Optional[ModelArtifact] = None
_task: Optional[asyncio.Task] = None
_broadcast = None
# node_id -> {"status": str, "exceedances": int, "recoveries": int}
_state: Dict[str, Dict] = {}


def set_broadcast(callback) -> None:
    """WebSocket 브로드캐스트 콜백 주입. main.py 가 ws_manager 를 넘긴다."""
    global _broadcast
    _broadcast = callback


def artifact() -> Optional[ModelArtifact]:
    return _artifact


def init() -> None:
    """서버 시작 시 artifact 를 읽는다.

    실패해도 예외를 밖으로 던지지 않는다 (§0.8). 모델이 없다고 센서 수집과 안전
    경보가 멈추면, 연구용 기능 하나 때문에 안전 시스템 전체를 내리는 셈이다.
    대신 model_not_ready 로 남고 그 사실이 화면에 그대로 표시된다.
    """
    global _artifact
    _artifact = None
    directory = Path(settings.ai_anomaly_artifact_dir)
    if not directory.is_dir():
        logger.info("AI 이상탐지 artifact 없음 (%s) — model_not_ready 로 시작", directory)
        return
    try:
        _artifact = engine.load_artifact(directory)
        logger.info(
            "AI 이상탐지 artifact 로드: version=%s features=%s threshold=%.4f",
            _artifact.model_version, _artifact.features, _artifact.threshold,
        )
    except Exception:
        logger.exception("AI 이상탐지 artifact 로드 실패 — model_not_ready 로 계속한다")
        _artifact = None


async def start() -> None:
    global _task
    if not settings.ai_anomaly_enabled:
        logger.info("AI 이상탐지 비활성 (AI_ANOMALY_ENABLED=false)")
        return
    _task = asyncio.create_task(_loop())


async def stop() -> None:
    global _task
    if _task is None:
        return
    _task.cancel()
    try:
        await _task
    except asyncio.CancelledError:
        pass
    _task = None


async def _loop() -> None:
    while True:
        try:
            await asyncio.sleep(EVAL_INTERVAL_S)
            await evaluate_all()
        except asyncio.CancelledError:
            raise
        except Exception:
            # 루프가 죽으면 조용히 영원히 멈춘다. 세어서 /api/metrics 로 드러낸다.
            metrics.increment("ai_anomaly_loop_failures")
            logger.exception("AI 이상탐지 주기 평가 실패")


async def _nodes_to_evaluate() -> List[str]:
    if _artifact is not None and _artifact.scaler_per_node:
        return sorted(_artifact.scaler_per_node)
    return await ai_anomaly_repository.recent_node_ids()


async def evaluate_all() -> List[dict]:
    results = []
    for node_id in await _nodes_to_evaluate():
        result = await evaluate_node(node_id)
        if result is not None:
            results.append(result)
    return results


def _empty_result(node_id: str, status: str, now: datetime) -> dict:
    return {
        "type": "ai_anomaly",
        "node_id": node_id,
        "evaluated_at": now.isoformat(),
        "status": status,
        "score": None,
        "threshold": _artifact.threshold if _artifact else None,
        "consecutive_exceedances": 0,
        "top_contributors": [],
        "model_version": _artifact.model_version if _artifact else None,
        "is_research_only": True,
        "source_mode": None,
    }


async def evaluate_node(node_id: str) -> Optional[dict]:
    """한 노드의 최근 10분을 판정한다.

    무거운 계산은 별도 스레드로 보낸다 — FastAPI event loop 에서 60스텝 LSTM 을
    직접 돌리면 그 동안 MQTT 수신과 WebSocket 브로드캐스트가 멈춘다 (§9.1).
    """
    now = datetime.now(timezone.utc)

    if _artifact is None:
        return await _finish(_empty_result(node_id, STATUS_MODEL_NOT_READY, now))

    span_s = _artifact.sequence_length * _artifact.resample_interval_s
    rows = await ai_anomaly_repository.recent_window(
        node_id=node_id,
        features=_artifact.features,
        start=now - timedelta(seconds=span_s),
        end=now,
    )

    if not rows:
        return await _finish(_empty_result(node_id, STATUS_INSUFFICIENT_DATA, now))

    latest = max(row["time"] for row in rows)
    if (now - latest).total_seconds() > STALE_AFTER_S:
        # stale 을 normal 로 바꾸지 않는다 (§9.2). 센서가 멈춘 것과 정상인 것은 다르다.
        return await _finish(_empty_result(node_id, STATUS_STALE_DATA, now))

    present = {row["metric"] for row in rows}
    missing = [f for f in _artifact.features if f not in present]
    if missing:
        result = _empty_result(node_id, STATUS_FEATURE_MISMATCH, now)
        result["missing_features"] = missing
        return await _finish(result)

    values, observed, source_mode = _build_window(rows, now)
    if observed.mean() < MIN_OBSERVED_RATIO:
        return await _finish(_empty_result(node_id, STATUS_INSUFFICIENT_DATA, now))

    scored = await asyncio.to_thread(_score_window, node_id, values, observed)
    if scored is None:
        return await _finish(_empty_result(node_id, STATUS_INSUFFICIENT_DATA, now))

    score, contributors = scored
    status, exceedances = _advance_state(node_id, score)

    result = _empty_result(node_id, status, now)
    result.update({
        "score": round(float(score), 4),
        "consecutive_exceedances": exceedances,
        "top_contributors": contributors,
        "source_mode": source_mode,
    })
    return await _finish(result)


def _build_window(rows: List[dict], now: datetime):
    """long-format 행을 [1, T, F] 값·마스크로 편다. 학습 때와 같은 리샘플링 규칙."""
    assert _artifact is not None
    steps = _artifact.sequence_length
    interval = _artifact.resample_interval_s
    n_features = _artifact.n_features

    values = np.zeros((steps, n_features), dtype="float32")
    observed = np.zeros((steps, n_features), dtype=bool)
    index = {name: i for i, name in enumerate(_artifact.features)}
    origin = now - timedelta(seconds=steps * interval)

    buckets: Dict[tuple, List[float]] = {}
    source_modes = set()
    for row in rows:
        column = index.get(row["metric"])
        if column is None:
            continue
        offset = int((row["time"] - origin).total_seconds() // interval)
        if 0 <= offset < steps:
            buckets.setdefault((offset, column), []).append(float(row["value"]))
        if row.get("source_mode"):
            source_modes.add(row["source_mode"])

    for (step, column), samples in buckets.items():
        values[step, column] = float(np.mean(samples))
        observed[step, column] = True

    # 짧은 공백만 채운다. 값은 직전 관측을 잇고 마스크는 False 로 남겨 loss/점수에서 빠진다.
    limit = max(1, 20 // interval)
    for column in range(n_features):
        last_seen = -1
        for step in range(steps):
            if observed[step, column]:
                if 0 <= last_seen and step - last_seen <= limit + 1:
                    start_v, end_v = values[last_seen, column], values[step, column]
                    for gap in range(last_seen + 1, step):
                        ratio = (gap - last_seen) / (step - last_seen)
                        values[gap, column] = start_v + (end_v - start_v) * ratio
                last_seen = step

    mode = "simulation" if "simulation" in source_modes else (
        "live" if "live" in source_modes else None
    )
    return values[None, :, :], observed[None, :, :], mode


def _score_window(node_id: str, values: np.ndarray, observed: np.ndarray):
    """스레드에서 실행. 학습 때와 동일한 노드별 scaler 를 쓴다."""
    assert _artifact is not None
    mean, std = _artifact.scaler_for(node_id)
    scaled = (values - mean) / std
    scaled = np.where(observed, scaled, 0.0).astype("float32")

    prediction = engine.reconstruct(_artifact, scaled)
    errors = engine.feature_errors(_artifact, prediction, scaled, observed)
    score = engine.anomaly_score(errors)[0]
    if np.isnan(score):
        return None
    return float(score), engine.top_contributors(_artifact, errors[0])


def _advance_state(node_id: str, score: float):
    """3회 연속 지속 조건 (§6.2). 기존 경보의 enter_for_ms 와는 무관한 별개 상태다."""
    assert _artifact is not None
    state = _state.setdefault(
        node_id, {"status": STATUS_NORMAL, "exceedances": 0, "recoveries": 0}
    )
    if score > _artifact.threshold:
        state["exceedances"] += 1
        state["recoveries"] = 0
        if state["exceedances"] >= CONSECUTIVE_TO_ANOMALY:
            state["status"] = STATUS_ANOMALY
        elif state["status"] != STATUS_ANOMALY:
            state["status"] = STATUS_CANDIDATE
    else:
        state["recoveries"] += 1
        state["exceedances"] = 0
        if state["recoveries"] >= CONSECUTIVE_TO_NORMAL:
            state["status"] = STATUS_NORMAL
    return state["status"], state["exceedances"]


async def _finish(result: dict) -> dict:
    """저장 + 브로드캐스트. 어느 쪽이 실패해도 다른 쪽과 다음 주기를 막지 않는다."""
    try:
        await ai_anomaly_repository.insert(result)
    except Exception:
        metrics.increment("ai_anomaly_store_failures")
        logger.exception("AI 이상탐지 결과 저장 실패 (node=%s)", result["node_id"])

    if _broadcast is not None:
        try:
            await _broadcast(result)
        except Exception:
            metrics.increment("ai_anomaly_broadcast_failures")
            logger.exception("AI 이상탐지 브로드캐스트 실패 (node=%s)", result["node_id"])
    return result


def reset_state() -> None:
    """테스트용. 지속 조건 카운터를 비운다."""
    _state.clear()
