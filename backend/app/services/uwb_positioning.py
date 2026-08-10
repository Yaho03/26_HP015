"""2D Least Squares UWB 위치 추정 (이슈 #69).

N개 앵커(x_i, y_i) 와 태그-앵커 거리 d_i 로부터 태그의 2D 위치 (x, y) 추정.
선형화된 최소제곱 시스템 (A^T A) θ = A^T b 를 2x2 closed-form 으로 풀이한다.

수학 (APPENDIX_TECHNICAL.md Least Squares 섹션):
  각 앵커 i: (x - x_i)^2 + (y - y_i)^2 = d_i^2
  기준 앵커(인덱스 0) 로 빼서 선형화:
    2(x_i - x_0) x + 2(y_i - y_0) y = d_0^2 - d_i^2 - x_0^2 + x_i^2 - y_0^2 + y_i^2
  행렬 A(2×N-1) 와 벡트 b(N-1) 로 구성 후 정규방정식 풀이.
"""
from __future__ import annotations

from typing import List, Sequence, Tuple

Anchor = Tuple[float, float]


def least_squares_2d(
    anchors: Sequence[Anchor], distances: Sequence[float]
) -> Tuple[float, float]:
    if len(anchors) < 3:
        raise ValueError("at least 3 anchors required")
    if len(anchors) != len(distances):
        raise ValueError("anchors and distances length mismatch")
    if any(d < 0 for d in distances):
        raise ValueError("distances must be non-negative")

    x0, y0 = anchors[0]
    d0_sq = distances[0] ** 2

    rows: List[Tuple[float, float, float]] = []
    for (xi, yi), di in zip(anchors[1:], distances[1:]):
        a_row_x = 2.0 * (xi - x0)
        a_row_y = 2.0 * (yi - y0)
        b_row = d0_sq - di ** 2 - x0 ** 2 + xi ** 2 - y0 ** 2 + yi ** 2
        rows.append((a_row_x, a_row_y, b_row))

    ata_00 = sum(r[0] * r[0] for r in rows)
    ata_01 = sum(r[0] * r[1] for r in rows)
    ata_11 = sum(r[1] * r[1] for r in rows)
    atb_0 = sum(r[0] * r[2] for r in rows)
    atb_1 = sum(r[1] * r[2] for r in rows)

    det = ata_00 * ata_11 - ata_01 * ata_01
    if abs(det) < 1e-12:
        raise ValueError("degenerate anchor geometry (collinear or duplicate)")

    inv_det = 1.0 / det
    x = inv_det * (ata_11 * atb_0 - ata_01 * atb_1)
    y = inv_det * (-ata_01 * atb_0 + ata_00 * atb_1)
    return (x, y)
