"""공간 통행 구조(nav graph) 데이터 모델 (FR-801, 12_EVACUATION_ROUTE_SPEC §2).

필드명은 사양서 §2.1~2.3 표를 그대로 따른다. 프론트엔드
`frontend/src/types/evacuation.ts` 와 같은 이름이어야 한다 — 여기서 이름을 새로
지으면 REST 응답이 프론트 타입과 어긋난다.

pydantic 이 잡는 것과 잡지 못하는 것이 나뉜다.
- 잡는 것: 타입, enum 값, `length_m > 0` 같은 필드 단위 제약
- 못 잡는 것: 끊긴 참조, 고아 노드, 도달 불가능한 출구 — 그래프 전체를 봐야 안다

후자는 `services/evacuation_topology.py` 의 검증기가 맡는다.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class NavNodeKind(str, Enum):
    FLOOR = "floor"
    SCAFFOLD_DECK = "scaffold_deck"
    LADDER_TOP = "ladder_top"
    LADDER_BOTTOM = "ladder_bottom"
    EXIT = "exit"


class NavEdgeKind(str, Enum):
    WALK = "walk"
    SCAFFOLD_PLANK = "scaffold_plank"
    LADDER = "ladder"
    HATCH = "hatch"

    @property
    def default_traverse_factor(self) -> float:
        """이동 난이도 기본값 (§3.2).

        설정 파일이 값을 주면 그것이 우선이고, 이 값은 누락 시 폴백이다.
        사다리 2.5 는 수직 이동이 느리고 손이 막혀 위험하다는 판단이다 —
        근거 문헌은 아직 확보되지 않았다 (OQ-V3).
        """
        return {
            NavEdgeKind.WALK: 1.0,
            NavEdgeKind.SCAFFOLD_PLANK: 1.3,
            NavEdgeKind.LADDER: 2.5,
            NavEdgeKind.HATCH: 1.8,
        }[self]


class EvacuationExitKind(str, Enum):
    MANHOLE = "manhole"
    HATCH = "hatch"
    LADDER_OUT = "ladder_out"


class NavLevel(BaseModel):
    """비계 층. UWB 가 2D 라 작업자가 어느 층에 있는지는 측정되지 않는다."""

    model_config = ConfigDict(from_attributes=True)

    level_id: str = Field(..., min_length=1)
    name: str = ""
    height_m: float = 0.0


class NavNode(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    nav_node_id: str = Field(..., min_length=1)
    kind: NavNodeKind
    x_m: float
    y_m: float
    z_m: float
    level_id: str = Field(..., min_length=1)
    label: str = ""


class NavEdge(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    edge_id: str = Field(..., min_length=1)
    from_node_id: str = Field(..., min_length=1)
    to_node_id: str = Field(..., min_length=1)
    kind: NavEdgeKind
    # 0 이하면 Dijkstra 의 비용이 무의미해진다. DB 에도 같은 CHECK 가 걸려 있다.
    length_m: float = Field(..., gt=0)
    traverse_factor: float = Field(1.0, gt=0)
    bidirectional: bool = True
    width_m: float | None = None
    is_usable: bool = True


class EvacuationExit(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    exit_id: str = Field(..., min_length=1)
    nav_node_id: str = Field(..., min_length=1)
    kind: EvacuationExitKind
    x_m: float
    y_m: float
    z_m: float
    is_usable: bool = True
    # 비용이 같을 때의 tie-break. 낮을수록 우선.
    priority: int = 100
    label: str = ""


class NavTopology(BaseModel):
    """통행 구조 전체. config/space_topology.yaml 한 벌과 1:1 대응."""

    model_config = ConfigDict(from_attributes=True)

    version: int = 1
    # ship-visual 만 허용한다. FILL 프리셋 좌표가 들어오면 거리가 왜곡되어
    # 최근접 출구가 실제와 다르게 나온다 (ADR-010).
    coordinate_system: str = "ship-visual"
    levels: list[NavLevel] = Field(default_factory=list)
    nav_nodes: list[NavNode] = Field(default_factory=list)
    nav_edges: list[NavEdge] = Field(default_factory=list)
    exits: list[EvacuationExit] = Field(default_factory=list)

    @property
    def node_ids(self) -> set[str]:
        return {n.nav_node_id for n in self.nav_nodes}


class TopologyStatus(BaseModel):
    """경로 기능이 살아 있는지와 그 사유.

    `/health` 와 대시보드 배너가 이것을 그대로 읽는다. 꺼져 있다는 사실을 화면이
    모르면 관제사는 "경로가 안 뜨는" 것과 "안전한 경로가 없는" 것을 구분할 수 없다.
    """

    enabled: bool
    # enabled=False 일 때만 채운다. 사람이 읽고 고칠 수 있는 문장이어야 한다.
    reason: str | None = None
    # 실측 도면 미반영 여부 (OQ-V5). 화면이 가정값임을 표시하는 근거.
    provisional: bool = True
    node_count: int = 0
    edge_count: int = 0
    exit_count: int = 0
