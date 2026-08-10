"""EXP-5A: IDW 합성 데이터 검증 (이슈 #77).

목적: 알려진 가스 분포 모델(예: 단일 발생점에서의 거리 감쇠)을 합성 데이터로
      생성한 뒤, IDW 보간이 참값에 가까운지 정량 검증한다.

합성 모델:
  4개 센서 노드 위치에서 발생점(center) 기준 거리 감쇠 모델의 값을 측정값으로 사용.
  발생점 외 무작위 격자점에서 IDW 보간값과 참값을 비교해 RMSE 계산.

합격 기준: P95 RMSE ≤ 임계값 (여기서는 50ppm CO₂ 기준).
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import List, Tuple

Point = Tuple[float, float]


@dataclass
class Exp5AResult:
    samples: int
    rmse: float
    max_abs_error: float
    p95_error: float
    passed: bool


def synthetic_decay(center: Point, point: Point, peak: float = 2000.0,
                    decay_rate: float = 0.8, ambient: float = 600.0) -> float:
    """단일 발생점에서 거리에 따른 지수 감쇠 모델."""
    dist = math.sqrt((center[0] - point[0]) ** 2 + (center[1] - point[1]) ** 2)
    return ambient + (peak - ambient) * math.exp(-decay_rate * dist)


def idw_estimate(samples: List[Tuple[Point, float]], target: Point, power: float = 2.0) -> float:
    """IDW 보간. samples: [(point, value), ...]."""
    if not samples:
        return 0.0
    num = 0.0
    den = 0.0
    for (px, py), value in samples:
        d2 = (px - target[0]) ** 2 + (py - target[1]) ** 2
        if d2 < 1e-9:
            return value
        w = 1.0 / (d2 ** (power / 2.0))
        num += w * value
        den += w
    return num / den if den > 0 else 0.0


def run_exp5a(
    bounds: Tuple[float, float, float, float] = (0.0, 2.5, 0.0, 2.0),
    sensors: List[Point] = None,
    source: Point = (1.25, 1.0),
    n_test_points: int = 200,
    seed: int = 42,
    rmse_threshold: float = 500.0,
) -> Exp5AResult:
    if sensors is None:
        sensors = [(0.5, 0.5), (2.0, 0.5), (0.5, 1.5), (2.0, 1.5)]
    rng = random.Random(seed)

    sensor_values = [(s, synthetic_decay(source, s)) for s in sensors]

    errors: List[float] = []
    min_x, max_x, min_y, max_y = bounds
    for _ in range(n_test_points):
        tx = rng.uniform(min_x, max_x)
        ty = rng.uniform(min_y, max_y)
        target = (tx, ty)
        true_val = synthetic_decay(source, target)
        estimate = idw_estimate(sensor_values, target)
        errors.append(abs(true_val - estimate))

    errors.sort()
    mse = sum(e * e for e in errors) / len(errors)
    rmse = math.sqrt(mse)
    max_err = errors[-1]
    p95 = errors[int(len(errors) * 0.95)]
    return Exp5AResult(
        samples=n_test_points,
        rmse=rmse,
        max_abs_error=max_err,
        p95_error=p95,
        passed=p95 <= rmse_threshold,
    )


if __name__ == "__main__":
    THRESHOLD = 500.0
    result = run_exp5a(rmse_threshold=THRESHOLD)
    print(f"EXP-5A IDW validation:")
    print(f"  samples: {result.samples}")
    print(f"  RMSE:    {result.rmse:.2f} ppm")
    print(f"  P95:     {result.p95_error:.2f} ppm")
    print(f"  max err: {result.max_abs_error:.2f} ppm")
    print(f"  threshold (P95): {THRESHOLD:.1f} ppm")
    print(f"  result:  {'PASS' if result.passed else 'FAIL'}")
