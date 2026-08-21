"""비상 탈출 경로 계산 서비스 (FR-801~808).

**현재는 배선용 스텁이다.** 실제 구현은 `docs/12_EVACUATION_ROUTE_SPEC.md` §3 을 따른다.

스텁을 먼저 두는 이유는 exposure_service 와 같다 — 두 기능을 병렬 세션에서
만들기 때문에 main.py lifespan 을 미리 잡아둔다.

구현 시 반드시 지킬 것 (사양서에서 옮겨온 요점):

- 사용 가능한 exit 전체를 소스로 **다중 소스 Dijkstra 1회** 를 돌린다 (§3.1).
  출구마다 반복하지 않는다.
- 엣지 비용은 ``length_m × traverse_factor × hazard_multiplier`` 이고, 여러
  HazardZone 과 교차하면 **곱이 아니라 최댓값**을 쓴다 (§3.2). 곱하면 작은 zone
  여러 개가 치명 구역보다 비싸지는 역전이 생긴다.
- 좌표계는 ``ship-visual`` (실제 선박 치수) + **TRUE SCALE 균일 배율** 고정이다
  (ADR-010). ``FILL`` 프리셋은 x 24배 / y 6.5배 비균일이라 거리가 왜곡되어
  최근접 출구 판정이 틀려진다.
- 경로 교체에 히스테리시스를 건다 (§3.4). 새 경로가 현재의 85% 미만일 때만
  바꾼다. 없으면 비용이 비슷한 두 경로 사이에서 화면이 요동친다.
- **모든 출구가 막혀도 경로를 숨기지 않는다** (§3.5). ``BLOCKED`` 를 완화해
  재계산한 최소 위험 경로를 ``no_safe_route`` 로 제시한다. 대피 중 빈 화면이 최악이다.
- 토폴로지 검증 실패는 **경로 기능만** 끄고 ``/health`` 에 사유를 노출한다 (§6.3).
  나머지 시스템은 정상 기동해야 한다.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def init() -> None:
    """서비스 초기화.

    구현 전이므로 아무것도 하지 않는다. 기능이 꺼져 있다는 사실만 로그로 남긴다
    (§6.3 의 "조용히 죽지 않는다" 원칙 — 구현 후에는 /health 에도 노출한다).
    """
    logger.warning(
        "evacuation_service is a stub — 탈출 경로 계산이 동작하지 않는다 (FR-801, 미구현)"
    )
