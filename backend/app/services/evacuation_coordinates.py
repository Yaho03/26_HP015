"""측위 좌표 → 경로 좌표 변환 (ADR-010, 12_EVACUATION_ROUTE_SPEC §2.4).

UWB 는 축소 데모 공간(demo-local, 2.5 x 2.0m)의 좌표를 준다. nav graph 는 실제
선박 화물창(ship-visual, 60 x 20 x 14m) 기준으로 작성한다. 그 사이를 잇는다.

── 백엔드가 이 변환을 하는 이유 ────────────────────────────────────────
"백엔드는 표시 좌표를 만들지 않는다"는 §3.1.1 규칙의 **의도적 예외**다. 경로는
표시물이 아니라 기하 계산 결과이기 때문이다. 변환을 프론트로 내리면 백엔드가
발령하는 no_safe_route 경보와 화면에 그려지는 경로가 서로 다른 그래프에서 나온다.

── 프리셋을 TRUE SCALE 로 고정하는 이유 ────────────────────────────────
FILL 프리셋은 축마다 배율이 다르다(x 24배 / y 6.5배). 왜곡된 좌표로 Dijkstra 를
돌리면 "가장 가까운 출구"가 실제와 다른 출구로 나온다. 거리가 축에 무관하게
보존되는 균일 배율에서만 경로 계산이 성립한다.

프론트엔드 `utils/coordinates.ts` 의 UNIFORM_PRESET 과 같은 값을 만든다. 둘이
갈라지면 화면의 작업자 위치와 경로 시작점이 어긋난다.
"""
from __future__ import annotations

# 축소 실험 장비 공간 (05_DIGITAL_TWIN_SPEC §2).
DEMO_LENGTH_M = 2.5
DEMO_WIDTH_M = 2.0

# 선박형 트윈 공간 (§3.1.2). 폭 20m 는 높이 5.5~9.0m 의 수직 측벽에서만 나온다.
# 작업자는 바닥을 걷고 nav graph 도 바닥 평면이므로 매핑 대상은 바닥 폭이다.
SHIP_LENGTH_M = 60.0
SHIP_FLOOR_HALF_WIDTH_M = 6.5
SHIP_FLOOR_WIDTH_M = SHIP_FLOOR_HALF_WIDTH_M * 2

# 두 축에 같은 배율을 쓴다. 폭이 먼저 차서 배율이 결정되고(13 / 2.0 = 6.5),
# 길이 방향은 남는 만큼 가운데 정렬한다.
UNIFORM_SCALE = min(SHIP_LENGTH_M / DEMO_LENGTH_M, SHIP_FLOOR_WIDTH_M / DEMO_WIDTH_M)

_TARGET_WIDTH_M = DEMO_LENGTH_M * UNIFORM_SCALE
_TARGET_DEPTH_M = DEMO_WIDTH_M * UNIFORM_SCALE
_TARGET_MIN_X_M = (SHIP_LENGTH_M - _TARGET_WIDTH_M) / 2
_TARGET_MIN_Y_M = -_TARGET_DEPTH_M / 2


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def demo_to_ship(x_m: float, y_m: float) -> tuple[float, float]:
    """demo-local 실측 좌표 → ship-visual.

    범위를 벗어난 값은 잘라낸다. 측위 오차로 공간 밖 좌표가 들어와도 선체 밖에
    작업자를 그리지 않기 위해서다 — 프론트의 mapDemoToShip 과 같은 처리다.
    """
    return (
        _TARGET_MIN_X_M + _clamp01(x_m / DEMO_LENGTH_M) * _TARGET_WIDTH_M,
        _TARGET_MIN_Y_M + _clamp01(y_m / DEMO_WIDTH_M) * _TARGET_DEPTH_M,
    )


def to_ship_visual(
    x_m: float, y_m: float, source_coordinate_system: str
) -> tuple[float, float]:
    """좌표계를 보고 필요할 때만 변환한다.

    이미 ship-visual 인 값에 다시 적용하면 좌표가 두 번 확대된다. 시연 시나리오가
    ship-visual 을 직접 발행할 수 있으므로(§2.4) 반드시 확인하고 건너뛴다.
    """
    if source_coordinate_system == "ship-visual":
        return x_m, y_m
    return demo_to_ship(x_m, y_m)
