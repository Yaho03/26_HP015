"""정상 실측 데이터 진단 (§3).

이 모듈이 하는 유일한 판단은 **"이 데이터로 학습해도 되는가"** 이다.
feature 를 고르는 것도 여기서 한다 — 코드에 6 을 박아두지 않고, 실제 유효성을
확인한 결과가 그대로 feature manifest 가 된다 (§2.2 마지막 규칙).

배제는 조용히 하지 않는다. 어떤 feature 를 왜 뺐는지 전부 이유와 개수로 남긴다.
"모델이 잘 나오게" 데이터를 깎는 것과 "센서가 죽어서" 빼는 것은 다른 일이고,
후자만 정당하다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

STATUS_DATA_READY = "DATA_READY"
STATUS_DATA_PARTIAL = "DATA_PARTIAL"
STATUS_DATA_UNAVAILABLE = "DATA_UNAVAILABLE"

# 유효 feature 가 이 수보다 적으면 다변량 모델을 만들 이유가 없다.
# 1채널이면 그것은 autoencoder 가 아니라 단변량 이상탐지이고, z-score 로 충분하다.
MIN_FEATURES = 2


@dataclass
class FeatureVerdict:
    """feature 하나에 대한 판정. rejected 면 reason 이 반드시 있다."""
    metric: str
    accepted: bool
    reason: str
    n_rows: int
    n_nodes: int
    null_ratio: float
    cv_pct: Optional[float]
    longest_constant_run: int
    # 이 feature 가 죽어 있는 노드. feature 는 살리되 해당 노드 구간만 빼는 판단에 쓴다.
    dead_nodes: List[str] = field(default_factory=list)


# BME680 IAQ 는 BSEC 정확도가 2 이상일 때만 유효하다
# (08_SAFETY_AND_LIMITATIONS §2.1, 06_ALERT_RULES §4.4). 통계로 판별할 수 없는
# 도메인 규칙이라 별도로 확인한다 — 값이 아무리 잘 변해도 accuracy 가 낮으면
# 그 변동은 공기질이 아니라 BSEC 의 내부 보정 과정이다.
IAQ_METRIC = "iaq_index"
IAQ_ACCURACY_METRIC = "iaq_accuracy"
IAQ_MIN_ACCURACY = 2


@dataclass
class QualityReport:
    status: str
    nodes: List[str]
    features_valid: List[str]
    features_rejected: List[FeatureVerdict]
    start_at: Optional[pd.Timestamp]
    end_at: Optional[pd.Timestamp]
    sampling_interval_median_s: Dict[str, float]
    valid_ratio_by_feature: Dict[str, float]
    longest_gap_by_feature_s: Dict[str, float]
    constant_runs: Dict[str, int]
    live_simulation_split: Dict[str, int]
    duplicate_timestamps: int
    notes: List[str] = field(default_factory=list)
    # feature -> 노드 최대 드리프트 비율(추세 크기 / window 내 변동). 1 을 크게 넘으면
    # 기준선이 관측 기간 동안 이동했다는 뜻이라 정상 패턴 학습의 전제가 깨진다.
    drift_ratio_by_feature: Dict[str, float] = field(default_factory=dict)
    is_stationary: bool = True

    def render(self) -> str:
        """§3 이 요구하는 고정 형식. 사람이 읽고 그대로 보고서에 붙일 수 있어야 한다."""
        def fmt_map(m: Dict[str, float], suffix: str = "") -> str:
            if not m:
                return "    (없음)"
            return "\n".join(f"    {k}: {v:.4g}{suffix}" for k, v in sorted(m.items()))

        rejected = "\n".join(
            f"    {v.metric}: {v.reason}" for v in self.features_rejected
        ) or "    (없음)"

        return "\n".join([
            f"STATUS: {self.status}",
            f"NODES: {', '.join(self.nodes) or '(없음)'}",
            f"FEATURES_VALID: {', '.join(self.features_valid) or '(없음)'}",
            "FEATURES_REJECTED:",
            rejected,
            f"START_AT: {self.start_at}",
            f"END_AT: {self.end_at}",
            "SAMPLING_INTERVAL_MEDIAN:",
            fmt_map(self.sampling_interval_median_s, "s"),
            "VALID_RATIO_BY_FEATURE:",
            fmt_map(self.valid_ratio_by_feature),
            "LONGEST_GAP_BY_FEATURE:",
            fmt_map(self.longest_gap_by_feature_s, "s"),
            "CONSTANT_RUNS:",
            fmt_map({k: float(v) for k, v in self.constant_runs.items()}),
            f"STATIONARY: {self.is_stationary}",
            "DRIFT_RATIO_BY_FEATURE (추세/window변동, 1 초과 시 기준선 이동):",
            fmt_map(self.drift_ratio_by_feature, "x"),
            f"LIVE_SIMULATION_SPLIT: {self.live_simulation_split}",
            f"DUPLICATE_TIMESTAMPS: {self.duplicate_timestamps}",
            "NOTES:",
            "\n".join(f"    - {n}" for n in self.notes) or "    (없음)",
        ])


def _longest_constant_run(values: np.ndarray) -> int:
    """같은 값이 연속으로 이어진 최대 길이.

    stuck-at 고장의 지문이다. sensor-04 의 gas_resistance_ohm 이 6,521 샘플 내내
    176.6 이었던 것을 이 지표가 잡는다.
    """
    if values.size == 0:
        return 0
    changed = np.flatnonzero(np.diff(values) != 0)
    boundaries = np.concatenate(([-1], changed, [values.size - 1]))
    return int(np.diff(boundaries).max())


def _median_interval_s(times: pd.Series) -> float:
    if len(times) < 2:
        return float("nan")
    deltas = times.sort_values().diff().dropna().dt.total_seconds()
    positive = deltas[deltas > 0]
    return float(positive.median()) if not positive.empty else float("nan")


def _longest_gap_s(times: pd.Series) -> float:
    if len(times) < 2:
        return float("nan")
    return float(times.sort_values().diff().dropna().dt.total_seconds().max())


def _drop_redundant(
    df: pd.DataFrame,
    accepted: List[str],
    nodes: List[str],
    *,
    redundancy_r: float,
) -> "tuple[List[str], List[FeatureVerdict]]":
    """서로 결정론적 변환 관계인 feature 를 하나만 남긴다.

    MQ 센서는 raw_adc -> voltage_v -> rs_ohm 이 고정 수식으로 이어진다. 셋 다 넣으면
    같은 물리량을 3번 세게 되고, anomaly_score 의 feature 평균이 MQ 쪽으로 구조적으로
    기울어 온습도 이상을 덮어버린다. 채널 수만 늘고 정보는 늘지 않는다.

    상관계수로 판별하는 이유: 이름 규칙(*_raw_adc 등)으로 자르면 다음에 다른
    펌웨어 필드가 들어왔을 때 조용히 새어 들어온다. |r| 이 1 에 붙는다는 사실
    자체가 중복의 정의다.

    Pearson 과 Spearman 을 함께 보는 이유: 변환이 선형이라는 보장이 없다.
    raw_adc -> voltage_v 는 선형이지만 voltage_v -> rs_ohm 은
    Rs = RL x (Vcc - V) / V 로 **비선형**이다. Pearson 만 보면 이 쌍이 서로 다른
    정보인 것처럼 통과해 같은 MQ 센서가 두 채널을 차지한다. 단조 변환이면
    Spearman 이 정확히 1 이 되므로 이쪽이 잡는다.

    남길 대표는 accepted 순서(알파벳순)가 아니라 **물리적으로 해석 가능한 것**을
    고른다 — rs_ohm 은 센서 저항이라 단위와 의미가 있지만 raw_adc 는 ADC 눈금이다.
    """
    if len(accepted) < 2:
        return accepted, []

    wide = (
        df[df["metric"].isin(accepted)]
        .pivot_table(index=["node_id", "time"], columns="metric", values="value", aggfunc="last")
        .sort_index()
    )
    # 대표 선호도. 낮을수록 먼저 남긴다.
    def preference(metric: str) -> tuple:
        for rank, suffix in enumerate(("_rs_ohm", "_pct", "_c", "_ohm", "_voltage_v", "_raw_adc")):
            if metric.endswith(suffix):
                return (rank, metric)
        return (0, metric)

    ordered = sorted(accepted, key=preference)
    kept: List[str] = []
    dropped: List[FeatureVerdict] = []

    for metric in ordered:
        duplicate_of = None
        for keeper in kept:
            pair = wide[[metric, keeper]].dropna()
            if len(pair) < 10:
                continue
            if pair[metric].std() == 0 or pair[keeper].std() == 0:
                continue
            linear = abs(float(pair[metric].corr(pair[keeper])))
            monotonic = abs(float(pair[metric].corr(pair[keeper], method="spearman")))
            r = max(linear, monotonic)
            if r >= redundancy_r:
                duplicate_of = (keeper, r)
                break
        if duplicate_of is None:
            kept.append(metric)
        else:
            keeper, r = duplicate_of
            dropped.append(FeatureVerdict(
                metric=metric, accepted=False,
                reason=f"{keeper} 와 |r|={r:.5f} — 결정론적 변환 관계라 정보가 중복된다",
                n_rows=int(df["metric"].eq(metric).sum()), n_nodes=len(nodes),
                null_ratio=0.0, cv_pct=None, longest_constant_run=0,
            ))

    return sorted(kept), dropped


def _drift_ratio(values: np.ndarray, window: int) -> float:
    """구간 전체의 추세 크기를 window 내부 변동으로 나눈 값.

    이 비율이 1 을 크게 넘으면 "정상" 의 기준선 자체가 관측 기간 동안 이동했다는
    뜻이다. 그런 데이터로 과거를 학습해 미래를 판정하면, 모델이 보는 것은 이상이
    아니라 자기가 배운 기준선이 낡았다는 사실뿐이다.

    LSTM autoencoder 는 정상 패턴이 **반복되는 것**을 전제한다. 기준선이 단조롭게
    흐르면 반복할 패턴이 없다. 이 지표가 그 전제가 깨졌는지를 판별한다.

    MQ 계열은 예열에만 수 시간이 걸리고 BME680 은 24시간 안정화가 필요하다
    (08_SAFETY_AND_LIMITATIONS §5.1). 짧은 기록은 통째로 워밍업 과도구간일 수 있고,
    §0.6 은 워밍업 값을 정상 패턴으로 학습하지 말라고 못박는다.
    """
    if values.size < window * 3:
        return float("nan")
    quarter = max(1, values.size // 5)
    trend = float(np.mean(values[-quarter:]) - np.mean(values[:quarter]))
    local = pd.Series(values).rolling(window).std().median()
    if not np.isfinite(local) or local < 1e-12:
        return float("nan")
    return abs(trend) / float(local)


def _iaq_accuracy_is_usable(df: pd.DataFrame) -> bool:
    """iaq_index 를 쓸 수 있는지는 값이 아니라 동반 지표 iaq_accuracy 가 정한다."""
    accuracy = df.loc[df["metric"] == IAQ_ACCURACY_METRIC, "value"]
    if accuracy.empty:
        return False
    return bool(accuracy.max() >= IAQ_MIN_ACCURACY)


def diagnose(
    df: pd.DataFrame,
    *,
    candidate_features: Optional[Sequence[str]] = None,
    require_all_nodes: bool = True,
    dead_run_ratio: float = 0.2,
    min_cv_pct: float = 0.1,
    min_valid_ratio: float = 0.5,
    redundancy_r: float = 0.999,
    max_drift_ratio: float = 3.0,
    drift_window_s: float = 600.0,
) -> QualityReport:
    """long-format 프레임을 진단하고 학습 가능 여부와 유효 feature 를 판정한다.

    dead_run_ratio: 한 노드에서 최장 동일값 연속이 그 노드 표본의 이 비율을 넘으면
        그 (노드, feature) 를 죽은 것으로 본다. **절대 샘플 수가 아니라 비율**인
        이유는, 1초 주기에서 240샘플(4분) 고정은 일시적 정체지만 6,521샘플(전 구간)
        고정은 센서 사망이기 때문이다. 둘을 같은 잣대로 자르면 sensor-04 의 죽은
        BME680 하나 때문에 멀쩡한 나머지 3노드의 gas_resistance_ohm 까지 버리게 된다.
        비율에 못 미치는 짧은 고정 구간은 feature 를 버리지 않고 전처리에서
        관측되지 않은 것으로 마스킹한다 (§0.6, §3).
    min_cv_pct: 변동계수가 이보다 작으면 사실상 상수라 복원 오차에 기여하지 못한다.
    min_valid_ratio: 노드별 관측 비율이 이보다 낮은 feature 는 쓰지 않는다.
    """
    notes: List[str] = []

    if df.empty:
        return QualityReport(
            status=STATUS_DATA_UNAVAILABLE,
            nodes=[], features_valid=[], features_rejected=[],
            start_at=None, end_at=None,
            sampling_interval_median_s={}, valid_ratio_by_feature={},
            longest_gap_by_feature_s={}, constant_runs={},
            live_simulation_split={}, duplicate_timestamps=0,
            notes=["입력 데이터가 비어 있습니다 (실측 live 행 0건)."],
        )

    nodes = sorted(df["node_id"].unique())
    metrics = sorted(df["metric"].unique())
    if candidate_features:
        metrics = [m for m in metrics if m in set(candidate_features)]

    live_split = df["source_mode"].value_counts(dropna=False).to_dict()
    live_split = {("unknown" if pd.isna(k) else str(k)): int(v) for k, v in live_split.items()}

    duplicates = int(
        df.duplicated(subset=["node_id", "metric", "time"], keep="first").sum()
    )
    if duplicates:
        notes.append(
            f"동일 (node, metric, time) 중복 {duplicates}건 — 리샘플링에서 마지막 값을 쓴다."
        )

    valid: List[str] = []
    rejected: List[FeatureVerdict] = []
    interval_median: Dict[str, float] = {}
    valid_ratio: Dict[str, float] = {}
    longest_gap: Dict[str, float] = {}
    constant_runs: Dict[str, int] = {}

    # 노드별 관측 기간. feature 의 "관측 비율" 은 그 노드가 살아 있던 기간을
    # 분모로 삼아야 한다. 나중에 합류한 노드를 결측으로 세면 안 된다.
    node_span = {
        n: (g["time"].min(), g["time"].max()) for n, g in df.groupby("node_id")
    }

    iaq_ok = _iaq_accuracy_is_usable(df)

    for metric in metrics:
        sub = df[df["metric"] == metric]
        present_nodes = sorted(sub["node_id"].unique())

        per_node_ratio: Dict[str, float] = {}
        dead_nodes: List[str] = []
        runs: List[int] = []
        cvs: List[float] = []
        intervals: List[float] = []
        gaps: List[float] = []

        for node in present_nodes:
            node_sub = sub[sub["node_id"] == node].sort_values("time")
            values = node_sub["value"].to_numpy()
            run = _longest_constant_run(values)
            runs.append(run)
            if values.size and run / values.size > dead_run_ratio:
                dead_nodes.append(node)
            mean = float(np.mean(values)) if values.size else 0.0
            if mean:
                cvs.append(100.0 * float(np.std(values)) / abs(mean))
            median_dt = _median_interval_s(node_sub["time"])
            intervals.append(median_dt)
            gaps.append(_longest_gap_s(node_sub["time"]))

            span_start, span_end = node_span[node]
            span_s = (span_end - span_start).total_seconds()
            if span_s > 0 and not np.isnan(median_dt) and median_dt > 0:
                expected = span_s / median_dt
                per_node_ratio[node] = min(1.0, len(node_sub) / expected)
            else:
                per_node_ratio[node] = 1.0 if len(node_sub) else 0.0

        interval_median[metric] = float(np.nanmedian(intervals)) if intervals else float("nan")
        longest_gap[metric] = float(np.nanmax(gaps)) if gaps else float("nan")
        constant_runs[metric] = max(runs) if runs else 0
        ratio = float(np.mean(list(per_node_ratio.values()))) if per_node_ratio else 0.0
        valid_ratio[metric] = ratio
        # 죽은 노드는 평균 CV 를 0 쪽으로 끌어내려 멀쩡한 노드까지 상수로 보이게 한다.
        # 살아 있는 노드만으로 대표 변동성을 잰다.
        live_cvs = [c for node, c in zip(present_nodes, cvs) if node not in dead_nodes]
        cv = float(np.mean(live_cvs)) if live_cvs else (float(np.mean(cvs)) if cvs else None)

        verdict = FeatureVerdict(
            metric=metric, accepted=False, reason="",
            n_rows=len(sub), n_nodes=len(present_nodes),
            null_ratio=1.0 - ratio, cv_pct=cv,
            longest_constant_run=constant_runs[metric],
            dead_nodes=dead_nodes,
        )

        # 판정. 순서가 곧 우선순위다 — 더 근본적인 결격 사유를 먼저 적는다.
        if require_all_nodes and len(present_nodes) < len(nodes):
            missing = sorted(set(nodes) - set(present_nodes))
            verdict.reason = (
                f"전체 {len(nodes)}노드 중 {len(present_nodes)}노드에만 존재 "
                f"(누락: {', '.join(missing)})"
            )
        elif metric == IAQ_METRIC and not iaq_ok:
            verdict.reason = (
                f"iaq_accuracy 가 전 노드에서 {IAQ_MIN_ACCURACY} 미만 — "
                f"BSEC 미보정 구간이라 IAQ 값이 공기질을 뜻하지 않는다 "
                f"(08_SAFETY §2.1)"
            )
        elif dead_nodes and len(dead_nodes) == len(present_nodes):
            verdict.reason = (
                f"전 노드에서 stuck-at (최장 동일값 {constant_runs[metric]}샘플, "
                f"표본의 {dead_run_ratio:.0%} 초과)"
            )
        elif require_all_nodes and dead_nodes:
            verdict.reason = (
                f"{', '.join(dead_nodes)} 에서 stuck-at "
                f"(최장 동일값 {constant_runs[metric]}샘플) — 4노드 공통 채널로 쓸 수 없다"
            )
        elif ratio < min_valid_ratio:
            verdict.reason = f"관측 비율 {ratio:.1%} < 기준 {min_valid_ratio:.0%}"
        elif cv is not None and cv < min_cv_pct:
            verdict.reason = f"변동계수 {cv:.3f}% < 기준 {min_cv_pct}% (사실상 상수)"
        else:
            verdict.accepted = True
            verdict.reason = "유효"

        if verdict.accepted:
            valid.append(metric)
        else:
            rejected.append(verdict)

    valid, redundant = _drop_redundant(df, valid, nodes, redundancy_r=redundancy_r)
    rejected.extend(redundant)

    # 정상성 검사. feature 를 버리지 않고 리포트에만 남긴다 — 드리프트는 채널의
    # 결격이 아니라 **관측 기간이 짧다**는 사실의 증상이고, 판단은 학습 단계가 한다.
    drift_by_feature: Dict[str, float] = {}
    for metric in valid:
        sub = df[df["metric"] == metric]
        ratios = []
        for node in sorted(sub["node_id"].unique()):
            series = sub[sub["node_id"] == node].sort_values("time")["value"].to_numpy()
            median_dt = interval_median.get(metric, 1.0) or 1.0
            steps_per_window = max(10, int(drift_window_s / median_dt))
            ratio = _drift_ratio(series, steps_per_window)
            if np.isfinite(ratio):
                ratios.append(ratio)
        if ratios:
            drift_by_feature[metric] = float(max(ratios))

    worst_drift = max(drift_by_feature.values(), default=0.0)
    is_stationary = worst_drift <= max_drift_ratio
    if not is_stationary:
        offenders = sorted(
            (m for m, r in drift_by_feature.items() if r > max_drift_ratio),
            key=lambda m: -drift_by_feature[m],
        )
        notes.append(
            f"기준선 이동이 지배적이다 — 최대 드리프트 {worst_drift:.1f}x "
            f"(기준 {max_drift_ratio}x, 해당 feature: {', '.join(offenders)}). "
            f"관측 기간 내내 정상값 자체가 흘렀다는 뜻이라 '반복되는 정상 패턴' 이 없다. "
            f"MQ 는 예열에만 수 시간, BME680 은 24시간 안정화가 필요하다 "
            f"(08_SAFETY §5.1) — 짧은 기록은 통째로 워밍업 과도구간일 수 있고 "
            f"§0.6 은 워밍업 값을 정상으로 학습하지 말라고 규정한다."
        )

    if len(valid) >= MIN_FEATURES and len(nodes) >= 2:
        status = STATUS_DATA_READY
    elif valid:
        status = STATUS_DATA_PARTIAL
    else:
        status = STATUS_DATA_UNAVAILABLE

    if len(valid) < MIN_FEATURES:
        notes.append(
            f"유효 feature 가 {len(valid)}개로 최소 {MIN_FEATURES}개 미만이다. "
            f"다변량 autoencoder 를 만들 근거가 없다."
        )

    span_h = (df["time"].max() - df["time"].min()).total_seconds() / 3600
    if span_h < 24:
        notes.append(
            f"관측 구간이 {span_h:.1f}시간이다. 프로토타입 검증용이며 "
            f"현장 일반화의 증거가 아니다 (§4.3)."
        )

    unknown = live_split.get("unknown", 0)
    if unknown:
        notes.append(
            f"source_mode 불명 {unknown}건은 학습에서 제외됐다 (live 로 승격하지 않음)."
        )

    return QualityReport(
        status=status,
        nodes=nodes,
        features_valid=valid,
        features_rejected=rejected,
        start_at=df["time"].min(),
        end_at=df["time"].max(),
        sampling_interval_median_s=interval_median,
        valid_ratio_by_feature=valid_ratio,
        longest_gap_by_feature_s=longest_gap,
        constant_runs=constant_runs,
        live_simulation_split=live_split,
        duplicate_timestamps=duplicates,
        notes=notes,
        drift_ratio_by_feature=drift_by_feature,
        is_stationary=is_stationary,
    )
