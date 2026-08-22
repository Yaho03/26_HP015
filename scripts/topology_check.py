#!/usr/bin/env python3
"""통행 구조(topology) 검증 CLI — 이슈 #225 수용기준 리포트.

현장 측정 담당자가 config/space_topology.yaml 을 교체한 뒤 실행한다:

    ./backend/.venv/bin/python scripts/topology_check.py [--file PATH]

프로덕션 검증기(backend evacuation_topology)를 그대로 쓴다 — 시험용
검증 로직을 따로 만들면 정작 기동 때 쓰는 검증과 어긋난다 (#124 의 교훈).

이 스크립트가 판정하는 것 (이슈 #225 수용기준 중 SW 검증 가능 항목):
  1. 사용 가능한 출구 >= 2
  2. 모든 edge 가 존재하는 node 를 참조
  3. 모든 length_m > 0
  4. 좌표계 == ship-visual
  5. 모든 노드가 최소 하나의 사용 가능한 출구에 도달 가능 (연결성)

이 스크립트가 판정할 수 없는 것 (반드시 사람이 한다):
  - length_m/좌표가 실측에 근거하는지 — 워크시트(config/space_topology.WORKSHEET.md)
    의 서명란으로만 확인된다 (OQ-V5).
  - traverse_factor 근거 (OQ-V3, 별도 과제).

종료 코드: 0 통과 / 1 실패 / 2 사용법 오류. CI 게이트로 쓸 수 있다.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.services.evacuation_topology import load_and_validate  # noqa: E402


def check(topology) -> list[str]:
    """프로덕션 검증 + #225 수용기준 보강 검사. 문장 리스트를 돌려준다."""
    problems: list[str] = []

    usable_exits = [e for e in topology.exits if e.is_usable]
    if len(usable_exits) < 2:
        problems.append(
            f"사용 가능한 출구가 {len(usable_exits)}개다 — 2개 이상이어야 한다 "
            "(#225: 경로 선택과 전-출구-차단 시나리오 EXP-8.2 가 성립하지 않는다)"
        )

    node_ids = topology.node_ids
    for edge in topology.nav_edges:
        for side, ref in (("from", edge.from_node_id), ("to", edge.to_node_id)):
            if ref not in node_ids:
                problems.append(f"엣지 {edge.edge_id}: {side} 노드 {ref!r} 가 없다")
        if edge.length_m <= 0:
            problems.append(f"엣지 {edge.edge_id}: length_m={edge.length_m} — 양수여야 한다")

    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--file",
        type=Path,
        default=None,
        help="검사할 YAML 경로 (기본: 프로덕션 기본 경로)",
    )
    args = parser.parse_args(argv)

    topology, errors = load_and_validate(args.file)

    print("=" * 64)
    print("통행 구조 검증 — 이슈 #225 수용기준")
    print("=" * 64)

    if topology is None:
        print("[FAIL] YAML 을 읽지 못했다:")
        for e in errors:
            print(f"  - {e}")
        return 1

    print(
        f"노드 {len(topology.nav_nodes)}개 · 엣지 {len(topology.nav_edges)}개 · "
        f"출구 {len(topology.exits)}개(사용 가능 {sum(e.is_usable for e in topology.exits)}) · "
        f"좌표계 {topology.coordinate_system}"
    )

    problems = list(errors) + check(topology)
    if problems:
        print(f"\n[FAIL] 문제 {len(problems)}건:")
        for p in problems:
            print(f"  - {p}")
        return 1

    print("\n[PASS] 구조 검증 전 항목 통과")
    print(
        "\n주의: 이 PASS 는 '구조가 유효하다'는 뜻이다. 좌표·길이가 실측에\n"
        "근거하는지는 소프트웨어가 판정할 수 없다 (OQ-V5). 워크시트\n"
        "config/space_topology.WORKSHEET.md 의 서명란이 채워져야 #225 가 닫힌다."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
