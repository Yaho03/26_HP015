"""작업자 누적 노출량 적산 서비스 (FR-701~708).

**현재는 배선용 스텁이다.** 실제 구현은 `docs/11_EXPOSURE_DOSE_SPEC.md` §4 를 따른다.

스텁을 먼저 두는 이유: 이 기능과 탈출 경로(evacuation_service)를 서로 다른 작업
세션에서 병렬로 만든다. 두 세션이 각자 main.py 의 lifespan 을 고치면 같은 줄에서
충돌한다. 그래서 lifespan 등록과 모듈 자리를 먼저 잡아두고, 각 세션은 자기
모듈 내부만 채운다.

구현 시 반드시 지킬 것 (사양서에서 옮겨온 요점):

- 농도 출처는 **최근접 센서 노드의 실측값**이다 (ADR-008). IDW 보간값을 쓰지
  않는다 — ADR-005 가 추정값의 경보 사용을 금지한다.
- 적산은 고정 tick 이 아니라 **센서 샘플 도착 이벤트 구동** 사다리꼴 적분이다 (§4.1).
- 측정 공백은 마지막 값을 최대 ``gap_max_s`` 까지만 유지해 적산하고, 초과분은
  ``data_gap_s`` 에 쌓는다 (§4.2). 공백을 0 으로 봐도(과소평가), 무한 유지해도
  (dose 폭주) 둘 다 위험하다.
- ``dose_ppm_min`` 을 메모리에만 두지 않는다 (§4.5). 재시작하면 8시간 누적이
  사라진다. ``flush_interval_s`` 마다 ``exposure_state`` 에 flush 하고 기동 시
  복구한다.
- 노출 윈도우는 ``worker_assignments`` 구간과 일치시킨다 (§4.3). shift 테이블을
  새로 만들지 않는다.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def init() -> None:
    """서비스 초기화.

    구현 전이므로 아무것도 하지 않는다. 다만 **조용히 넘어가지는 않는다** —
    기능이 꺼져 있다는 사실이 로그에 남아야 한다 (이슈 #154 의 교훈: 초기화가
    조용히 실패하면 데이터는 계속 쌓이는데 판정만 영구히 멈춘 것을 아무도 모른다).
    """
    logger.warning(
        "exposure_service is a stub — 누적 노출량 적산이 동작하지 않는다 (FR-701, 미구현)"
    )
