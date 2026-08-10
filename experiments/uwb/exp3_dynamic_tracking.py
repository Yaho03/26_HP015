"""EXP-3: 동적 위치 추적 실험 (이슈 #78).

이동하는 태그의 궤적을 4개 앵커로 추적해 정확도를 검증한다.
- 합성 궤적(원형/사각형 경로)을 따라 이동하는 태그의 참 위치 시퀀스 생성
- 각 시점에서 앵커-태그 거리에 가우시안 노이즈 추가 → Least Squares 추정
- 시간 축 오차 통계 + 경로 추종 품질 측정

합격 기준 (07_EXPERIMENT_PLAN.md EXP-3):
  - P95 오차 ≤ 0.5m (동적 추적은 정적보다 여유 있게 설정)
  - 궤적 완주율 100% (추정 실패 지점 없음)
"""
from __future__ import annotations

import math
import random
import statistics
from dataclasses import dataclass, field
from typing import Callable, List, Tuple

from app.services.uwb_positioning import least_squares_2d

Point = Tuple[float, float]
Anchor = Tuple[float, float]


@dataclass
class Exp3Result:
    frames: int
    success_frames: int
    completion_pct: float
    mean_error_m: float
    rmse_m: float
    p95_error_m: float
    max_error_m: float
    passed: bool
    errors: List[float] = field(default_factory=list)


def circular_trajectory(center: Point, radius: float, t: float, period_s: float = 10.0) -> Point:
    angle = 2 * math.pi * t / period_s
    return (center[0] + radius * math.cos(angle), center[1] + radius * math.sin(angle))


def rect_trajectory(bounds: Tuple[float, float, float, float], t: float, period_s: float = 16.0) -> Point:
    perimeter_t = (t % period_s) / period_s
    min_x, max_x, min_y, max_y = bounds
    wx = max_x - min_x
    wy = max_y - min_y
    perim = 2 * (wx + wy)
    dist = perimeter_t * perim
    corners = [(min_x, min_y), (max_x, min_y), (max_x, max_y), (min_x, max_y)]
    for i in range(4):
        seg_len = math.dist(corners[i], corners[(i + 1) % 4])
        if dist <= seg_len:
            ratio = dist / seg_len
            c1 = corners[i]
            c2 = corners[(i + 1) % 4]
            return (c1[0] + (c2[0] - c1[0]) * ratio, c1[1] + (c2[1] - c1[1]) * ratio)
        dist -= seg_len
    return corners[0]


def run_exp3(
    anchors: List[Anchor] = None,
    trajectory: Callable[[float], Point] = None,
    duration_s: float = 10.0,
    step_s: float = 0.2,
    noise_sigma_m: float = 0.15,
    seed: int = 42,
    p95_threshold_m: float = 0.50,
) -> Exp3Result:
    if anchors is None:
        anchors = [(0.0, 0.0), (2.5, 0.0), (2.5, 2.0), (0.0, 2.0)]
    if trajectory is None:
        trajectory = lambda t: circular_trajectory((1.25, 1.0), 0.6, t)
    rng = random.Random(seed)

    errors: List[float] = []
    frames = 0
    success = 0
    t = 0.0
    while t <= duration_s:
        frames += 1
        true_pos = trajectory(t)
        measured = [
            max(0.0, math.dist(a, true_pos) + rng.gauss(0, noise_sigma_m))
            for a in anchors
        ]
        try:
            est = least_squares_2d(anchors, measured)
            err = math.dist(est, true_pos)
            errors.append(err)
            success += 1
        except ValueError:
            pass
        t += step_s

    errors.sort()
    if not errors:
        return Exp3Result(frames, 0, 0.0, 0.0, 0.0, 0.0, 0.0, False, [])

    completion = success / frames * 100.0
    mean_err = statistics.mean(errors)
    rmse = math.sqrt(statistics.mean(e * e for e in errors))
    p95 = errors[min(int(len(errors) * 0.95), len(errors) - 1)]
    max_err = errors[-1]
    return Exp3Result(
        frames=frames,
        success_frames=success,
        completion_pct=completion,
        mean_error_m=mean_err,
        rmse_m=rmse,
        p95_error_m=p95,
        max_error_m=max_err,
        passed=(p95 <= p95_threshold_m and completion >= 100.0),
        errors=errors,
    )


if __name__ == "__main__":
    print("EXP-3 동적 위치 추적 (원형 궤적):")
    r1 = run_exp3(trajectory=lambda t: circular_trajectory((1.25, 1.0), 0.6, t))
    print(f"  frames: {r1.success_frames}/{r1.frames} ({r1.completion_pct:.1f}%)")
    print(f"  RMSE:   {r1.rmse_m:.4f} m")
    print(f"  P95:    {r1.p95_error_m:.4f} m")
    print(f"  max:    {r1.max_error_m:.4f} m")
    print(f"  result: {'PASS' if r1.passed else 'FAIL'}")
    print()
    print("EXP-3 동적 위치 추적 (사각 궤적):")
    r2 = run_exp3(trajectory=lambda t: rect_trajectory((0.5, 2.0, 0.5, 1.5), t))
    print(f"  frames: {r2.success_frames}/{r2.frames} ({r2.completion_pct:.1f}%)")
    print(f"  RMSE:   {r2.rmse_m:.4f} m")
    print(f"  P95:    {r2.p95_error_m:.4f} m")
    print(f"  max:    {r2.max_error_m:.4f} m")
    print(f"  result: {'PASS' if r2.passed else 'FAIL'}")
