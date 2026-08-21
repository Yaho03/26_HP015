"""누적 노출량 적산 — 순수 로직 (FR-701, docs/11_EXPOSURE_DOSE_SPEC.md §4).

DB 도 시계도 네트워크도 건드리지 않는다. 상태를 받아 새 상태를 돌려주는 함수만 있다.

**이 분리는 편의가 아니라 검증 때문이다.** 여기 있는 산수가 틀리면 8시간 일한
작업자의 노출량이 틀리게 나오고, 화면은 그것을 근거 있는 숫자처럼 보여준다. DB 나
MQTT 없이 이 파일만 단독으로 돌려볼 수 있어야 그 산수를 실제로 검증할 수 있다.
(현재 이 저장소에는 pytest 도 venv 도 없어서, 러너 없이 돌려볼 수 있다는 성질이
실제로 유일한 검증 수단이다.)
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Literal, Optional

# O2 농도 구간 경계 (%).
#
# 이 값들은 "조절 가능한 경보 임계값"이 아니라 **컬럼의 정의**다. exposure_state 의
# o2_deficient_s / o2_severe_s / o2_enriched_s 가 각각 이 경계 아래·위에 머문 시간을
# 뜻하므로, 값을 바꾸면 이미 쌓인 컬럼의 의미가 소급해서 달라진다. 근거는
# 산업안전보건기준에 관한 규칙의 적정공기 정의이고 06_ALERT_RULES.md §4.2 에 이미
# 반영돼 있다 (11_EXPOSURE_DOSE_SPEC.md §2.4, §3.2 각주).
#
# 순간값 O2 경보의 임계값은 이것과 별개이며 그쪽은 thresholds 테이블에서 온다.
O2_DEFICIENT_PCT = 19.5
O2_SEVERE_PCT = 16.0
O2_ENRICHED_PCT = 23.5

ExposureSource = Literal["wearable_direct", "nearest_node", "unavailable"]
TrustLevel = Literal["high", "medium", "low"]


@dataclass(frozen=True)
class DoseState:
    """한 (작업자, 노드, 지표) 윈도우의 적산 상태.

    frozen 인 이유는 적산이 제자리 수정이 아니라 치환이어야 하기 때문이다. 중간에
    예외가 나면 옛 상태가 그대로 남아야지, 반쯤 갱신된 상태로 flush 되면 안 된다.
    """

    dose_ppm_min: float = 0.0
    dose_worst_case_ppm_min: float = 0.0
    #: 샘플이 없어 적산하지 못한 시간. 이만큼 dose 는 **과소평가**되어 있다.
    data_gap_s: float = 0.0
    #: 실제로 적산에 반영된 시간. elapsed_s 와의 차이가 data_gap_s 다.
    accumulated_s: float = 0.0
    last_value: Optional[float] = None
    last_sample_at: Optional[datetime] = None
    peak_ppm: Optional[float] = None
    peak_at: Optional[datetime] = None
    o2_deficient_s: float = 0.0
    o2_severe_s: float = 0.0
    o2_enriched_s: float = 0.0
    o2_min_pct: Optional[float] = None


def integrate(
    state: DoseState,
    value: float,
    sampled_at: datetime,
    *,
    gap_max_s: float,
    worst_case_value: Optional[float] = None,
) -> DoseState:
    """샘플 하나를 적산한다 (§4.1 사다리꼴 적분).

        Δt     = min(sampled_at - last_sample_at, gap_max_s)
        C_avg  = (C_prev + C_now) / 2
        dose  += C_avg × (Δt / 60)        # ppm·min

    고정 주기 tick 이 아니라 **샘플 도착 이벤트 구동**이다. 센서가 1초마다 오든
    5초마다 오든 같은 결과가 나와야 하고, 그건 Δt 를 실제 간격에서 계산해야만 된다.

    측정 공백 처리 (§4.2) — 두 선택지가 모두 위험하다.

      * 공백을 0 으로 간주 → 노출량 **과소평가**. 안전 시스템에서 최악이다
      * 마지막 값을 무한 유지 → 하루 끊기면 dose 가 천문학적으로 뛴다

    그래서 마지막 값을 유지하되 **최대 gap_max_s 까지만** 적산하고, 초과분은
    data_gap_s 에 쌓는다. 화면은 그 값을 보고 "실제 노출은 표시값보다 크다"고 말한다.

    :param worst_case_value: 전 노드 최댓값. 표시 전용이며 **경보 판정에 쓰지
        않는다** (ADR-008). 주지 않으면 value 로 같이 적산한다.
    """
    if state.last_sample_at is None or state.last_value is None:
        # 윈도우의 첫 샘플. 적분할 구간이 아직 없다 — 좌변만 세워 둔다.
        return replace(
            state,
            last_value=value,
            last_sample_at=sampled_at,
            peak_ppm=value,
            peak_at=sampled_at,
        )

    delta_s = (sampled_at - state.last_sample_at).total_seconds()
    if delta_s < 0:
        # 시각이 거꾸로 온 샘플. 적산하면 dose 가 줄어드는데 누적값은 단조 증가라야
        # 한다 (§5.2). 무시하되 좌변도 갱신하지 않는다 — 순서가 뒤집힌 채로
        # 좌변을 옮기면 다음 정상 샘플의 Δt 까지 오염된다.
        return state
    if delta_s == 0:
        # 같은 시각의 중복 샘플. 적분 구간이 0 이라 dose 는 그대로지만 peak 는 본다.
        return _with_peak(state, value, sampled_at)

    counted_s = min(delta_s, gap_max_s)
    gap_s = delta_s - counted_s

    average = (state.last_value + value) / 2.0
    dose_delta = average * (counted_s / 60.0)

    worst = value if worst_case_value is None else worst_case_value
    worst_average = (state.last_value + worst) / 2.0
    worst_delta = worst_average * (counted_s / 60.0)

    nxt = replace(
        state,
        dose_ppm_min=state.dose_ppm_min + dose_delta,
        dose_worst_case_ppm_min=state.dose_worst_case_ppm_min + worst_delta,
        accumulated_s=state.accumulated_s + counted_s,
        data_gap_s=state.data_gap_s + gap_s,
        last_value=value,
        last_sample_at=sampled_at,
    )
    return _with_peak(nxt, value, sampled_at)


def _with_peak(state: DoseState, value: float, sampled_at: datetime) -> DoseState:
    """윈도우 내 최고 순간 농도를 갱신한다 (§2.1 peak_ppm / peak_at)."""
    if state.peak_ppm is None or value > state.peak_ppm:
        return replace(state, peak_ppm=value, peak_at=sampled_at)
    return state


def integrate_o2(
    state: DoseState,
    o2_pct: float,
    sampled_at: datetime,
    *,
    gap_max_s: float,
) -> DoseState:
    """O2 결핍 노출 **시간**을 누적한다 (§2.4).

    산소는 몸에 축적되는 물질이 아니다. 그래서 ppm·min 이 아니라 초를 센다.

    구간을 어느 농도로 분류할지는 사양서가 정하지 않았다. 여기서는 §4.1 의 C_avg 와
    같은 방식으로 **두 샘플의 평균**으로 분류한다. 직전 값으로 고정(zero-order hold)
    하면 회복 직전 구간이 통째로 결핍으로 잡히고, 이후 값으로 하면 악화 구간을
    놓친다. 평균은 그 사이를 취한다.
    """
    o2_min = o2_pct if state.o2_min_pct is None else min(state.o2_min_pct, o2_pct)

    if state.last_sample_at is None or state.last_value is None:
        return replace(
            state,
            last_value=o2_pct,
            last_sample_at=sampled_at,
            o2_min_pct=o2_min,
        )

    delta_s = (sampled_at - state.last_sample_at).total_seconds()
    if delta_s < 0:
        return state
    if delta_s == 0:
        return replace(state, o2_min_pct=o2_min)

    counted_s = min(delta_s, gap_max_s)
    gap_s = delta_s - counted_s
    average = (state.last_value + o2_pct) / 2.0

    deficient = state.o2_deficient_s
    severe = state.o2_severe_s
    enriched = state.o2_enriched_s
    if average < O2_SEVERE_PCT:
        # 심각(<16.0%)은 결핍(<19.5%)의 부분집합이다. 둘 다 올린다 — §5.4 가 두
        # 카운터로 서로 다른 등급을 판정하므로 배타적으로 세면 L2 가 영영 안 걸린다.
        severe += counted_s
        deficient += counted_s
    elif average < O2_DEFICIENT_PCT:
        deficient += counted_s
    elif average > O2_ENRICHED_PCT:
        enriched += counted_s

    return replace(
        state,
        accumulated_s=state.accumulated_s + counted_s,
        data_gap_s=state.data_gap_s + gap_s,
        last_value=o2_pct,
        last_sample_at=sampled_at,
        o2_deficient_s=deficient,
        o2_severe_s=severe,
        o2_enriched_s=enriched,
        o2_min_pct=o2_min,
    )


def dose_fraction(dose_ppm_min: float, dose_limit_ppm_min: Optional[float]) -> Optional[float]:
    """기준 대비 소진율. 기준값이 없으면 **0 이 아니라 None** 이다.

    0 을 돌려주면 화면이 "노출 0%"로 그린다. 기준값을 아직 시드하지 않은 상태(§3.2)와
    정말로 노출이 없는 상태는 화면에서 구분되어야 한다 (§6.4 MUST).
    """
    if dose_limit_ppm_min is None or dose_limit_ppm_min <= 0:
        return None
    return dose_ppm_min / dose_limit_ppm_min


def twa_8h_ppm(dose_ppm_min: float, elapsed_s: float) -> Optional[float]:
    """윈도우 시작 이후 시간가중평균 = dose / elapsed_min (§2.1)."""
    if elapsed_s <= 0:
        return None
    return dose_ppm_min / (elapsed_s / 60.0)


def trust_level(
    *,
    data_gap_s: float,
    elapsed_s: float,
    source: ExposureSource,
    source_distance_m: Optional[float],
    unavailable_s: float = 0.0,
    max_trust_distance_m: float,
    medium_trust_distance_m: float,
) -> TrustLevel:
    """dose 를 얼마나 믿을 수 있는가 (§4.4).

        low    : data_gap_s / elapsed_s > 0.2
               | source_distance_m > max_trust_distance_m
               | unavailable 구간이 윈도우의 20% 초과
        medium : source_distance_m > medium_trust_distance_m
        high   : 그 외 (wearable_direct 는 항상 high)

    웨어러블 직접 측정이 항상 high 인 이유는 대입 오차가 없기 때문이다 — 작업자가
    차고 있는 센서의 값이라 "농도 출처가 얼마나 먼가"라는 질문 자체가 성립하지 않는다.
    """
    if source == "wearable_direct":
        return "high"

    if source == "unavailable":
        return "low"

    if elapsed_s > 0:
        if data_gap_s / elapsed_s > 0.2:
            return "low"
        if unavailable_s / elapsed_s > 0.2:
            return "low"

    if source_distance_m is None:
        # 거리를 모르면 대입 오차를 평가할 수 없다. 모르는 것을 high 로 두지 않는다.
        return "low"
    if source_distance_m > max_trust_distance_m:
        return "low"
    if source_distance_m > medium_trust_distance_m:
        return "medium"
    return "high"


def nearest_node(
    position: tuple[float, float],
    nodes: dict[str, tuple[float, float]],
) -> tuple[Optional[str], Optional[float]]:
    """작업자 위치에서 가장 가까운 센서 노드와 그 2D 거리 (ADR-008).

    **IDW 보간값을 쓰지 않는다.** ADR-005 가 추정값의 경보 사용을 금지하므로, 노출량은
    실제로 측정된 노드 값 하나를 대입한다. 그 대입의 오차는 source_distance_m 으로
    드러내고 trust_level 로 등급을 낮춘다 — 감추지 않는다.

    높이는 보지 않는다. 측위가 2D 고정이라(04_DATA_CONTRACT §4.4) z 는 항상 0 이다.
    """
    if not nodes:
        return None, None
    x, y = position
    best_id: Optional[str] = None
    best_d = float("inf")
    for node_id, (nx, ny) in sorted(nodes.items()):
        d = ((nx - x) ** 2 + (ny - y) ** 2) ** 0.5
        if d < best_d:
            best_d = d
            best_id = node_id
    return best_id, best_d


def sensor_nodes_from_anchors(
    anchors: dict[str, tuple[float, float]],
) -> dict[str, tuple[float, float]]:
    """UWB 앵커 좌표를 센서 노드 좌표로 옮긴다.

    센서 노드 4개가 곧 UWB 앵커다 (README 하드웨어 구성). 그래서 좌표를 따로 설정하지
    않고 ``uwb_anchors`` 하나에서 파생한다 — 두 벌로 두면 언젠가 어긋나고, 어긋난
    쪽이 노출량이면 작업자에게 엉뚱한 노드의 농도가 귀속된다.

    ``A<n>`` → ``sensor-0<n>`` 대응은 세 곳에서 교차 확인된다.

      * ``firmware/platformio.ini`` — env ``sensor-01`` 이 ``DWM1000_SHORT_ADDRESS=1``
      * ``dwm1000_ranging_driver.cpp`` — short address 1 → ``"A1"``
      * ``docs/03_HARDWARE_DESIGN.md`` §UWB — ``A1 (sensor-01)``

    규칙에 맞지 않는 앵커 ID 는 **추측해서 매핑하지 않고 버린다.** 잘못 매핑하느니
    출처 없음(exposure_source "unavailable")으로 내려가는 편이 안전하다.
    """
    out: dict[str, tuple[float, float]] = {}
    for anchor_id, position in anchors.items():
        label = anchor_id.strip().upper()
        if len(label) < 2 or label[0] != "A" or not label[1:].isdigit():
            continue
        index = int(label[1:])
        if index < 1:
            continue
        out[f"sensor-{index:02d}"] = position
    return out
