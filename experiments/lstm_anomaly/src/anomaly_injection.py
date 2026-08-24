"""평가용 이상 주입 (§7).

**held-out test 의 복사본에만** 주입한다. 원본 배열을 절대 제자리에서 고치지 않는다.
학습셋에 이상이 한 번이라도 섞이면 모델이 그것을 정상으로 배우고, 그 뒤의 모든
평가 수치가 무의미해진다. 그래서 이 모듈의 모든 함수는 새 배열을 반환한다.

주입은 정규화 **이전**의 원 단위(ohm, °C, %)에서 한다. 정규화 뒤에 넣으면 magnitude
의 물리적 의미가 사라져 "몇 시그마" 라는 말밖에 못 하게 되고, 실제 센서에서 그만한
변화가 일어날 수 있는지 판단할 수 없다.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

ANOMALY_TYPES = (
    "spike",
    "drift",
    "stuck_at",
    "dropout",
    "noise_burst",
    "multi_feature",
    "cross_feature_break",
)


@dataclass
class InjectionRecord:
    """§7 이 요구하는 metadata. 이 기록만으로 같은 이상을 재현할 수 있어야 한다."""
    window_index: int
    anomaly_type: str
    start_step: int
    end_step: int
    target_features: List[str]
    magnitude: float
    seed: int

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


def _scale_of(window: np.ndarray, channel: int) -> float:
    """그 채널의 자연스러운 변동 폭. 이상 크기의 기준자로 쓴다.

    표준편차가 0 인 채널(그 window 안에서 상수)은 절대값의 1% 를 쓴다. 0 을 쓰면
    magnitude 를 아무리 키워도 아무 일이 일어나지 않아 '주입했는데 탐지 못 함' 이
    아니라 '주입 자체가 안 됨' 이 된다.
    """
    std = float(np.std(window[:, channel]))
    if std > 1e-9:
        return std
    return max(abs(float(np.mean(window[:, channel]))) * 0.01, 1e-6)


def _apply_spike(w, obs, ch, start, end, mag, rng):
    for c in ch:
        w[start:end, c] += mag * _scale_of(w, c) * rng.choice([-1.0, 1.0])
    return w, obs


def _apply_drift(w, obs, ch, start, end, mag, rng):
    ramp = np.linspace(0.0, 1.0, end - start)
    direction = rng.choice([-1.0, 1.0])
    for c in ch:
        w[start:end, c] += direction * mag * _scale_of(w, c) * ramp
    return w, obs


def _apply_stuck_at(w, obs, ch, start, end, mag, rng):
    # 마지막 정상값을 붙잡는다. 실제 stuck-at 고장의 거동 그대로다.
    for c in ch:
        w[start:end, c] = w[start, c]
    return w, obs


def _apply_dropout(w, obs, ch, start, end, mag, rng):
    # 값이 아니라 관측 마스크를 끈다. 실제 결측과 같은 표현이어야
    # 모델 입력 경로가 평가에서만 달라지는 일이 없다.
    for c in ch:
        obs[start:end, c] = False
        w[start:end, c] = 0.0
    return w, obs


def _apply_noise_burst(w, obs, ch, start, end, mag, rng):
    for c in ch:
        w[start:end, c] += rng.normal(0.0, mag * _scale_of(w, c), end - start)
    return w, obs


def _apply_multi_feature(w, obs, ch, start, end, mag, rng):
    # 여러 채널이 같은 방향으로 함께 움직인다.
    direction = rng.choice([-1.0, 1.0])
    for c in ch:
        w[start:end, c] += direction * mag * _scale_of(w, c)
    return w, obs


def _apply_cross_feature_break(w, obs, ch, start, end, mag, rng):
    """평소 같이 움직이던 채널들이 **반대로** 간다.

    다른 유형과 달리 각 채널의 값 범위는 정상 범위 안에 머문다. 단변량 z-score 는
    이것을 못 잡고 다변량 모델만 잡는다 — LSTM autoencoder 를 쓸 이유가 있다면
    바로 이 유형에서 증명돼야 한다.
    """
    for i, c in enumerate(ch):
        sign = 1.0 if i % 2 == 0 else -1.0
        w[start:end, c] += sign * mag * _scale_of(w, c)
    return w, obs


_APPLIERS = {
    "spike": _apply_spike,
    "drift": _apply_drift,
    "stuck_at": _apply_stuck_at,
    "dropout": _apply_dropout,
    "noise_burst": _apply_noise_burst,
    "multi_feature": _apply_multi_feature,
    "cross_feature_break": _apply_cross_feature_break,
}

# 유형별 기본 지속 비율(window 길이 대비)과 크기(채널 표준편차 배수).
_PROFILE = {
    "spike":               dict(span=(0.03, 0.10), mag=(4.0, 8.0), n_ch=(1, 1)),
    "drift":               dict(span=(0.50, 1.00), mag=(3.0, 6.0), n_ch=(1, 2)),
    "stuck_at":            dict(span=(0.30, 0.70), mag=(1.0, 1.0), n_ch=(1, 2)),
    "dropout":             dict(span=(0.10, 0.30), mag=(1.0, 1.0), n_ch=(1, 2)),
    "noise_burst":         dict(span=(0.20, 0.50), mag=(3.0, 6.0), n_ch=(1, 2)),
    "multi_feature":       dict(span=(0.20, 0.60), mag=(2.5, 5.0), n_ch=(2, 3)),
    "cross_feature_break": dict(span=(0.30, 0.70), mag=(2.0, 4.0), n_ch=(2, 3)),
}


def inject(
    values: np.ndarray,
    observed: np.ndarray,
    features: Sequence[str],
    *,
    seed: int,
    contamination_ratio: float = 0.3,
    types: Optional[Sequence[str]] = None,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, List[InjectionRecord]]:
    """window 묶음의 일부에 이상을 주입한다.

    반환: (값, 관측마스크, window 라벨[N] bool, 주입기록)

    입력 배열은 건드리지 않는다 — 호출자가 넘긴 test 원본이 오염되면 정상 구간
    오경보율(§7.1)을 잴 기준 자체가 사라진다.
    """
    types = list(types or ANOMALY_TYPES)
    unknown = set(types) - set(ANOMALY_TYPES)
    if unknown:
        raise ValueError(f"알 수 없는 이상 유형: {sorted(unknown)}")

    values = np.array(values, copy=True)
    observed = np.array(observed, copy=True)
    n_windows, n_steps, n_features = values.shape
    labels = np.zeros(n_windows, dtype=bool)
    records: List[InjectionRecord] = []

    if n_windows == 0:
        return values, observed, labels, records

    rng = np.random.default_rng(seed)
    n_target = int(round(n_windows * contamination_ratio))
    if n_target == 0:
        return values, observed, labels, records

    chosen = rng.choice(n_windows, size=min(n_target, n_windows), replace=False)
    # 유형을 고르게 배분한다. 무작위로 뽑으면 표본이 작을 때 어떤 유형은 0건이 되어
    # 유형별 recall(§7.1)을 낼 수 없다.
    assigned = np.resize(np.array(types, dtype=object), len(chosen))
    rng.shuffle(assigned)

    for window_index, anomaly_type in zip(chosen, assigned):
        profile = _PROFILE[anomaly_type]
        span_lo, span_hi = profile["span"]
        span = int(round(n_steps * rng.uniform(span_lo, span_hi)))
        span = max(2, min(span, n_steps))
        start = int(rng.integers(0, n_steps - span + 1))
        end = start + span

        ch_lo, ch_hi = profile["n_ch"]
        n_ch = int(rng.integers(ch_lo, min(ch_hi, n_features) + 1))
        channels = rng.choice(n_features, size=min(n_ch, n_features), replace=False)

        mag_lo, mag_hi = profile["mag"]
        magnitude = float(rng.uniform(mag_lo, mag_hi))

        window = values[window_index]
        mask = observed[window_index]
        window, mask = _APPLIERS[anomaly_type](
            window, mask, list(channels), start, end, magnitude, rng
        )
        values[window_index] = window
        observed[window_index] = mask
        labels[window_index] = True
        records.append(InjectionRecord(
            window_index=int(window_index),
            anomaly_type=str(anomaly_type),
            start_step=start,
            end_step=end,
            target_features=[features[c] for c in channels],
            magnitude=magnitude,
            seed=seed,
        ))

    return values, observed, labels, records
