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


class HazardZone(BaseModel):
    """활성 위험 구역. 원형 근사다 (05_DIGITAL_TWIN_SPEC §5.1).

    실제 가스 분포는 원이 아니다. 경로 계산에 쓰는 것은 "이 근처를 지나면 위험하다"는
    정도의 근사이고, 그 이상을 주장하지 않는다 (§7 한계 #4).

    좌표는 ship-visual 이다. 원의 중심은 보통 경보가 뜬 고정 센서 노드의 위치다.
    """

    zone_id: str
    center_x_m: float
    center_y_m: float
    radius_m: float = Field(..., gt=0)
    # normal 은 위험 구역이 아니다. 만들지 않는다.
    level: str = Field(..., pattern=r"^level[123]_(caution|warning|critical)$")


class RouteWaypoint(BaseModel):
    """경로 위의 한 점. schemas/evacuation-route.schema.json 과 필드명이 같아야 한다."""

    seq: int = Field(..., ge=0)
    # seq 0 은 작업자의 실측 위치라 그래프 노드가 아니다.
    nav_node_id: str | None = None
    x_m: float
    y_m: float
    z_m: float
    level_id: str
    # 마지막 waypoint 는 None.
    edge_kind_to_next: str | None = None
    label: str = ""


class BlockedExit(BaseModel):
    exit_id: str
    reason: str  # hazard_level3 | disabled | unreachable


class RouteResult(BaseModel):
    """경로 계산 결과. WebSocket 메시지와 REST 응답이 이것을 그대로 싣는다.

    route_id 와 computed_at 은 여기 없다. 그것들은 "이 경로를 채택했다"는 결정에
    붙는 값이고, 계산 자체는 같은 입력에 같은 결과를 내는 순수 함수여야 한다.
    """

    route_status: str  # safe | degraded | no_safe_route | unavailable
    unavailable_reason: str | None = None
    coordinate_system: str = "ship-visual"
    # UWB 가 2D 라 작업자의 비계 층은 측정된 적이 없다. 항상 가정이다 (§7 한계 #2).
    assumed_level_id: str = "L0"
    target_exit_id: str | None = None
    entry_nav_node_id: str | None = None
    snap_distance_m: float | None = None
    total_length_m: float | None = None
    total_cost: float | None = None
    estimated_seconds: int | None = None
    hazard_multiplier_max: float | None = None
    waypoints: list[RouteWaypoint] = Field(default_factory=list)
    blocked_exits: list[BlockedExit] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


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
