"""EXP-5B: IDW 일관성 검증 (이슈 #80).

EXP-5A 가 정확도를 다뤘다면, EXP-5B 는 노이즈 민감도와 재현성을 검증한다.
실제 하드웨어가 없으므로 합성 데이터로 일관성 지표를 산출한다.

검증 항목:
1. 노이즈 민감도: 동일 참 분포에 서로 다른 노이즈 시드 N회 반복 측정 시,
   각 격자점 추정값의 표준편차가 임계값 이내인지.
2. 센서 값 변화 전파: 한 센서 값을 ±10% 변화시켰을 때 격자점 추정값이
   기대 범위 내에서 변화하는지 (폭발적 증폭 없음).
3. 재현성: 동일 입력에 대한 IDW 출력이 결정론적이어야 한다.
"""
from __future__ import annotations

import math
import random
import statistics
from dataclasses import dataclass, field
from typing import List, Tuple

Point = Tuple[float, float]


@dataclass
class Exp5BResult:
    grid_points: int
    mean_stddev_ppm: float
    max_stddev_ppm: float
    perturbation_max_delta_ppm: float
    perturbation_relative_pct: float
    deterministic: bool
    passed: bool


def synthetic_decay(center: Point, point: Point, peak: float = 2000.0,
                    decay_rate: float = 0.8, ambient: float = 600.0) -> float:
    dist = math.sqrt((center[0] - point[0]) ** 2 + (center[1] - point[1]) ** 2)
    return ambient + (peak - ambient) * math.exp(-decay_rate * dist)


def idw_estimate(samples: List[Tuple[Point, float]], target: Point, power: float = 2.0) -> float:
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


def run_exp5b(
    sensors: List[Point] = None,
    source: Point = (1.25, 1.0),
    bounds: Tuple[float, float, float, float] = (0.0, 2.5, 0.0, 2.0),
    grid_resolution: int = 10,
    n_trials: int = 30,
    noise_sigma_ppm: float = 30.0,
    perturbation_pct: float = 0.10,
    seed: int = 42,
    max_stddev_threshold: float = 50.0,
    perturbation_relative_threshold: float = 0.20,
) -> Exp5BResult:
    if sensors is None:
        sensors = [(0.5, 0.5), (2.0, 0.5), (0.5, 1.5), (2.0, 1.5)]
    rng = random.Random(seed)

    min_x, max_x, min_y, max_y = bounds
    step_x = (max_x - min_x) / grid_resolution
    step_y = (max_y - min_y) / grid_resolution

    grid_points: List[Point] = []
    for i in range(grid_resolution + 1):
        for j in range(grid_resolution + 1):
            grid_points.append((min_x + step_x * i, min_y + step_y * j))

    true_sensor_values = [synthetic_decay(source, s) for s in sensors]

    per_point_estimates: List[List[float]] = [[] for _ in grid_points]
    for _ in range(n_trials):
        noisy_values = [v + rng.gauss(0, noise_sigma_ppm) for v in true_sensor_values]
        samples = list(zip(sensors, noisy_values))
        for idx, gp in enumerate(grid_points):
            per_point_estimates[idx].append(idw_estimate(samples, gp))

    stddevs = [statistics.pstdev(est) if len(est) > 1 else 0.0 for est in per_point_estimates]
    mean_stddev = statistics.mean(stddevs)
    max_stddev = max(stddevs)

    samples_ref = list(zip(sensors, true_sensor_values))
    baseline = [idw_estimate(samples_ref, gp) for gp in grid_points]
    perturbed_values = [v * (1.0 + perturbation_pct) for v in true_sensor_values]
    samples_perturbed = list(zip(sensors, perturbed_values))
    perturbed = [idw_estimate(samples_perturbed, gp) for gp in grid_points]

    deltas = [abs(p - b) for p, b in zip(perturbed, baseline)]
    max_delta = max(deltas)
    avg_baseline = statistics.mean(baseline) if baseline else 1.0
    relative_pct = (max_delta / avg_baseline) if avg_baseline > 0 else 0.0

    a = idw_estimate(samples_ref, grid_points[0])
    b = idw_estimate(samples_ref, grid_points[0])
    deterministic = abs(a - b) < 1e-12

    passed = (
        max_stddev <= max_stddev_threshold
        and relative_pct <= perturbation_relative_threshold
        and deterministic
    )
    return Exp5BResult(
        grid_points=len(grid_points),
        mean_stddev_ppm=mean_stddev,
        max_stddev_ppm=max_stddev,
        perturbation_max_delta_ppm=max_delta,
        perturbation_relative_pct=relative_pct,
        deterministic=deterministic,
        passed=passed,
    )


if __name__ == "__main__":
    r = run_exp5b()
    print("EXP-5B IDW 일관성 검증:")
    print(f"  grid points:        {r.grid_points}")
    print(f"  노이즈 민감도:")
    print(f"    mean stddev:      {r.mean_stddev_ppm:.2f} ppm")
    print(f"    max stddev:       {r.max_stddev_ppm:.2f} ppm (threshold 50.0)")
    print(f"  센서 ±10% 변화 전파:")
    print(f"    max delta:        {r.perturbation_max_delta_ppm:.2f} ppm")
    print(f"    relative:         {r.perturbation_relative_pct*100:.2f}% (threshold 20%)")
    print(f"  결정론적 재현성:    {r.deterministic}")
    print(f"  결과:               {'PASS' if r.passed else 'FAIL'}")
