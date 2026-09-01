"""노출량 적산 산수 검증 (FR-701, 11_EXPOSURE_DOSE_SPEC.md §4).

EXP-7 의 합격 기준(해석적 계산값 대비 오차 <= 2%)을 DB 없이 여기서 먼저 건다.

pytest 를 import 하지 않는다. 이 저장소에는 아직 pytest 도 venv 도 없어서, 러너
없이 `python` 으로 직접 호출해 돌릴 수 있어야 실제로 검증이 된다. pytest 가 들어오면
그대로 수집된다 — 평범한 assert 만 쓴다.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.exposure_accumulator import (  # noqa: E402
    DoseState,
    alert_level_for_fraction,
    dose_fraction,
    integrate,
    integrate_o2,
    max_alert_level,
    nearest_node,
    o2_alert_level,
    sensor_nodes_from_anchors,
    stel_exceeded,
    trust_level,
    twa_8h_ppm,
    twa_15min_ppm,
)

T0 = datetime(2026, 8, 21, 1, 0, 0, tzinfo=timezone.utc)
GAP_MAX = 60.0


def _feed(values_and_offsets, *, gap_max_s: float = GAP_MAX) -> DoseState:
    state = DoseState()
    for value, offset_s in values_and_offsets:
        state = integrate(state, value, T0 + timedelta(seconds=offset_s), gap_max_s=gap_max_s)
    return state


# ============================================================
# §4.1 사다리꼴 적분 — 해석적 계산값과 맞아야 한다
# ============================================================

def test_constant_concentration_matches_analytic_dose():
    """1000ppm 을 60분 유지하면 60,000 ppm·min (EXP-7 합격 기준 ±2%)."""
    samples = [(1000.0, i * 5) for i in range(0, 60 * 12 + 1)]  # 5초 간격 60분
    state = _feed(samples)
    expected = 1000.0 * 60.0
    assert abs(state.dose_ppm_min - expected) / expected <= 0.02, (
        f"dose={state.dose_ppm_min}, expected≈{expected}"
    )


def test_demo_dose_scale_changes_only_accumulated_dose_not_peak():
    state = integrate(DoseState(), 4.0, T0, gap_max_s=GAP_MAX, dose_scale=6000.0)
    state = integrate(
        state, 4.0, T0 + timedelta(seconds=15),
        gap_max_s=GAP_MAX, dose_scale=6000.0,
    )
    assert state.dose_ppm_min == 6000.0
    assert state.peak_ppm == 4.0
    assert state.accumulated_s == 15.0


def test_linear_ramp_is_exact():
    """사다리꼴 적분은 선형 구간에 대해 오차가 없다.

    0 → 1200ppm 로 60분간 선형 상승하면 평균 600ppm, dose = 36,000 ppm·min.
    여기서 오차가 나면 구현이 사다리꼴이 아니라 좌/우 리만합이라는 뜻이다.
    """
    minutes = 60
    samples = [(1200.0 * (m / minutes), m * 60) for m in range(minutes + 1)]
    state = _feed(samples)
    assert abs(state.dose_ppm_min - 36000.0) < 1e-6, state.dose_ppm_min


def test_sampling_interval_does_not_change_result():
    """고정 tick 이 아니라 이벤트 구동이므로 샘플 간격이 결과를 바꾸면 안 된다."""
    dense = _feed([(800.0, i * 2) for i in range(0, 30 * 30 + 1)])      # 2초 간격
    sparse = _feed([(800.0, i * 30) for i in range(0, 2 * 30 + 1)])     # 30초 간격
    assert abs(dense.dose_ppm_min - sparse.dose_ppm_min) < 1e-6


def test_first_sample_does_not_accumulate():
    """윈도우의 첫 샘플은 적분할 구간이 없다. 좌변만 세운다."""
    state = integrate(DoseState(), 5000.0, T0, gap_max_s=GAP_MAX)
    assert state.dose_ppm_min == 0.0
    assert state.last_value == 5000.0
    assert state.accumulated_s == 0.0


# ============================================================
# §4.2 측정 공백 — 과소평가도 폭주도 막는다
# ============================================================

def test_gap_beyond_max_is_not_accumulated():
    """5분 끊기면 gap_max_s(60초)만 적산하고 나머지는 data_gap_s 로 간다.

    마지막 값을 무한 유지하면 하루 끊겼을 때 dose 가 천문학적으로 뛴다.
    """
    state = _feed([(1000.0, 0), (1000.0, 300)])
    assert abs(state.dose_ppm_min - 1000.0 * (60.0 / 60.0)) < 1e-9, state.dose_ppm_min
    assert abs(state.data_gap_s - 240.0) < 1e-9, state.data_gap_s
    assert abs(state.accumulated_s - 60.0) < 1e-9


def test_gap_does_not_make_dose_explode():
    """노드 5분 오프라인 구간에서 dose 폭주가 없어야 한다 (EXP-7.2)."""
    state = _feed([(2000.0, 0), (2000.0, 300), (2000.0, 305)])
    # 60초 + 5초만 적산된다. 305초 전체가 적산되면 10,166 ppm·min 이 된다.
    assert state.dose_ppm_min < 2000.0 * (70.0 / 60.0), state.dose_ppm_min
    assert state.data_gap_s > 0


def test_accumulated_plus_gap_equals_elapsed():
    """§2.2 — accumulated_s = elapsed_s - data_gap_s 관계가 유지되어야 한다."""
    state = _feed([(500.0, 0), (500.0, 30), (500.0, 400), (500.0, 430)])
    elapsed = 430.0
    assert abs((state.accumulated_s + state.data_gap_s) - elapsed) < 1e-9


# ============================================================
# §5.2 누적값은 단조 증가한다
# ============================================================

def test_dose_never_decreases():
    """농도가 0 으로 떨어져도 누적량은 줄지 않는다. 몸에 들어간 가스는 사라지지 않는다."""
    state = DoseState()
    previous = 0.0
    for value, offset in [(1500.0, 0), (1500.0, 30), (0.0, 60), (0.0, 120), (900.0, 150)]:
        state = integrate(state, value, T0 + timedelta(seconds=offset), gap_max_s=GAP_MAX)
        assert state.dose_ppm_min >= previous, "누적량이 줄었다"
        previous = state.dose_ppm_min


def test_out_of_order_sample_is_ignored():
    """시각이 거꾸로 온 샘플로 dose 가 줄어들면 안 된다."""
    state = _feed([(1000.0, 0), (1000.0, 60)])
    before = state.dose_ppm_min
    state = integrate(state, 1000.0, T0 + timedelta(seconds=30), gap_max_s=GAP_MAX)
    assert state.dose_ppm_min == before
    # 좌변도 옮기지 않아야 다음 정상 샘플의 Δt 가 오염되지 않는다.
    assert state.last_sample_at == T0 + timedelta(seconds=60)


def test_duplicate_timestamp_does_not_double_count():
    state = _feed([(1000.0, 0), (1000.0, 60), (1000.0, 60)])
    assert abs(state.dose_ppm_min - 1000.0) < 1e-9


# ============================================================
# peak
# ============================================================

def test_peak_tracks_highest_sample():
    state = _feed([(600.0, 0), (2400.0, 30), (800.0, 60)])
    assert state.peak_ppm == 2400.0
    assert state.peak_at == T0 + timedelta(seconds=30)


# ============================================================
# §2.4 O2 — 농도가 아니라 시간을 센다
# ============================================================

def test_o2_deficient_seconds_accumulate():
    state = DoseState()
    for pct, offset in [(20.9, 0), (19.0, 30), (19.0, 60)]:
        state = integrate_o2(state, pct, T0 + timedelta(seconds=offset), gap_max_s=GAP_MAX)
    # 0~30s 평균 19.95 → 결핍 아님. 30~60s 평균 19.0 → 결핍 30초.
    assert abs(state.o2_deficient_s - 30.0) < 1e-9, state.o2_deficient_s
    assert state.o2_severe_s == 0.0
    assert state.o2_min_pct == 19.0


def test_o2_severe_also_counts_as_deficient():
    """심각(<16%)은 결핍(<19.5%)의 부분집합이다.

    배타적으로 세면 §5.4 의 L2(결핍 900초) 판정이 영영 안 걸린다 — 심각 구간에서
    결핍 카운터가 멈춰버리기 때문이다.
    """
    state = DoseState()
    for pct, offset in [(15.0, 0), (15.0, 60)]:
        state = integrate_o2(state, pct, T0 + timedelta(seconds=offset), gap_max_s=GAP_MAX)
    assert abs(state.o2_severe_s - 60.0) < 1e-9
    assert abs(state.o2_deficient_s - 60.0) < 1e-9, "심각 구간이 결핍에서 빠졌다"


def test_o2_enriched_counts_fire_risk():
    state = DoseState()
    for pct, offset in [(24.0, 0), (24.0, 45)]:
        state = integrate_o2(state, pct, T0 + timedelta(seconds=offset), gap_max_s=GAP_MAX)
    assert abs(state.o2_enriched_s - 45.0) < 1e-9
    assert state.o2_deficient_s == 0.0


def test_o2_respects_gap_max():
    state = DoseState()
    for pct, offset in [(18.0, 0), (18.0, 600)]:
        state = integrate_o2(state, pct, T0 + timedelta(seconds=offset), gap_max_s=GAP_MAX)
    assert abs(state.o2_deficient_s - 60.0) < 1e-9, "공백이 결핍 시간으로 둔갑했다"
    assert abs(state.data_gap_s - 540.0) < 1e-9


# ============================================================
# §6.4 MUST — 없는 것과 0 인 것을 구분한다
# ============================================================

def test_dose_fraction_is_none_when_limit_unseeded():
    """기준값 미시드(§3.2)를 0% 로 그리면 안전하다고 오해한다."""
    assert dose_fraction(50000.0, None) is None
    assert dose_fraction(50000.0, 0.0) is None


def test_dose_fraction_can_exceed_one():
    """누적값은 100% 에서 멈추지 않는다."""
    assert abs(dose_fraction(2_760_000.0, 2_400_000.0) - 1.15) < 1e-9


def test_twa_is_none_before_any_elapsed_time():
    assert twa_8h_ppm(0.0, 0.0) is None
    assert abs(twa_8h_ppm(60000.0, 3600.0) - 1000.0) < 1e-9


# ============================================================
# §4.4 신뢰도
# ============================================================

_TRUST = {"max_trust_distance_m": 3.0, "medium_trust_distance_m": 1.5}


def test_wearable_direct_is_always_high():
    assert trust_level(
        data_gap_s=9999.0, elapsed_s=1.0, source="wearable_direct",
        source_distance_m=None, **_TRUST,
    ) == "high"


def test_large_data_gap_drops_to_low():
    assert trust_level(
        data_gap_s=300.0, elapsed_s=1000.0, source="nearest_node",
        source_distance_m=0.5, **_TRUST,
    ) == "low"


def test_far_source_node_drops_trust():
    assert trust_level(
        data_gap_s=0.0, elapsed_s=1000.0, source="nearest_node",
        source_distance_m=2.4, **_TRUST,
    ) == "medium"
    assert trust_level(
        data_gap_s=0.0, elapsed_s=1000.0, source="nearest_node",
        source_distance_m=4.8, **_TRUST,
    ) == "low"


def test_unknown_distance_is_not_high():
    """거리를 모르면 대입 오차를 평가할 수 없다. 모르는 것을 high 로 두지 않는다."""
    assert trust_level(
        data_gap_s=0.0, elapsed_s=1000.0, source="nearest_node",
        source_distance_m=None, **_TRUST,
    ) == "low"


def test_close_source_with_no_gap_is_high():
    assert trust_level(
        data_gap_s=10.0, elapsed_s=1000.0, source="nearest_node",
        source_distance_m=1.1, **_TRUST,
    ) == "high"


# ============================================================
# ADR-008 최근접 노드
# ============================================================

NODES = {
    "sensor-01": (0.0, 0.0),
    "sensor-02": (2.5, 0.0),
    "sensor-03": (2.5, 2.0),
    "sensor-04": (0.0, 2.0),
}


def test_nearest_node_picks_closest():
    node, distance = nearest_node((0.2, 0.1), NODES)
    assert node == "sensor-01"
    assert abs(distance - 0.2236) < 1e-3


def test_nearest_node_is_deterministic_on_ties():
    """정확히 등거리인 지점에서 호출마다 다른 노드가 나오면 안 된다."""
    first = nearest_node((1.25, 1.0), NODES)
    for _ in range(5):
        assert nearest_node((1.25, 1.0), NODES) == first


def test_nearest_node_without_nodes_is_none():
    assert nearest_node((1.0, 1.0), {}) == (None, None)


# ============================================================
# 앵커 → 센서 노드 매핑
# ============================================================

def test_anchor_ids_map_to_sensor_nodes():
    """A<n> → sensor-0<n>. 하드웨어 문서·펌웨어와 교차 확인된 대응이다."""
    anchors = {"A1": (0.0, 0.0), "A2": (2.5, 0.0), "A3": (2.5, 2.0), "A4": (0.0, 2.0)}
    assert sensor_nodes_from_anchors(anchors) == NODES


def test_unrecognised_anchor_id_is_dropped_not_guessed():
    """규칙에 맞지 않는 ID 를 추측해서 매핑하면 엉뚱한 노드의 농도가 귀속된다."""
    mapped = sensor_nodes_from_anchors({"A1": (0.0, 0.0), "GATEWAY": (9.0, 9.0), "A": (1.0, 1.0)})
    assert mapped == {"sensor-01": (0.0, 0.0)}


# ============================================================
# §5.1 / §5.4 등급 판정
# ============================================================

def test_fraction_ladder_matches_spec():
    assert alert_level_for_fraction(0.49) == "normal"
    assert alert_level_for_fraction(0.5) == "level1_caution"
    assert alert_level_for_fraction(0.8) == "level2_warning"
    assert alert_level_for_fraction(1.0) == "level3_critical"
    assert alert_level_for_fraction(3.0) == "level3_critical"


def test_stel_exceeded_is_critical_regardless_of_fraction():
    """15분 단시간 노출은 8시간 누적이 여유로워도 그 자체로 위험하다."""
    assert alert_level_for_fraction(0.05, stel_exceeded=True) == "level3_critical"
    assert alert_level_for_fraction(None, stel_exceeded=True) == "level3_critical"


def test_missing_limit_is_not_folded_into_normal():
    """기준값이 없는 상태를 normal 로 접으면 모르는 것을 안전하다고 말하게 된다."""
    raised = False
    try:
        alert_level_for_fraction(None)
    except ValueError:
        raised = True
    assert raised, "기준값 없음이 조용히 normal 로 접혔다"


def test_o2_time_ladder_matches_spec():
    assert o2_alert_level(o2_deficient_s=299, o2_severe_s=0) == "normal"
    assert o2_alert_level(o2_deficient_s=300, o2_severe_s=0) == "level1_caution"
    assert o2_alert_level(o2_deficient_s=900, o2_severe_s=0) == "level2_warning"
    assert o2_alert_level(o2_deficient_s=0, o2_severe_s=60) == "level3_critical"


def test_o2_severe_wins_over_deficient():
    """심각 1분이 결핍 5분보다 위다. 둘 다 걸리면 높은 쪽."""
    assert o2_alert_level(o2_deficient_s=400, o2_severe_s=60) == "level3_critical"


def test_max_alert_level_picks_higher():
    assert max_alert_level("normal", "level2_warning") == "level2_warning"
    assert max_alert_level("level3_critical", "level1_caution") == "level3_critical"
    assert max_alert_level("normal", "normal") == "normal"


# ============================================================
# §2.1 STEL — 15분 이동 평균
# ============================================================

def test_twa_15min_is_none_before_two_samples():
    assert twa_15min_ppm(DoseState()) is None
    assert twa_15min_ppm(_feed([(100.0, 0)])) is None


def test_twa_15min_averages_the_window():
    state = _feed([(1000.0, i * 30) for i in range(0, 31)])  # 15분간 1000ppm
    assert twa_15min_ppm(state) == pytest.approx(1000.0)


def test_twa_15min_drops_samples_outside_the_window():
    """창을 벗어난 고농도 구간이 계속 평균을 끌어올리면 STEL 이 영영 안 내려간다."""
    early_spike = [(9000.0, i * 30) for i in range(0, 4)]      # 0~90초 고농도
    later_calm = [(100.0, 120 + i * 30) for i in range(0, 60)]  # 이후 30분간 저농도
    state = _feed(early_spike + later_calm)
    twa = twa_15min_ppm(state)
    assert twa == pytest.approx(100.0), f"창 밖 샘플이 남아 있다: {twa}"


def test_stel_not_exceeded_without_a_limit():
    """기준값이 없으면 판정하지 않는다 — 없는 기준으로 '초과 아님'이라 말하지 않는다."""
    state = _feed([(50_000.0, i * 30) for i in range(0, 31)])
    assert stel_exceeded(state, None) is False
    assert stel_exceeded(state, 0.0) is False


def test_stel_exceeded_when_moving_average_passes_limit():
    state = _feed([(40_000.0, i * 30) for i in range(0, 31)])
    assert stel_exceeded(state, 30_000.0) is True
    assert stel_exceeded(state, 50_000.0) is False


def test_o2_integration_does_not_feed_stel_window():
    """O2 는 ppm 이 아니라 시간을 센다. STEL 창에 섞이면 안 된다."""
    state = DoseState()
    for pct, offset in [(18.0, 0), (18.0, 60)]:
        state = integrate_o2(state, pct, T0 + timedelta(seconds=offset), gap_max_s=GAP_MAX)
    assert state.recent == ()
