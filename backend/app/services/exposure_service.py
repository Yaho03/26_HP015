"""작업자 누적 노출량 적산 서비스 (FR-701~708, 11_EXPOSURE_DOSE_SPEC.md §4).

산수는 `exposure_accumulator` 에, 저장은 `exposure_repository` 에 있다. 이 모듈은
그 둘을 배선하고 윈도우의 수명주기를 관리한다.

## 윈도우 수명주기를 배정 훅이 아니라 조정 루프로 만든 이유

§4.3 은 "노출 윈도우는 `worker_assignments` 구간과 일치"라고 한다. 배정 INSERT/UPDATE
시점에 훅을 거는 방법도 있지만, 여기서는 주기적으로 `list_active()` 를 읽어 메모리
상태와 맞추는 **조정(reconcile)** 방식을 쓴다.

  * `worker_repository` 를 건드리지 않는다. 인증·작업자 명부가 이미 쓰는 경로라
    훅을 심으면 그쪽 트랜잭션 안에서 노출량 실패가 배정을 롤백시킬 수 있다.
  * **기동 복구가 같은 코드로 처리된다.** 훅 방식이면 백엔드가 꺼져 있는 동안 일어난
    배정·해제를 따로 따라잡는 경로를 또 만들어야 한다.
  * 윈도우가 열리는 시각이 조금 늦어도 `window_start = assigned_at` 이라 **기록되는
    구간은 정확하다.** dose 는 어차피 첫 샘플부터 쌓이므로 손실도 없다.

## 다운타임이 data_gap 으로 잡히는 경로

백엔드가 멈춘 동안의 공백을 따로 계산하지 않는다. 복구된 윈도우는 `last_sample_at`
이 과거로 남아 있고, 다음 샘플이 오면 Δt 가 `gap_max_s` 를 넘겨 초과분이 그대로
`data_gap_s` 로 간다 (§4.2). 적산기가 이미 하는 일을 서비스가 다시 하지 않는다.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

from app.config import settings
from app.models.alert import AlertLevel, AlertTransition
from app.models.exposure import ExposureShiftLogRow, ExposureStateRow
from app.repositories import exposure_repository as repo
from app.repositories import worker_repository
from app.services import location_service
from app.services.exposure_accumulator import (
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
from app.services.uwb_service import parse_anchors

logger = logging.getLogger(__name__)

#: 노출은 사람에게 귀속되므로 윈도우는 웨어러블 노드에만 열린다 (§5.3).
WEARABLE_PREFIX = "wearable"

#: 센서 노드에서 오는 가스 지표. O2 는 웨어러블 직접 측정이라 따로 다룬다.
GAS_METRICS = ("co2_ppm", "co_ppm", "h2s_ppm")
O2_METRIC = "o2_pct"

#: metric → alert_key (§5.3). metric 과 **다른 문자열**이어야 한다 — 특히 O2 는
#: 순간값 경보(o2_low/o2_high)와 metric 이 같아서, 키를 나누지 않으면 시간 누적
#: 경보와 순간값 경보가 서로를 덮어쓴다 (§5.4 가 금지).
ALERT_KEYS = {
    "co2_ppm": "exposure_co2",
    "co_ppm": "exposure_co",
    "h2s_ppm": "exposure_h2s",
    "o2_pct": "o2_deficiency_time",
}

#: O2 시간 누적 등급별 경계 초 (§5.4). 경보 메시지의 threshold 로 실린다.
_O2_THRESHOLD_S = {
    "level1_caution": 300.0,
    "level2_warning": 900.0,
    "level3_critical": 60.0,   # severe 기준
}

RECONCILE_INTERVAL_S = 15.0

_WindowKey = Tuple[str, str]  # (wearable node_id, metric)


class _Window:
    """활성 윈도우 하나의 런타임 상태.

    `row` 는 DB 정체성(exposure_id, worker_id, window_start)을, `state` 는 적산
    중간값을 들고 있다. 둘을 나눈 이유는 flush 가 state 만 쓰기 때문이다.
    """

    __slots__ = ("row", "state", "worker_name", "source", "source_node_id",
                 "source_distance_m", "unavailable_s", "max_level",
                 "emitted_level", "dirty")

    def __init__(self, row: ExposureStateRow, worker_name: str) -> None:
        self.row = row
        self.worker_name = worker_name
        self.state = DoseState(
            dose_ppm_min=row.dose_ppm_min,
            dose_worst_case_ppm_min=row.dose_worst_case_ppm_min,
            data_gap_s=float(row.data_gap_s),
            last_value=row.last_value,
            last_sample_at=row.last_sample_at,
            peak_ppm=row.peak_ppm,
            peak_at=row.peak_at,
            o2_deficient_s=float(row.o2_deficient_s),
            o2_severe_s=float(row.o2_severe_s),
            o2_enriched_s=float(row.o2_enriched_s),
            o2_min_pct=row.o2_min_pct,
        )
        self.source: str = "unavailable"
        self.source_node_id: Optional[str] = None
        self.source_distance_m: Optional[float] = None
        self.unavailable_s: float = 0.0
        self.max_level: str = "normal"
        #: 지금까지 **발행한** 등급. 여기서 내려가는 일은 없다 (§5.2).
        #: 재시작 후에는 normal 로 시작하는데, 이미 임계를 넘긴 윈도우면 다음 평가에서
        #: 곧바로 같은 등급을 다시 올린다. MQTT state 토픽이 retain 이라 구독자가 보는
        #: 최종 상태는 같다.
        self.emitted_level: str = "normal"
        self.dirty = False

    def elapsed_s(self, now: datetime) -> float:
        return max((now - self.row.window_start).total_seconds(), 0.0)

    def to_row(self) -> ExposureStateRow:
        """flush 용 스냅샷. 적산기의 float 초를 DB 의 정수 초로 내린다."""
        return self.row.model_copy(update={
            "dose_ppm_min": self.state.dose_ppm_min,
            "dose_worst_case_ppm_min": self.state.dose_worst_case_ppm_min,
            "o2_deficient_s": int(self.state.o2_deficient_s),
            "o2_severe_s": int(self.state.o2_severe_s),
            "o2_enriched_s": int(self.state.o2_enriched_s),
            "peak_ppm": self.state.peak_ppm,
            "peak_at": self.state.peak_at,
            "o2_min_pct": self.state.o2_min_pct,
            "last_value": self.state.last_value,
            "last_sample_at": self.state.last_sample_at,
            "data_gap_s": int(self.state.data_gap_s),
        })


_windows: Dict[_WindowKey, _Window] = {}
_limits: dict = {}
_sensor_nodes: Dict[str, Tuple[float, float]] = {}
_task: Optional[asyncio.Task] = None


# ── 초기화 ──────────────────────────────────────────────────────────────

async def init() -> None:
    """서비스 시작. 실패를 삼키지 않는다 (이슈 #154).

    초기화가 조용히 실패하면 센서 데이터는 계속 쌓이는데 적산만 영구히 멈춘 것을
    아무도 모른다. 그 상태로 8시간이 지나면 화면은 "노출 0"을 근거 있는 값처럼
    보여준다.
    """
    global _limits, _sensor_nodes, _task

    _sensor_nodes = sensor_nodes_from_anchors(parse_anchors(settings.uwb_anchors))
    if not _sensor_nodes:
        logger.warning(
            "노출량: 센서 노드 좌표를 얻지 못했다 (uwb_anchors=%r). "
            "최근접 노드를 정할 수 없어 가스 노출량이 산출되지 않는다",
            settings.uwb_anchors,
        )

    _limits = await repo.load_limits()
    missing = [m for m in (*GAS_METRICS,) if m not in _limits]
    if missing:
        # 정상 상태다 (§3.2). 고시 원문 대조 전까지 시드하지 않기로 했고, 화면은
        # 이것을 "0% 노출"이 아니라 "기준값 미검증"으로 그린다.
        logger.info("노출량: 기준값 미시드 metric=%s (limit_unverified 로 내려간다)", missing)

    await _recover()
    await _reconcile()

    from app.services import ingest
    ingest.set_exposure_callback(on_reading)

    if _task is None or _task.done():
        _task = asyncio.create_task(_loop())
    logger.info(
        "노출량 적산 시작 (윈도우 %d개, gap_max=%.0fs, flush=%.0fs)",
        len(_windows), settings.exposure_gap_max_s, settings.exposure_flush_interval_s,
    )


async def reload_limits() -> None:
    """기준값을 다시 읽는다. 관리자가 고친 직후 라우터가 부른다.

    프로세스를 재시작하지 않고 반영되어야 한다 — thresholds 가 alert_service.reload()
    로 하는 것과 같은 이유다 (FR-201).
    """
    global _limits
    _limits = await repo.load_limits()
    logger.info("노출 기준값 재로드 (%d개 시드됨)", len(_limits))


async def stop() -> None:
    """루프를 멈추고 마지막으로 한 번 flush 한다 (§4.5).

    종료 경로라 flush 실패를 전파하지 않는다. 여기서 예외가 나가면 lifespan 의
    나머지 정리(mqtt, DB 연결 해제)가 중단되고, 원래 종료 원인이 이 예외에 가려진다.
    DB 가 이미 내려간 상태로 종료하는 경우가 실제로 있다.
    """
    global _task
    if _task is not None:
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
        _task = None
    try:
        await _flush()
    except Exception:
        logger.exception("노출량 종료 flush 실패 — 마지막 %.0f초 분량이 유실된다",
                         settings.exposure_flush_interval_s)


def status() -> dict:
    """적산 기능 상태 (/health, 이슈 #207).

    evacuation.status() 와 같은 계약 — enabled/reason/provisional. 적산이
    멈춰 있으면 화면은 "노출 0%"가 아니라 "기능 비활성"을 그려야 한다
    (이슈 #154 와 같은 무음 실패 패턴 방지). 전체 status(ok/degraded)에는
    반영하지 않는다 — 노출 적산이 멈춰도 센서 수집·가스 경보는 정상이고
    그쪽이 본체다.
    """
    from pydantic import BaseModel

    class ExposureStatus(BaseModel):
        enabled: bool
        reason: str | None = None
        provisional: bool = False

    if _task is None or _task.done():
        return ExposureStatus(enabled=False, reason="not_started").model_dump()
    if not _sensor_nodes:
        return ExposureStatus(
            enabled=False,
            reason="센서 노드 좌표(uwb_anchors)를 읽지 못해 최근접 노드 판정 불가",
        ).model_dump()
    unverified = [m for m in GAS_METRICS if m not in _limits]
    return ExposureStatus(
        enabled=True,
        provisional=bool(unverified),
        reason=(
            f"기준값 미시드 metric={unverified} — limit_unverified 로 내려간다"
            if unverified
            else None
        ),
    ).model_dump()


async def _recover() -> None:
    """기동 시 열려 있던 윈도우를 메모리로 되살린다 (§4.5).

    **한 노드/지표에 활성 윈도우가 둘 이상일 수 있다.** `uq_exposure_state_active`
    는 worker_id 까지 포함한 키라, 백엔드가 꺼진 사이 웨어러블이 다른 작업자에게
    넘어가면 두 행이 동시에 열려 있게 된다. `_windows` 는 (node_id, metric) 키라
    하나만 들 수 있으므로 **현재 배정된 작업자의 것을 고른다.**

    아무거나 고르면 B 가 착용 중인데 A 의 exposure_id 에 노출이 쌓인다. 누적은
    되돌릴 수 없고, 교대 로그는 A 의 기록으로 확정된다.
    """
    active = {a.node_id: a for a in await worker_repository.list_active()}
    # 정렬은 결정성을 위해서다. DB 반환 순서에 기대면 같은 데이터로 기동할 때마다
    # 다른 윈도우가 선택될 수 있다.
    for row in sorted(await repo.load_active_states(),
                      key=lambda r: (r.window_start, r.exposure_id)):
        key = (row.node_id, row.metric)
        assignment = active.get(row.node_id)
        previous = _windows.get(key)
        if previous is not None:
            keep_previous = (assignment is not None
                             and previous.row.worker_id == assignment.worker_id)
            chosen = previous.row.worker_id if keep_previous else row.worker_id
            logger.warning(
                "노출량: %s/%s 에 활성 윈도우가 둘 이상이다 (worker %s, %s). "
                "worker %s 것을 적산에 쓴다 — 나머지는 DB 에 열린 채 남으므로 "
                "확인이 필요하다",
                row.node_id, row.metric,
                previous.row.worker_id, row.worker_id, chosen,
            )
            if keep_previous:
                continue
        _windows[key] = _Window(row, await _worker_name_for(row.worker_id, assignment))
    if _windows:
        logger.info("노출량: 활성 윈도우 %d개 복구", len(_windows))


async def _worker_name_for(worker_id: int, assignment) -> str:
    """윈도우 주인의 이름. **현재 착용자에서 가져오지 않는다.**

    `exposure_shift_log.worker_name` 은 일부러 비정규화된 컬럼이고 workers FK 도
    없다 — 작업자 행이 지워져도 그 교대에 누가 있었는지가 남아야 하기 때문이다.
    그 자리에 지금 배정된 사람 이름을 넣으면 기록이 사실과 달라진다.

    배정이 이미 다른 사람에게 넘어간 뒤에 복구가 돌 수 있으므로(다운타임 중 교대)
    이름은 윈도우가 가리키는 worker_id 로 조회한다.
    """
    if assignment is not None and assignment.worker_id == worker_id:
        return assignment.name
    worker = await worker_repository.get(worker_id)
    if worker is not None:
        return worker.name
    # 조회 실패를 빈 문자열이나 현재 착용자 이름으로 메우지 않는다. 모른다는 것이
    # 기록에 남아야 나중에 worker_id 로 되짚을 수 있다.
    logger.warning("노출량: worker %s 를 조회하지 못했다 (교대 기록의 이름이 비어 있다)",
                   worker_id)
    return f"(worker {worker_id} 조회 실패)"


# ── 윈도우 수명주기 ─────────────────────────────────────────────────────

async def _reconcile() -> None:
    """배정 현황과 메모리 윈도우를 맞춘다 (§4.3)."""
    active = [a for a in await worker_repository.list_active()
              if a.node_id.startswith(WEARABLE_PREFIX)]
    wanted: set[_WindowKey] = set()

    for assignment in active:
        for metric in (*GAS_METRICS, O2_METRIC):
            key = (assignment.node_id, metric)
            wanted.add(key)
            existing = _windows.get(key)
            if existing is not None:
                if existing.row.worker_id == assignment.worker_id:
                    existing.worker_name = assignment.name
                    continue
                # 같은 웨어러블이 **다른 작업자**에게 넘어갔다. 백엔드가 꺼진 사이
                # 교대가 일어나면 복구된 윈도우의 주인이 지금 착용자와 다르다.
                #
                # 이름만 바꿔 달면 A 의 exposure_id·worker_id 에 B 의 노출이 쌓이고,
                # 교대 로그는 worker_id=A / worker_name=B 라는 자기모순인 행으로
                # 확정된다. A 의 윈도우를 먼저 닫아 A 의 기록을 온전히 남긴다.
                logger.info(
                    "노출량: %s 착용자가 바뀌었다 (worker %s → %s). 이전 윈도우를 "
                    "확정하고 새로 연다",
                    assignment.node_id, existing.row.worker_id, assignment.worker_id,
                )
                await _close(key)
            row = await repo.open_window(
                repo.new_exposure_id(),
                assignment.worker_id,
                assignment.node_id,
                metric,
                assignment.assigned_at,
                "assignment",
            )
            if row is None:
                # DB 에 이미 활성 윈도우가 있다. 다른 프로세스가 열었거나 복구가
                # 늦은 것이다 — 다음 조정에서 _recover 없이도 맞춰진다.
                logger.debug("노출량: 활성 윈도우가 이미 있다 (%s/%s)", *key)
                continue
            _windows[key] = _Window(row, assignment.name)
            logger.info("노출량 윈도우 시작 (%s %s, worker=%s)", *key, assignment.name)

    for key in [k for k in _windows if k not in wanted]:
        await _close(key)


async def _close(key: _WindowKey) -> None:
    """배정이 끝난 윈도우를 확정한다."""
    window = _windows.pop(key, None)
    if window is None:
        return
    now = datetime.now(timezone.utc)
    row = window.to_row()
    metric = row.metric

    if metric == O2_METRIC:
        level = o2_alert_level(
            o2_deficient_s=window.state.o2_deficient_s,
            o2_severe_s=window.state.o2_severe_s,
        )
        fraction = None
    else:
        limit = _limits.get(metric)
        fraction = dose_fraction(
            window.state.dose_ppm_min,
            limit.dose_limit_ppm_min if limit else None,
        )
        # 기준값이 없으면 소진율을 계산할 수 없고, 계산할 수 없었으므로 이 윈도우
        # 동안 노출량 경보는 한 번도 발령되지 않았다. max_alert_level 은 "실제로
        # 도달한 최고 경보 등급"이므로 그 경우 normal 이 사실이다.
        #
        # 이걸 "정상이었다"로 읽으면 안 되는데, 그 구분은 같은 행의
        # dose_fraction IS NULL 이 해 준다 — 판정이 불가능했다는 표시가 남는다.
        # (alert_level_for_fraction(None) 자체는 예외를 낸다. 등급 판정 함수가
        # 조용히 normal 을 돌려주면 살아 있는 경보 경로에서 위험을 덮는다.)
        level = "normal" if fraction is None else alert_level_for_fraction(fraction)

    final = ExposureShiftLogRow(
        exposure_id=row.exposure_id,
        worker_id=row.worker_id,
        worker_name=window.worker_name,
        node_id=row.node_id,
        metric=metric,
        window_start=row.window_start,
        window_end=now,
        dose_ppm_min=window.state.dose_ppm_min if metric != O2_METRIC else None,
        dose_fraction=fraction,
        twa_8h_ppm=twa_8h_ppm(window.state.dose_ppm_min, window.elapsed_s(now))
        if metric != O2_METRIC else None,
        peak_ppm=window.state.peak_ppm,
        o2_deficient_s=int(window.state.o2_deficient_s) if metric == O2_METRIC else None,
        data_gap_s=int(window.state.data_gap_s),
        trust_level=_trust_of(window, now),
        max_alert_level=max_alert_level(window.max_level, level),
    )
    # 해제는 여기서만 일어난다 (§5.2). 농도가 정상으로 돌아왔다는 이유로는 절대
    # 내려가지 않는다.
    await _resolve_alert(window)
    await repo.close_window(row, final)
    logger.info("노출량 윈도우 확정 (%s %s, dose=%.1f ppm·min, gap=%ds)",
                key[0], key[1], window.state.dose_ppm_min, final.data_gap_s)


def _trust_of(window: _Window, now: datetime) -> str:
    return trust_level(
        data_gap_s=window.state.data_gap_s,
        elapsed_s=window.elapsed_s(now),
        source=window.source,  # type: ignore[arg-type]
        source_distance_m=window.source_distance_m,
        unavailable_s=window.unavailable_s,
        max_trust_distance_m=settings.exposure_max_trust_distance_m,
        medium_trust_distance_m=settings.exposure_medium_trust_distance_m,
    )


# ── 적산 ────────────────────────────────────────────────────────────────

async def on_reading(
    node_id: str,
    metric: str,
    value: float,
    sampled_at: datetime,
    *,
    source_mode: str = "live",
    scenario_id: Optional[str] = None,
) -> None:
    """센서 샘플 하나를 적산한다. ingest 가 metric 저장 직후 호출한다 (§4.1).

    고정 tick 이 아니라 이벤트 구동인 이유는 §4.1 이 Δt 를 실제 샘플 간격으로
    정의하기 때문이다.
    """
    if node_id.startswith(WEARABLE_PREFIX):
        if metric != O2_METRIC:
            return
        window = _windows.get((node_id, O2_METRIC))
        if window is None:
            return
        # 웨어러블 직접 측정이라 대입 오차가 없다 (§4.4 → 항상 high).
        window.source = "wearable_direct"
        window.source_node_id = None
        window.source_distance_m = None
        window.state = integrate_o2(
            window.state, value, sampled_at, gap_max_s=settings.exposure_gap_max_s
        )
        window.dirty = True
        await _maybe_alert(window)
        await _broadcast(node_id)
        return

    if metric not in GAS_METRICS:
        return

    touched: set[str] = set()

    for (wearable_id, window_metric), window in _windows.items():
        if window_metric != metric:
            continue
        source_id, distance = _source_for(wearable_id)
        if source_id is None:
            # 위치를 모르면 어느 노드의 농도를 대입할지 정할 수 없다. 가장 가까운
            # 노드를 추측하느니 적산을 멈춘다 — 틀린 귀속은 되돌릴 수 없다.
            window.source = "unavailable"
            window.source_node_id = None
            window.source_distance_m = None
            continue
        if source_id != node_id:
            continue
        window.source = "nearest_node"
        window.source_node_id = source_id
        window.source_distance_m = distance
        # 촬영용 누적 노출 시나리오만 시간을 압축해 보여준다. 실측·다른 시뮬레이션은
        # 기존 적산식(배율 1)을 그대로 사용한다. 순간 농도와 peak/STEL 값은 조작하지
        # 않고 누적 dose 증가분에만 배율을 적용한다.
        dose_scale = (
            6000.0
            if source_mode == "simulation" and scenario_id == "exposure_h2s_danger"
            else 1.0
        )
        window.state = integrate(
            window.state,
            value,
            sampled_at,
            gap_max_s=settings.exposure_gap_max_s,
            dose_scale=dose_scale,
        )
        window.dirty = True
        touched.add(wearable_id)
        await _maybe_alert(window)

    for wearable_id in sorted(touched):
        await _broadcast(wearable_id)


async def _maybe_alert(window: "_Window") -> None:
    """등급이 올라갔으면 경보를 올린다 (§5.1, §5.4).

    **내리지 않는다.** 누적값은 단조 증가하므로 노출량 경보에는 Hysteresis 도
    exit_threshold 도 없다 (§5.2). 해제는 윈도우 종료로만 이루어진다. 이 함수가
    한 방향으로만 움직이는 것이 그 규칙의 구현이다.
    """
    metric = window.row.metric
    if metric == O2_METRIC:
        level = o2_alert_level(
            o2_deficient_s=window.state.o2_deficient_s,
            o2_severe_s=window.state.o2_severe_s,
        )
        trigger = (window.state.o2_severe_s if level == "level3_critical"
                   else window.state.o2_deficient_s)
        threshold = _O2_THRESHOLD_S.get(level, 0.0)
    else:
        limit = _limits.get(metric)
        fraction = dose_fraction(
            window.state.dose_ppm_min, limit.dose_limit_ppm_min if limit else None
        )
        if fraction is None:
            # 기준값이 없으면 판정 자체가 불가능하다. 여기서 normal 을 만들어
            # 내보내면 "확인했고 정상"이라는 거짓 신호가 된다 (§3.2, §6.4).
            return
        exceeded = stel_exceeded(window.state, getattr(limit, "stel_limit_ppm", None))
        level = alert_level_for_fraction(fraction, stel_exceeded=exceeded)
        trigger = window.state.dose_ppm_min
        threshold = limit.dose_limit_ppm_min if limit else 0.0

    if max_alert_level(window.emitted_level, level) == window.emitted_level:
        return  # 같거나 낮다 — 내리지 않는다

    from app.services import alert_service
    await alert_service.handle_transition(AlertTransition(
        node_id=window.row.node_id,          # 웨어러블이다. 가스를 잰 센서가 아니다 (§5.3)
        metric=metric,
        alert_key=ALERT_KEYS[metric],
        from_level=AlertLevel(window.emitted_level),
        to_level=AlertLevel(level),
        value=float(trigger),
        threshold=float(threshold or 0.0),
        timestamp=datetime.now(timezone.utc),
    ))
    window.emitted_level = level
    window.max_level = max_alert_level(window.max_level, level)
    logger.info("노출량 경보 %s %s → %s (worker=%s)",
                window.row.node_id, ALERT_KEYS[metric], level, window.worker_name)
    # 등급 변화는 스로틀을 무시한다 (§6.1). 사람이 즉시 알아야 하는 사건을 최대
    # 5초 늦추는 것은 이 시스템이 존재하는 이유와 어긋난다.
    await _broadcast(window.row.node_id, force=True)


async def _resolve_alert(window: "_Window") -> None:
    """윈도우 종료로만 이루어지는 해제 (§5.2).

    농도가 정상으로 돌아왔다는 이유로는 절대 여기 오지 않는다. 작업자가 공간에서
    나왔거나(배정 해제) 관리자가 수동 리셋한 경우뿐이다.
    """
    if window.emitted_level == "normal":
        return
    from app.services import alert_service
    metric = window.row.metric
    await alert_service.handle_transition(AlertTransition(
        node_id=window.row.node_id,
        metric=metric,
        alert_key=ALERT_KEYS[metric],
        from_level=AlertLevel(window.emitted_level),
        to_level=AlertLevel.NORMAL,
        value=float(window.state.dose_ppm_min),
        threshold=0.0,
        timestamp=datetime.now(timezone.utc),
    ))
    window.emitted_level = "normal"


def _source_for(wearable_id: str) -> Tuple[Optional[str], Optional[float]]:
    """작업자 위치에서 최근접 센서 노드 (ADR-008).

    **IDW 보간값을 쓰지 않는다.** ADR-005 가 추정값의 경보 사용을 금지한다.
    """
    if not _sensor_nodes:
        return None, None
    position = location_service.get_filter().latest(wearable_id)
    if position is None:
        return None, None
    return nearest_node((position.x, position.y), _sensor_nodes)


# ── 스냅샷 / 브로드캐스트 (§6.1) ────────────────────────────────────────

def _metric_payload(window: _Window, now: datetime) -> dict:
    """지표 하나의 페이로드.

    산출 불가는 dose 필드를 **아예 빼고** status/reason 만 남긴다 (§6.1 예시).
    0 으로 채우면 화면이 "노출 0%"로 그리고, 그게 §6.4 가 금지하는 표시다.
    """
    metric = window.row.metric
    if metric == O2_METRIC:
        if window.source == "unavailable":
            return {"status": "unavailable", "reason": "no_position"}
        return {
            "status": "active",
            "exposure_source": window.source,
            "source_node_id": window.source_node_id,
            "source_distance_m": window.source_distance_m,
            "o2_deficient_s": int(window.state.o2_deficient_s),
            "o2_severe_s": int(window.state.o2_severe_s),
            "o2_enriched_s": int(window.state.o2_enriched_s),
            "o2_min_pct": window.state.o2_min_pct,
            "alert_level": o2_alert_level(
                o2_deficient_s=window.state.o2_deficient_s,
                o2_severe_s=window.state.o2_severe_s,
            ),
        }

    limit = _limits.get(metric)
    if limit is None:
        # 고시 원문 대조 전이라 시드하지 않은 상태 (§3.2). 화면은 이것을
        # "기준값 미검증"으로 그린다.
        return {"status": "unavailable", "reason": "limit_unverified"}
    if window.source == "unavailable":
        return {"status": "unavailable", "reason": "no_position"}

    fraction = dose_fraction(window.state.dose_ppm_min, limit.dose_limit_ppm_min)
    stel_limit = getattr(limit, "stel_limit_ppm", None)
    exceeded = stel_exceeded(window.state, stel_limit)
    return {
        "status": "active",
        "exposure_source": window.source,
        "source_node_id": window.source_node_id,
        "source_distance_m": window.source_distance_m,
        "dose_ppm_min": window.state.dose_ppm_min,
        "dose_limit_ppm_min": limit.dose_limit_ppm_min,
        "dose_fraction": fraction,
        "dose_worst_case_ppm_min": window.state.dose_worst_case_ppm_min,
        "twa_8h_ppm": twa_8h_ppm(window.state.dose_ppm_min, window.elapsed_s(now)),
        "twa_15min_ppm": twa_15min_ppm(window.state),
        "stel_limit_ppm": stel_limit,
        "stel_exceeded": exceeded,
        "peak_ppm": window.state.peak_ppm,
        "peak_at": window.state.peak_at.isoformat() if window.state.peak_at else None,
        "alert_level": (
            alert_level_for_fraction(fraction, stel_exceeded=exceeded)
            if fraction is not None else "normal"
        ),
    }


def snapshot(node_id: str) -> Optional[dict]:
    """웨어러블 하나의 worker_exposure 메시지 (§6.1). 윈도우가 없으면 None."""
    windows = {m: w for (n, m), w in _windows.items() if n == node_id}
    if not windows:
        return None
    now = datetime.now(timezone.utc)
    any_window = next(iter(windows.values()))
    elapsed = any_window.elapsed_s(now)
    # 지표마다 공백이 다를 수 있다. 가장 큰 쪽을 대표로 쓴다 — 신뢰도는 보수적으로.
    gap = max(w.state.data_gap_s for w in windows.values())

    return {
        "type": "worker_exposure",
        "worker_id": any_window.row.worker_id,
        "worker_name": any_window.worker_name,
        "node_id": node_id,
        "exposure_id": any_window.row.exposure_id,
        "window_start": any_window.row.window_start.isoformat(),
        "window_source": any_window.row.window_source,
        "elapsed_s": int(elapsed),
        "accumulated_s": int(max(elapsed - gap, 0)),
        "data_gap_s": int(gap),
        "trust_level": _trust_of(any_window, now),
        "timestamp": now.isoformat(),
        "metrics": {m: _metric_payload(w, now) for m, w in windows.items()},
    }


def snapshot_all() -> list[dict]:
    nodes = {n for n, _ in _windows}
    return [s for s in (snapshot(n) for n in sorted(nodes)) if s is not None]


#: 마지막 브로드캐스트 시각 (node_id → epoch 초).
_last_broadcast: Dict[str, float] = {}

#: 발행 주기 (§6.1). dose 는 초 단위로 급변하지 않으므로 샘플마다 보내지 않는다.
BROADCAST_INTERVAL_S = 5.0


async def _broadcast(node_id: str, *, force: bool = False) -> None:
    """worker_exposure 브로드캐스트 (§6.1).

    5초 스로틀이되 **경보 등급이 바뀌면 스로틀을 무시한다.** 등급 변화는 사람이
    즉시 알아야 하는 사건이고, 그걸 최대 5초 늦추는 것은 이 시스템이 존재하는
    이유와 어긋난다.
    """
    now = datetime.now(timezone.utc).timestamp()
    if not force and now - _last_broadcast.get(node_id, 0.0) < BROADCAST_INTERVAL_S:
        return
    message = snapshot(node_id)
    if message is None:
        return
    _last_broadcast[node_id] = now
    try:
        from app.services.ws_manager import manager
        await manager.broadcast(message)
    except Exception:
        logger.exception("노출량 브로드캐스트 실패 (node=%s)", node_id)


# ── 수동 리셋 (§4.3, §5.2) ──────────────────────────────────────────────

async def reset_windows(node_id: str, reason: str, actor: str) -> int:
    """현재 윈도우를 확정하고 새 윈도우를 연다.

    노출량 경보는 자동으로 해제되지 않으므로(§5.2) 이것이 **유일한 해제 경로**다.
    그래서 권한(supervisor+)과 사유를 라우터가 강제한다.

    사유와 행위자를 로그에 남긴다. audit_log 테이블 적재는 라우터가 한다 (FR-605) —
    감사 기록은 "누가 HTTP 로 요청했는가"의 사실이라 요청 경계에 있는 쪽이 안다.
    """
    keys = [k for k in _windows if k[0] == node_id]
    if not keys:
        return 0
    logger.warning(
        "노출량 수동 리셋 (node=%s, actor=%s, 사유=%s, 윈도우 %d개)",
        node_id, actor, reason, len(keys),
    )
    for key in keys:
        await _close(key)
    await _reconcile_reset(node_id)
    return len(keys)


async def _reconcile_reset(node_id: str) -> None:
    """리셋 직후 새 윈도우를 연다. window_source 가 manual_reset 이다."""
    active = {a.node_id: a for a in await worker_repository.list_active()}
    assignment = active.get(node_id)
    if assignment is None:
        return
    now = datetime.now(timezone.utc)
    for metric in (*GAS_METRICS, O2_METRIC):
        row = await repo.open_window(
            repo.new_exposure_id(), assignment.worker_id, node_id, metric,
            now, "manual_reset",
        )
        if row is not None:
            _windows[(node_id, metric)] = _Window(row, assignment.name)


# ── 백그라운드 루프 ─────────────────────────────────────────────────────

async def _flush() -> None:
    """더러워진 윈도우를 저장한다 (§4.5).

    재시작 시 손실 상한이 곧 flush 주기다. 8시간 누적을 메모리에만 두지 않는다.
    """
    dirty = [w for w in _windows.values() if w.dirty]
    if not dirty:
        return
    await repo.flush_states(w.to_row() for w in dirty)
    for w in dirty:
        w.dirty = False


async def _loop() -> None:
    """flush 와 조정을 번갈아 돈다.

    retention.py 의 패턴을 따른다 — 예외를 삼키되 로그를 남기고 다음 tick 에서
    재시도한다. 한 번의 DB 오류로 적산 전체가 죽으면 안 된다.
    """
    since_reconcile = 0.0
    interval = settings.exposure_flush_interval_s
    while True:
        await asyncio.sleep(interval)
        try:
            await _flush()
        except Exception:
            logger.exception("노출량 flush 실패 (다음 tick 에서 재시도)")
        since_reconcile += interval
        if since_reconcile >= RECONCILE_INTERVAL_S:
            since_reconcile = 0.0
            try:
                await _reconcile()
            except Exception:
                logger.exception("노출량 윈도우 조정 실패 (다음 tick 에서 재시도)")
