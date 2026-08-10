"""EXP-2: UWB 정적 위치 정확도 실험 (이슈 #77).

정지한 태그의 위치를 4개 앵커 거리 측정으로 추정해 정확도를 검증한다.
- 참 위치(true_x, true_y)에서 각 앵커까지의 참 거리에 가우시안 노이즈를 추가해 측정값 생성
- 백엔드 app.services.uwb_positioning.least_squares_2d 로 추정
- N회 반복 후 오차 통계(RMSE, P95, max) 산출

합격 기준 (07_EXPERIMENT_PLAN.md EXP-2):
  - P95 오차 ≤ 0.3m (UWB 정적 정확도 목표)
"""
from __future__ import annotations

import math
import random
import statistics
from dataclasses import dataclass
from typing import List, Tuple

from app.services.uwb_positioning import least_squares_2d

Point = Tuple[float, float]
Anchor = Tuple[float, float]


@dataclass
class Exp2Result:
    samples: int
    mean_error_m: float
    rmse_m: float
    p95_error_m: float
    max_error_m: float
    passed: bool


def _true_distance(a: Anchor, p: Point) -> float:
    return math.sqrt((a[0] - p[0]) ** 2 + (a[1] - p[1]) ** 2)


def run_exp2(
    anchors: List[Anchor] = None,
    true_position: Point = (1.25, 1.0),
    noise_sigma_m: float = 0.10,
    samples: int = 100,
    seed: int = 42,
    p95_threshold_m: float = 0.30,
) -> Exp2Result:
    if anchors is None:
        anchors = [(0.0, 0.0), (2.5, 0.0), (2.5, 2.0), (0.0, 2.0)]
    rng = random.Random(seed)

    errors: List[float] = []
    for _ in range(samples):
        measured = [
            max(0.0, _true_distance(a, true_position) + rng.gauss(0, noise_sigma_m))
            for a in anchors
        ]
        try:
            est_x, est_y = least_squares_2d(anchors, measured)
        except ValueError:
            continue
        err = math.sqrt((est_x - true_position[0]) ** 2 + (est_y - true_position[1]) ** 2)
        errors.append(err)

    errors.sort()
    if not errors:
        return Exp2Result(0, 0.0, 0.0, 0.0, 0.0, False)

    mean_err = statistics.mean(errors)
    rmse = math.sqrt(statistics.mean(e * e for e in errors))
    p95 = errors[min(int(len(errors) * 0.95), len(errors) - 1)]
    max_err = errors[-1]
    return Exp2Result(
        samples=len(errors),
        mean_error_m=mean_err,
        rmse_m=rmse,
        p95_error_m=p95,
        max_error_m=max_err,
        passed=p95 <= p95_threshold_m,
    )


if __name__ == "__main__":
    result = run_exp2()
    print("EXP-2 UWB 정적 위치 정확도:")
    print(f"  samples:  {result.samples}")
    print(f"  mean err: {result.mean_error_m:.4f} m")
    print(f"  RMSE:     {result.rmse_m:.4f} m")
    print(f"  P95:      {result.p95_error_m:.4f} m")
    print(f"  max err:  {result.max_error_m:.4f} m")
    print(f"  threshold (P95): 0.3000 m")
    print(f"  result:   {'PASS' if result.passed else 'FAIL'}")
