"""로더 -> 진단 -> 전처리 -> window -> 분할 을 한 줄로 잇는다.

train.py 와 테스트가 같은 경로를 타게 하려고 분리했다. 학습 스크립트 안에만
있으면 "실제로 학습에 들어간 데이터" 를 테스트가 확인할 방법이 없다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Union

import numpy as np
import pandas as pd

from src.data_loader import load_sources, to_wide
from src.data_quality import QualityReport, diagnose
from src.preprocessing import ExclusionLog, Scaler, resample_node
from src.windowing import WindowSet, concat, make_windows, time_split


@dataclass
class PreparedData:
    report: QualityReport
    features: List[str]
    train: WindowSet
    val: WindowSet
    test: WindowSet
    scaler: Scaler
    split_meta: Dict[str, object]
    exclusions: List[ExclusionLog] = field(default_factory=list)
    node_windows: Dict[str, int] = field(default_factory=dict)


def prepare(
    sources: Sequence[Union[str, Path]],
    config: dict,
    *,
    features_override: Optional[Sequence[str]] = None,
) -> PreparedData:
    """설정과 입력 경로만 받아 학습 가능한 배열까지 만든다."""
    pre = config["preprocessing"]
    win = config["windowing"]
    interval_s = int(pre["resample_interval_s"])
    seq_len = int(win["sequence_length"])

    df = load_sources(sources, require_source_mode=config["data"]["require_source_mode"])
    report = diagnose(df)

    # feature 는 진단 결과를 쓴다. 설정에 명시가 있으면 그것을 쓰되, 진단이
    # 유효하다고 하지 않은 채널은 넣지 않는다 — 죽은 센서를 설정으로 되살릴 수는 없다.
    requested = list(features_override or config.get("features", {}).get("use") or [])
    if requested:
        features = [f for f in requested if f in report.features_valid]
        dropped = sorted(set(requested) - set(features))
        if dropped:
            report.notes.append(
                f"설정에 있었으나 진단에서 유효하지 않아 제외한 feature: {', '.join(dropped)}"
            )
    else:
        features = list(report.features_valid)

    if not features:
        empty = WindowSet(
            values=np.zeros((0, seq_len, 0), dtype="float32"),
            observed=np.zeros((0, seq_len, 0), dtype=bool),
            node_ids=np.array([], dtype=object),
            start_times=np.array([], dtype="datetime64[ns]"),
            features=[],
        )
        return PreparedData(report, [], empty, empty, empty, Scaler([]), {}, [], {})

    exclusions: List[ExclusionLog] = []
    per_node: List[WindowSet] = []
    node_windows: Dict[str, int] = {}

    for node_id in report.nodes:
        wide = to_wide(df, node_id, features)
        if wide.empty:
            continue
        wide.attrs["node_id"] = node_id
        values, observed, logs = resample_node(
            wide,
            interval_s=interval_s,
            max_interpolate_gap_s=int(pre["max_interpolate_gap_s"]),
            constant_run_reject_s=int(pre["constant_run_reject_s"]),
        )
        exclusions.extend(logs)
        windows = make_windows(
            values.to_numpy(), observed.to_numpy(), values.index, node_id, features,
            sequence_length=seq_len,
            stride=int(win["stride"]),
            interval_s=interval_s,
            max_gap_s=int(pre["max_window_gap_s"]),
            min_observed_ratio=float(pre["min_observed_ratio"]),
        )
        node_windows[node_id] = len(windows)
        per_node.append(windows)

    all_windows = concat(per_node, features, seq_len)
    split = win["split"]
    train, val, test, meta = time_split(
        all_windows,
        train=float(split["train"]), val=float(split["val"]), test=float(split["test"]),
        purge_gap_steps=int(win["purge_gap_steps"]), interval_s=interval_s,
    )

    # scaler 는 train 에서만 fit 한다 (§4.1). val/test 통계가 스케일에 들어가면
    # 모델은 평가 구간의 분포를 이미 알고 시작하게 된다.
    # 노드별로 fit 하는 이유는 preprocessing.Scaler docstring 참조 — 이 하드웨어에서는
    # 노드 간 baseline 차이가 노드 내 시간 변동을 압도한다.
    scaler = Scaler(features)
    if len(train):
        n_steps = train.values.shape[1]
        flat = train.values.reshape(-1, len(features))
        flat_mask = train.observed.reshape(-1, len(features))
        flat_nodes = np.repeat(train.node_ids, n_steps)
        scaler.fit(flat, flat_mask, flat_nodes)
        report.notes.append(
            f"scaler: 노드별 표준화 (train 구간, {len(scaler.per_node_)}개 노드). "
            f"노드 간 offset 이 노드 내 변동을 압도해 global scaler 로는 "
            f"정상 변동이 0.05σ 까지 눌린다."
        )
    else:
        report.notes.append("train window 가 0개라 scaler 를 fit 하지 못했다.")

    return PreparedData(
        report=report, features=features, train=train, val=val, test=test,
        scaler=scaler, split_meta=meta, exclusions=exclusions, node_windows=node_windows,
    )


def scaled(
    windows: WindowSet,
    scaler: Scaler,
    values: Optional[np.ndarray] = None,
    observed: Optional[np.ndarray] = None,
) -> np.ndarray:
    """window 값을 학습용 스케일로 변환. 미관측 위치는 0 으로 둔다.

    0 으로 두는 것이 안전한 이유: masked loss 가 그 위치를 세지 않으므로 값이
    무엇이든 gradient 에 기여하지 않는다. 다만 인코더 입력으로는 들어가므로
    극단값이 아닌 중앙값(정규화 후 0)이어야 한다.

    values/observed 를 따로 받는 것은 이상이 주입된 배열을 **원본 window 의
    node_ids 그대로** 변환하기 위해서다. 노드별 scaler 라 어느 노드의 통계를
    쓸지가 결과를 바꾸므로, 주입본이라고 다른 스케일을 타면 안 된다.
    """
    values = windows.values if values is None else values
    observed = windows.observed if observed is None else observed
    if values.shape[0] == 0:
        return values.astype("float32")

    n_features = values.shape[-1]
    n_steps = values.shape[1]
    flat_nodes = np.repeat(windows.node_ids, n_steps)
    out = scaler.transform(values.reshape(-1, n_features), flat_nodes)
    out = out.reshape(values.shape).astype("float32")
    return np.where(observed, out, 0.0).astype("float32")
