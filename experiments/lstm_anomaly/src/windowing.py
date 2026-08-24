"""Window 생성과 시간 기준 분할 (§4.2, §4.3).

두 가지를 절대 하지 않는다.
1. window 가 노드 경계를 넘지 않는다 — 서로 다른 방의 센서를 이어 붙인 10분은
   어떤 물리 현상도 아니다.
2. window 가 split 경계를 넘지 않는다 — train 의 마지막 9분과 validation 의 첫 1분이
   한 window 에 들어가면, 모델은 이미 본 데이터로 자기를 평가하게 된다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple

import numpy as np
import pandas as pd


@dataclass
class WindowSet:
    """[N, T, F] 배열 묶음. 모든 배열의 첫 축(N)이 같은 window 를 가리킨다."""
    values: np.ndarray            # [N, T, F]
    observed: np.ndarray          # [N, T, F] bool
    node_ids: np.ndarray          # [N]
    start_times: np.ndarray       # [N] datetime64
    features: List[str]

    def __len__(self) -> int:
        return int(self.values.shape[0])

    def subset(self, mask: np.ndarray) -> "WindowSet":
        return WindowSet(
            values=self.values[mask], observed=self.observed[mask],
            node_ids=self.node_ids[mask], start_times=self.start_times[mask],
            features=self.features,
        )


def make_windows(
    values: np.ndarray,
    observed: np.ndarray,
    index: pd.DatetimeIndex,
    node_id: str,
    features: Sequence[str],
    *,
    sequence_length: int,
    stride: int = 1,
    interval_s: int = 10,
    max_gap_s: int = 30,
    min_observed_ratio: float = 0.7,
) -> WindowSet:
    """한 노드의 연속 시계열에서 window 를 잘라낸다.

    두 가지 기준으로 window 를 버린다.
    - 내부에 max_gap_s 이상의 시간 공백이 있다 → 그 10분은 이어진 관측이 아니다
    - 관측 비율이 min_observed_ratio 미만 → 대부분이 보간값인 window 로 학습하면
      모델이 보간 알고리즘을 배운다
    """
    n_steps = len(index)
    features = list(features)
    empty = WindowSet(
        values=np.zeros((0, sequence_length, len(features)), dtype="float32"),
        observed=np.zeros((0, sequence_length, len(features)), dtype=bool),
        node_ids=np.array([], dtype=object),
        start_times=np.array([], dtype="datetime64[ns]"),
        features=features,
    )
    if n_steps < sequence_length:
        return empty

    # 인접 스텝 사이 실제 시간 간격. 리샘플링 후에도 원본이 통째로 빈 구간은
    # 균일 격자 위에서 "값 없음" 으로 남아 있으므로, 관측 마스크로 공백을 본다.
    any_observed = observed.any(axis=1)
    max_gap_steps = max(1, max_gap_s // interval_s)

    starts: List[int] = []
    for start in range(0, n_steps - sequence_length + 1, stride):
        stop = start + sequence_length
        window_observed = any_observed[start:stop]
        if not window_observed.any():
            continue
        # 연속으로 관측이 없는 최장 구간
        gap = best_gap = 0
        for flag in window_observed:
            gap = 0 if flag else gap + 1
            best_gap = max(best_gap, gap)
        if best_gap > max_gap_steps:
            continue
        if observed[start:stop].mean() < min_observed_ratio:
            continue
        starts.append(start)

    if not starts:
        return empty

    idx = np.asarray(starts)
    offsets = np.arange(sequence_length)
    gather = idx[:, None] + offsets[None, :]
    return WindowSet(
        values=values[gather].astype("float32"),
        observed=observed[gather],
        node_ids=np.array([node_id] * len(idx), dtype=object),
        start_times=index.to_numpy()[idx],
        features=features,
    )


def concat(sets: Sequence[WindowSet], features: Sequence[str], sequence_length: int) -> WindowSet:
    sets = [s for s in sets if len(s)]
    if not sets:
        return WindowSet(
            values=np.zeros((0, sequence_length, len(features)), dtype="float32"),
            observed=np.zeros((0, sequence_length, len(features)), dtype=bool),
            node_ids=np.array([], dtype=object),
            start_times=np.array([], dtype="datetime64[ns]"),
            features=list(features),
        )
    return WindowSet(
        values=np.concatenate([s.values for s in sets]),
        observed=np.concatenate([s.observed for s in sets]),
        node_ids=np.concatenate([s.node_ids for s in sets]),
        start_times=np.concatenate([s.start_times for s in sets]),
        features=list(features),
    )


def time_split(
    windows: WindowSet,
    *,
    train: float = 0.70,
    val: float = 0.15,
    test: float = 0.15,
    purge_gap_steps: int = 60,
    interval_s: int = 10,
) -> Tuple[WindowSet, WindowSet, WindowSet, Dict[str, object]]:
    """시간 기준 분할. random shuffle 을 쓰지 않는다 (§4.3).

    purge gap 이 필요한 이유: window 는 stride 1 로 겹쳐서 만들어진다. 경계에서
    자르기만 하면 train 의 마지막 window 와 validation 의 첫 window 가 최대
    sequence_length-1 스텝을 공유한다. 그 공유분이 곧 leakage 다. 경계 양쪽으로
    한 window 길이만큼 비워야 두 집합이 실제로 분리된다.

    노드별로 같은 시각 기준으로 자른다. 노드마다 다른 시각에서 자르면 한 노드의
    미래가 다른 노드의 train 에 들어간다.
    """
    if len(windows) == 0:
        meta = {"reason": "window 가 없어 분할하지 않았다"}
        return windows, windows, windows, meta

    times = pd.to_datetime(windows.start_times, utc=True)
    t_min, t_max = times.min(), times.max()
    span = (t_max - t_min).total_seconds()

    purge_s = purge_gap_steps * interval_s
    # purge 를 두 번(train|val, val|test) 빼고 남는 시간을 비율대로 나눈다.
    usable = span - 2 * purge_s
    notes: List[str] = []
    if usable <= 0:
        notes.append(
            f"전체 구간 {span/3600:.2f}시간이 purge gap 2x{purge_s}s 보다 짧아 "
            f"purge 를 적용하지 못했다. leakage 위험이 남는다."
        )
        purge_s = 0
        usable = span

    total = train + val + test
    train_end = t_min + pd.Timedelta(seconds=usable * (train / total))
    val_start = train_end + pd.Timedelta(seconds=purge_s)
    val_end = val_start + pd.Timedelta(seconds=usable * (val / total))
    test_start = val_end + pd.Timedelta(seconds=purge_s)

    train_mask = times <= train_end
    val_mask = (times >= val_start) & (times <= val_end)
    test_mask = times >= test_start

    dropped = int(len(windows) - (train_mask.sum() + val_mask.sum() + test_mask.sum()))
    meta = {
        "train_end": str(train_end),
        "val_start": str(val_start),
        "val_end": str(val_end),
        "test_start": str(test_start),
        "purge_gap_s": purge_s,
        "purged_windows": dropped,
        "counts": {
            "train": int(train_mask.sum()),
            "val": int(val_mask.sum()),
            "test": int(test_mask.sum()),
        },
        "notes": notes,
    }
    return (
        windows.subset(np.asarray(train_mask)),
        windows.subset(np.asarray(val_mask)),
        windows.subset(np.asarray(test_mask)),
        meta,
    )


def node_split(
    windows: WindowSet, holdout_node: str
) -> Tuple[WindowSet, WindowSet]:
    """노드 일반화 평가용 분할 (§4.3-2). 3노드 학습 / 남은 1노드 테스트."""
    mask = windows.node_ids == holdout_node
    return windows.subset(~mask), windows.subset(mask)
