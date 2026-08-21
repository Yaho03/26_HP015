"""비상 탈출 경로 서비스 (FR-801~808).

지금 담당하는 범위는 **통행 구조 적재와 기능 가용성 판정**이다 (B2). 경로 계산
자체(다중 소스 Dijkstra, 위험 가중, 히스테리시스)는 B3 에서 이 모듈에 들어온다.

── 왜 이 서비스만 예외를 삼키는가 ──────────────────────────────────────
`alert_service.init()` 은 실패를 그대로 전파시켜 기동을 실패시킨다. 경보 판정이
죽은 채로 서버가 "정상" 기동하면 아무도 모르기 때문이다 (이슈 #109/#154).

경로 기능은 반대로 간다. 토폴로지 YAML 에 오타가 났다고 센서 수집과 가스 경보까지
멈추면 훨씬 더 중요한 안전 기능을 잃는다. 그래서 **경로 기능만 끄고 서버는 뜬다**
(12_EVACUATION_ROUTE_SPEC §6.3).

두 정책의 차이를 만드는 것은 "조용한가"다. 이 모듈은 꺼질 때 세 곳에 흔적을 남긴다.

  1. `logger.error` — 로그
  2. `/health` 의 `evacuation.enabled=false` + `reason` — 기계가 읽는 곳
  3. 대시보드 배너 — 사람이 보는 곳

셋 다 사유를 담는다. #154 가 나빴던 것은 실패했다는 사실이 **어디에도** 남지
않았다는 점이지, 실패를 삼킨 것 자체가 아니다.
"""
from __future__ import annotations

import logging

from app.models.evacuation import NavTopology, TopologyStatus
from app.repositories import nav_repository
from app.services import evacuation_topology

logger = logging.getLogger(__name__)

# 기동 전 기본값. init() 이 아직 안 돌았으면 "꺼져 있고 사유는 미초기화"다.
# enabled=True 를 기본값으로 두면 init 이 실패한 뒤에도 켜진 것처럼 보인다.
_status = TopologyStatus(enabled=False, reason="아직 초기화되지 않았다")
_topology: NavTopology | None = None


async def init() -> None:
    """통행 구조를 읽고 검사한 뒤 DB 에 반영한다.

    실패해도 예외를 던지지 않는다 (위 모듈 주석 참고). 대신 상태와 사유를 남긴다.
    """
    global _status, _topology

    topology, errors = evacuation_topology.load_and_validate()

    if topology is None:
        reason = _summarize(errors)
        _topology = None
        _status = TopologyStatus(enabled=False, reason=reason)
        logger.error(
            "evacuation route disabled — 통행 구조 검증 실패: %s "
            "(센서 수집과 가스 경보는 정상 동작한다)",
            reason,
        )
        return

    try:
        await nav_repository.replace_topology(topology)
    except Exception as exc:  # noqa: BLE001 — 사유를 화면까지 전달해야 한다
        reason = f"통행 구조를 DB 에 반영하지 못했다: {exc}"
        _topology = None
        _status = TopologyStatus(enabled=False, reason=reason)
        logger.error("evacuation route disabled — %s", reason)
        return

    _topology = topology
    _status = TopologyStatus(
        enabled=True,
        reason=None,
        # 실측 도면이 들어오기 전까지는 항상 가정값이다 (OQ-V5). 화면이 이 사실을
        # 배지로 표시하는 근거가 된다.
        provisional=True,
        node_count=len(topology.nav_nodes),
        edge_count=len(topology.nav_edges),
        exit_count=len(topology.exits),
    )
    logger.info(
        "evacuation topology loaded — 노드 %d, 엣지 %d, 출구 %d (실측 미반영 가정값)",
        _status.node_count,
        _status.edge_count,
        _status.exit_count,
    )


def _summarize(errors: list[str]) -> str:
    """검증 오류를 한 문장으로 줄인다. /health 응답과 배너에 그대로 실린다.

    전부 싣지 않는 이유는 오류 하나가 연쇄로 수십 개를 만들 수 있어서다. 처음
    세 개와 총 개수면 무엇을 고쳐야 하는지 알기에 충분하고, 전체는 로그에 있다.
    """
    if not errors:
        return "알 수 없는 오류"
    head = "; ".join(errors[:3])
    if len(errors) > 3:
        head += f" (외 {len(errors) - 3}건)"
    return head


def status() -> TopologyStatus:
    """`/health` 와 대시보드가 읽는 현재 상태."""
    return _status


def is_enabled() -> bool:
    return _status.enabled


def get_topology() -> NavTopology | None:
    """적재된 통행 구조. 꺼져 있으면 None.

    B3 의 경로 계산이 이걸 입력으로 받는다. None 을 빈 그래프로 바꿔서 돌려주지
    않는다 — 빈 그래프는 "출구가 없다"로 읽혀서 no_safe_route 경보를 발령하게 되고,
    그건 기능이 꺼진 것과 전혀 다른 의미다.
    """
    return _topology


def reset_for_test() -> None:
    """테스트가 모듈 전역 상태를 초기화할 때 쓴다."""
    global _status, _topology
    _status = TopologyStatus(enabled=False, reason="아직 초기화되지 않았다")
    _topology = None
