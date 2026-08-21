# EVACUATION ROUTE SPEC — 비상 탈출 경로 사양서

| 항목 | 내용 |
|------|------|
| 문서명 | 비상 탈출 경로 산출 사양서 |
| 버전 | v0.1 |
| 상태 | 초안 (구현 전 검토 필요) |
| 최종 수정일 | 2026-08-21 |
| 관련 요구사항 | FR-801 ~ FR-808 |
| 관련 ADR | ADR-009 (정적 nav graph), ADR-010 (ship-visual 균일 배율), ADR-005 (IDW 시각화 전용) |

---

## 1. 개요

위험 상황이 발생하면 작업자는 **어디로 나가야 하는지** 알아야 한다. 밀폐공간은 시야가 나쁘고, 출입구가 한두 개뿐이며, 비계와 사다리로 얽혀 있다. 가장 가까운 출구가 반드시 가장 안전한 출구는 아니다 — 가스가 찬 통로를 지나야 한다면 멀리 돌아가는 편이 낫다.

이 기능은 작업자의 실시간 위치, 활성 HazardZone, 그리고 사전 정의된 공간 통행 구조를 입력으로 받아 **위험 가중 최소비용 경로**를 산출하고 2D 평면도와 3D 트윈에 표시한다.

```
작업자 위치(UWB) ─┐
활성 HazardZone  ─┼─→ 위험 가중 Dijkstra ─→ 경로(waypoints) ─→ 2D 평면도 / 3D 트윈
nav graph(정적)  ─┘
```

### 1.1 면책 (필수)

> 산출된 경로는 **참고 정보이며 현장 판단과 정식 대피 절차를 대체하지 않는다.** 경로는 사전 등록된 통행 구조 데이터에만 근거하며, 시스템은 임시 통로·구조물 변경·연기·시야·화재를 인지하지 못한다. 시스템이 경로를 제시하지 못하는 상황에서도 대피는 계속되어야 한다.

---

## 2. 공간 통행 구조 (신규 데이터)

**현재 저장소에는 이 데이터가 없다.** 센서 노드 좌표와 공간 치수(60 × 20 × 14m)만 있을 뿐, "어디를 지나갈 수 있는가"에 대한 정보가 전혀 없다. 이 기능의 선행 작업은 코딩이 아니라 **현장 구조를 데이터로 옮기는 일**이다.

### 2.1 nav_node — 통행 가능 지점

| 변수명 | 타입 | 설명 |
|--------|------|------|
| `nav_node_id` | string | `nav.floor.03`, `nav.exit.manhole-a` 형식. 고유 |
| `kind` | enum | `floor` \| `scaffold_deck` \| `ladder_top` \| `ladder_bottom` \| `exit` |
| `x_m` `y_m` `z_m` | number | 물리 좌표계 (Z-up, `model-local`) |
| `level_id` | string | `L0`(바닥) \| `L1` \| `L2` … 비계 층 식별자 |
| `label` | string | 화면 표시용 이름 ("전방 통로", "1단 비계") |

### 2.2 nav_edge — 이동 가능 구간

| 변수명 | 타입 | 설명 |
|--------|------|------|
| `edge_id` | string | 고유 ID |
| `from_node_id` / `to_node_id` | string | 양 끝 `nav_node_id` |
| `kind` | enum | `walk` \| `scaffold_plank` \| `ladder` \| `hatch` |
| `length_m` | number | 실제 이동 거리. 좌표 직선거리와 다를 수 있음(우회 통로) |
| `traverse_factor` | number | 이동 난이도 계수. §3.2 기본값 |
| `bidirectional` | boolean | 기본 `true`. 사다리 하향 전용 등 예외 표현 |
| `width_m` | number\|null | 통로 폭. 좁으면 병목 — MVP는 표시만 |
| `is_usable` | boolean | 점검·폐쇄 시 `false`. 관리자가 수동 변경 |

### 2.3 exit — 탈출구

| 변수명 | 타입 | 설명 |
|--------|------|------|
| `exit_id` | string | `manhole-a` 형식 |
| `nav_node_id` | string | 대응하는 nav_node |
| `kind` | enum | `manhole` \| `hatch` \| `ladder_out` |
| `x_m` `y_m` `z_m` | number | 물리 좌표 |
| `is_usable` | boolean | 사용 가능 여부 |
| `priority` | integer | 동일 비용일 때 선호 순위 (낮을수록 우선) |
| `label` | string | "전방 접근 트렁크" |

**출구 구성 (결정)**: 실제 선박 화물창 관행에 맞춰 **전방·후방 접근 트렁크 2개**로 한다. 각 트렁크는 바닥에서 상부까지 사다리로 연결된다.

출구를 2개 이상 두는 것은 시연 요건이기도 하다. 출구가 1개면 "가스가 찬 쪽을 피해 다른 출구로 돌아간다"는 이 기능의 핵심이 화면에 전혀 드러나지 않고, `no_safe_route` 폴백만 보이게 된다.

### 2.4 좌표계 — `ship-visual` 기준, 균일 배율 고정 (결정)

nav graph는 **실제 선박 화물창 치수(`ship-visual`, 60m × 20m × 14m)** 기준으로 작성한다. 축소 데모 공간(`demo-local`, 2.5 × 2.0m)에 비계와 사다리를 배치하는 것은 물리적으로 말이 되지 않고, 거리·이동 시간이 실제 작업 상황을 전혀 대표하지 못한다.

그러면 UWB가 산출한 작업자 좌표(`demo-local`)를 그래프 좌표계로 올려야 한다. 변환식은 새로 만들지 않는다 — `05_DIGITAL_TWIN_SPEC.md` §3.1.1의 비율 매핑 식을 그대로 쓴다.

```text
source_x_ratio = raw_x / source_width_m
source_y_ratio = raw_y / source_depth_m
visual_x_m = target_min_x_m + source_x_ratio * target_width_m
visual_y_m = target_min_y_m + source_y_ratio * target_depth_m
visual_z_m = raw_z
```

**단, 프리셋은 `TRUE SCALE`(균일 6.5배)로 고정한다.**

| 프리셋 | 배율 | 경로 계산 사용 |
|--------|------|----------------|
| `TRUE SCALE` | 균일 6.5배 | **사용** |
| `FILL` | x 24배 / y 6.5배 (비균일) | **금지** |

`FILL`은 축마다 배율이 달라 거리가 왜곡된다. 왜곡된 좌표로 Dijkstra를 돌리면 **"가장 가까운 출구"가 실제와 다른 출구로 나온다.** 경로 계산은 거리가 축에 무관하게 보존되는 균일 배율에서만 성립한다.

이에 따른 파생 규칙:

- **MUST**: nav graph YAML의 좌표계 식별자는 `ship-visual`이다.
- **MUST**: 경로 메시지의 `coordinate_system`은 `ship-visual`이다. 프론트엔드는 경로에 **추가 비율 매핑을 적용하지 않는다.** Z-up → Y-up 축 변환(`05_DIGITAL_TWIN_SPEC.md` §3.2)만 적용한다.
- **MUST**: `FILL` 프리셋으로 그리는 화면(모니터링 Screen 1의 축소 트윈)에는 **경로를 표시하지 않는다.** 비균일 배율이라 경로 형상이 실제와 달라진다. 경로는 3D 트윈(Screen 2, `TRUE SCALE`)과 2D 평면도에서만 표시한다.
- **MUST**: 이 변환은 백엔드가 수행한다. 이는 "백엔드는 표시 좌표를 만들지 않는다"는 §3.1.1 규칙의 **의도적 예외**이며 ADR-010에 기록한다. 예외인 이유는 경로가 표시물이 아니라 **기하 계산 결과**이기 때문이다 — 계산을 프론트로 내리면 백엔드의 경보(`no_safe_route`)와 화면의 경로가 서로 다른 그래프에서 나온다.
- 시연 시나리오(`worker_walk_uwb` 등)는 `source_coordinate_system: "ship-visual"`로 직접 발행할 수 있다. §3.1.1에 "`ship-visual`이면 비율 매핑을 적용하지 않는다"는 규칙이 이미 있어 변환이 이중으로 걸리지 않는다.

### 2.5 설정 파일 형식

`config/space_topology.yaml`을 단일 소스로 하고, 기동 시 DB(`nav_nodes`/`nav_edges`/`evacuation_exits`)에 로드한다. `06_ALERT_RULES.md` §4.5 임계값 YAML과 동일한 패턴이다.

아래는 **전방·후방 접근 트렁크 2개** 구성(§2.3 결정)의 골격이다. 실측값으로 채워야 한다.

```yaml
version: 1
coordinate_system: ship-visual   # 60m x 20m x 14m, 균일 배율 (§2.4)
levels:
  - { level_id: L0, name: "화물창 바닥", height_m: 0.0 }
  - { level_id: L1, name: "1단 비계",   height_m: 3.5 }

nav_nodes:
  # 바닥 통로 (선수 → 선미)
  - { nav_node_id: nav.floor.fwd,  kind: floor, x_m:  4.0, y_m: 0.0, z_m: 0.0, level_id: L0, label: "선수 바닥" }
  - { nav_node_id: nav.floor.mid,  kind: floor, x_m: 30.0, y_m: 0.0, z_m: 0.0, level_id: L0, label: "중앙 통로" }
  - { nav_node_id: nav.floor.aft,  kind: floor, x_m: 56.0, y_m: 0.0, z_m: 0.0, level_id: L0, label: "선미 바닥" }
  # 우현측 우회 통로 — 이게 있어야 가스 회피가 눈에 보인다
  - { nav_node_id: nav.floor.stbd, kind: floor, x_m: 30.0, y_m: 5.0, z_m: 0.0, level_id: L0, label: "우현 우회로" }
  # 전방 접근 트렁크 (사다리)
  - { nav_node_id: nav.ladder.fwd.bottom, kind: ladder_bottom, x_m: 2.0, y_m: 0.0, z_m:  0.0, level_id: L0, label: "전방 트렁크 하단" }
  - { nav_node_id: nav.exit.trunk-fwd,    kind: exit,          x_m: 2.0, y_m: 0.0, z_m: 14.0, level_id: L1, label: "전방 접근 트렁크" }
  # 후방 접근 트렁크 (사다리)
  - { nav_node_id: nav.ladder.aft.bottom, kind: ladder_bottom, x_m: 58.0, y_m: 0.0, z_m:  0.0, level_id: L0, label: "후방 트렁크 하단" }
  - { nav_node_id: nav.exit.trunk-aft,    kind: exit,          x_m: 58.0, y_m: 0.0, z_m: 14.0, level_id: L1, label: "후방 접근 트렁크" }

nav_edges:
  - { edge_id: e001, from_node_id: nav.floor.fwd,  to_node_id: nav.floor.mid,  kind: walk, length_m: 26.0, traverse_factor: 1.0, bidirectional: true, width_m: 1.2, is_usable: true }
  - { edge_id: e002, from_node_id: nav.floor.mid,  to_node_id: nav.floor.aft,  kind: walk, length_m: 26.0, traverse_factor: 1.0, bidirectional: true, width_m: 1.2, is_usable: true }
  - { edge_id: e003, from_node_id: nav.floor.fwd,  to_node_id: nav.floor.stbd, kind: walk, length_m: 26.5, traverse_factor: 1.0, bidirectional: true, width_m: 0.9, is_usable: true }
  - { edge_id: e004, from_node_id: nav.floor.stbd, to_node_id: nav.floor.aft,  kind: walk, length_m: 26.5, traverse_factor: 1.0, bidirectional: true, width_m: 0.9, is_usable: true }
  - { edge_id: e005, from_node_id: nav.floor.fwd,  to_node_id: nav.ladder.fwd.bottom, kind: walk,   length_m:  2.0, traverse_factor: 1.0, bidirectional: true, width_m: 0.8, is_usable: true }
  - { edge_id: e006, from_node_id: nav.ladder.fwd.bottom, to_node_id: nav.exit.trunk-fwd, kind: ladder, length_m: 14.0, traverse_factor: 2.5, bidirectional: true, width_m: 0.6, is_usable: true }
  - { edge_id: e007, from_node_id: nav.floor.aft,  to_node_id: nav.ladder.aft.bottom, kind: walk,   length_m:  2.0, traverse_factor: 1.0, bidirectional: true, width_m: 0.8, is_usable: true }
  - { edge_id: e008, from_node_id: nav.ladder.aft.bottom, to_node_id: nav.exit.trunk-aft, kind: ladder, length_m: 14.0, traverse_factor: 2.5, bidirectional: true, width_m: 0.6, is_usable: true }

exits:
  - { exit_id: trunk-fwd, nav_node_id: nav.exit.trunk-fwd, kind: ladder_out, x_m:  2.0, y_m: 0.0, z_m: 14.0, is_usable: true, priority: 1, label: "전방 접근 트렁크" }
  - { exit_id: trunk-aft, nav_node_id: nav.exit.trunk-aft, kind: ladder_out, x_m: 58.0, y_m: 0.0, z_m: 14.0, is_usable: true, priority: 2, label: "후방 접근 트렁크" }
```

> 이 골격은 **출구 2개 + 우회로 1개 + 사다리 2개**를 갖는다. 셋 다 시연에서 각각 다른 것을 보여준다 — 출구 2개는 경로 선택을, 우회로는 가스 회피를, 사다리는 `traverse_factor` 2.5가 비용에 반영되는 것을 드러낸다.

- **MUST**: 기동 시 그래프 무결성을 검증한다. 실패 시 경로 기능만 비활성화하고 **나머지 시스템은 정상 기동한다** (§6.3).

---

## 3. 경로 계산

### 3.1 알고리즘

**Dijkstra** (양수 비용, 노드 수십 개 규모라 A* 휴리스틱 이득 없음). 다중 출구는 **역방향 다중 소스 Dijkstra** 1회로 처리한다 — 모든 출구를 소스로 두고 전체 노드의 "출구까지 최소비용"을 한 번에 구한다.

```
1. 활성 HazardZone으로 각 edge의 hazard_multiplier 갱신
2. 사용 가능한 exit 전체를 소스로 다중 소스 Dijkstra 실행 → dist[], next[]
3. 작업자 위치를 가장 가까운 nav_node에 스냅 → entry_nav_node_id
4. next[] 를 따라가며 waypoints 생성
```

### 3.2 비용 함수

```
edge_cost = length_m × traverse_factor × hazard_multiplier
```

`traverse_factor` 기본값 (설정 파일에서 재정의 가능):

| `kind` | 기본값 | 근거 |
|--------|-------:|------|
| `walk` | 1.0 | 기준 |
| `scaffold_plank` | 1.3 | 발판은 좁고 미끄럽다 |
| `ladder` | 2.5 | 수직 이동은 느리고, 손이 막혀 위험 |
| `hatch` | 1.8 | 통과에 자세 변경 필요 |

`hazard_multiplier` — edge가 활성 HazardZone과 교차할 때:

| HazardZone 등급 | multiplier | 의미 |
|-----------------|-----------:|------|
| `level1_caution` | 1.5 | 가능하면 피함 |
| `level2_warning` | 5.0 | 강하게 회피. 대안이 없으면 통과 |
| `level3_critical` | `BLOCKED` | 차단. 단 §3.5 폴백 적용 |

- 여러 zone과 교차하면 **곱이 아니라 최댓값**을 쓴다. 곱하면 작은 zone 여러 개가 치명 구역보다 비싸지는 역전이 생긴다.
- 교차 판정: 선분–원 교차. HazardZone은 원형이다 (`05_DIGITAL_TWIN_SPEC.md` §5.1).

### 3.3 위치 스냅

작업자의 UWB 좌표는 그래프 위의 점이 아니다.

- 가장 가까운 `nav_node`를 시작점으로 하고 `snap_distance_m`을 기록한다.
- `snap_distance_m > evacuation.max_snap_distance_m`(기본 5.0m)이면 `route_status: "unavailable"`, 사유 `off_graph`. 억지로 붙이지 않는다.
- **MUST**: 첫 waypoint는 작업자의 **실제 위치**이고, 두 번째가 스냅된 nav_node다. 화면에서 경로가 작업자와 떨어져 시작하면 안 된다.

### 3.4 재계산 트리거와 경로 안정성

| 트리거 | 조건 |
|--------|------|
| 위치 변화 | 직전 계산 위치 대비 `≥ 0.5m` 이동 |
| HazardZone 변화 | 생성·해제·등급 변화 |
| 토폴로지 변화 | `is_usable` 변경 |
| 주기 | 최대 `2초`마다 (변화 없어도 1회) |

**경로 깜빡임 방지 (중요)**: 매번 최적 경로를 그대로 채택하면 두 경로 비용이 비슷할 때 화면에서 경로가 좌우로 요동친다. 대피 중인 작업자에게 이건 최악이다.

- **MUST**: 새 경로는 비용이 **현재 경로 비용의 85% 미만**일 때만 교체한다 (`evacuation.route_switch_ratio`).
- **MUST**: 단, 현재 경로가 `BLOCKED` edge를 포함하게 되면 비율과 무관하게 즉시 교체한다.
- **MUST**: 교체 시 `route_id`를 새로 발급하고 `switch_reason`을 기록한다.

### 3.5 폴백 — 안전한 경로가 없을 때

모든 출구가 `level3_critical` 구역 뒤에 있을 수 있다. 이때 "경로 없음"만 띄우고 화면을 비우는 것은 **최악의 설계**다.

| 상황 | `route_status` | 화면 동작 |
|------|----------------|-----------|
| 정상 경로 존재 | `safe` | 초록 경로선 |
| level1/2 구역 통과 불가피 | `degraded` | 주황 경로선 + "위험 구역 통과" 경고 |
| level3 차단 해제 후에만 경로 존재 | `no_safe_route` | 빨강 점선 + "안전 경로 없음 — 최소 위험 경로" 배너 + 즉시 감독자 알림 |
| 그래프 연결 없음 / 스냅 실패 / 위치 없음 | `unavailable` | 경로 미표시 + 사유 표시 |

- **MUST**: `no_safe_route`일 때 `BLOCKED`를 `multiplier: 50.0`으로 완화해 재계산하고 그 결과를 **최소 위험 경로**로 제시한다. 경로를 숨기지 않는다.
- **MUST**: `no_safe_route`는 `level3_critical` 등급의 별도 경보(`alert_key: "no_safe_route"`)를 발령한다.

### 3.6 성능 목표

| 항목 | 목표 |
|------|------|
| 경로 계산 소요 | ≤ 100ms (P95) |
| 트리거 → WebSocket 발행 | ≤ 1초 (P95) |

> 기존 "임계값 초과 → 경보 3초"(FR-203)와 **별개 지표**다. 혼동하지 말 것.

---

## 4. 인터페이스 계약

### 4.1 WebSocket 메시지 (신규 타입)

`WSMessageType`에 `evacuation_route`를 추가한다.

```json
{
  "type": "evacuation_route",
  "route_id": "01J6X3R8K7VQ2NTP5Z9MA4HWBC",
  "node_id": "wearable-01",
  "worker_id": 7,
  "worker_name": "김철수",
  "computed_at": "2026-08-21T03:00:00.120Z",
  "route_status": "degraded",
  "coordinate_system": "ship-visual",
  "assumed_level_id": "L0",
  "target_exit_id": "trunk-fwd",
  "entry_nav_node_id": "nav.floor.mid",
  "snap_distance_m": 0.8,
  "total_length_m": 42.0,
  "total_cost": 96.5,
  "estimated_seconds": 121,
  "hazard_multiplier_max": 5.0,
  "switch_reason": "hazard_changed",
  "waypoints": [
    { "seq": 0, "nav_node_id": null,                    "x_m": 29.4, "y_m": 0.6, "z_m":  0.0, "level_id": "L0", "edge_kind_to_next": "walk",   "label": "현재 위치" },
    { "seq": 1, "nav_node_id": "nav.floor.mid",         "x_m": 30.0, "y_m": 0.0, "z_m":  0.0, "level_id": "L0", "edge_kind_to_next": "walk",   "label": "중앙 통로" },
    { "seq": 2, "nav_node_id": "nav.floor.fwd",         "x_m":  4.0, "y_m": 0.0, "z_m":  0.0, "level_id": "L0", "edge_kind_to_next": "walk",   "label": "선수 바닥" },
    { "seq": 3, "nav_node_id": "nav.ladder.fwd.bottom", "x_m":  2.0, "y_m": 0.0, "z_m":  0.0, "level_id": "L0", "edge_kind_to_next": "ladder", "label": "전방 트렁크 하단" },
    { "seq": 4, "nav_node_id": "nav.exit.trunk-fwd",    "x_m":  2.0, "y_m": 0.0, "z_m": 14.0, "level_id": "L1", "edge_kind_to_next": null,     "label": "전방 접근 트렁크" }
  ],
  "blocked_exits": [
    { "exit_id": "trunk-aft", "reason": "hazard_level3" }
  ],
  "warnings": ["passes_hazard_level2"]
}
```

- JSON Schema: `schemas/evacuation-route.schema.json`
- **MUST**: 좌표계는 `ship-visual`이며 균일 배율이다 (§2.4). 프론트엔드는 추가 비율 매핑을 하지 않고 Z-up → Y-up 축 변환만 적용한다.
- `estimated_seconds` = `Σ (length_m × traverse_factor) / walk_speed_mps`, 기본 `walk_speed_mps = 0.8` (밀폐공간·보호구 착용 감안한 보수값, 설정 가능).

### 4.2 REST API

| 메서드 | 경로 | 권한 | 설명 |
|--------|------|------|------|
| GET | `/api/evacuation/route/{node_id}` | viewer+ | 현재 경로 (초기 로드) |
| GET | `/api/evacuation/topology` | viewer+ | nav graph 전체 (평면도 렌더용) |
| PUT | `/api/evacuation/topology` | admin | 토폴로지 교체. 검증 통과 시에만 적용. 감사 로그 필수 |
| PATCH | `/api/evacuation/exits/{exit_id}` | supervisor+ | `is_usable` 토글. 감사 로그 필수 |
| GET | `/api/evacuation/history` | viewer+ | 과거 경로 이력 (사고 조사) |

### 4.3 DB 스키마 (`009_evacuation.sql`)

```sql
CREATE TABLE IF NOT EXISTS nav_nodes (
    nav_node_id TEXT PRIMARY KEY,
    kind        TEXT NOT NULL,
    x_m         DOUBLE PRECISION NOT NULL,
    y_m         DOUBLE PRECISION NOT NULL,
    z_m         DOUBLE PRECISION NOT NULL,
    level_id    TEXT NOT NULL,
    label       TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS nav_edges (
    edge_id         TEXT PRIMARY KEY,
    from_node_id    TEXT NOT NULL REFERENCES nav_nodes (nav_node_id) ON DELETE CASCADE,
    to_node_id      TEXT NOT NULL REFERENCES nav_nodes (nav_node_id) ON DELETE CASCADE,
    kind            TEXT NOT NULL,
    length_m        DOUBLE PRECISION NOT NULL CHECK (length_m > 0),
    traverse_factor DOUBLE PRECISION NOT NULL DEFAULT 1.0 CHECK (traverse_factor > 0),
    bidirectional   BOOLEAN NOT NULL DEFAULT TRUE,
    width_m         DOUBLE PRECISION,
    is_usable       BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_nav_edges_from ON nav_edges (from_node_id);
CREATE INDEX IF NOT EXISTS idx_nav_edges_to   ON nav_edges (to_node_id);

CREATE TABLE IF NOT EXISTS evacuation_exits (
    exit_id     TEXT PRIMARY KEY,
    nav_node_id TEXT NOT NULL REFERENCES nav_nodes (nav_node_id) ON DELETE CASCADE,
    kind        TEXT NOT NULL,
    is_usable   BOOLEAN NOT NULL DEFAULT TRUE,
    priority    INTEGER NOT NULL DEFAULT 100,
    label       TEXT NOT NULL DEFAULT ''
);

-- 경로 이력. 사고 조사에서 "그때 시스템이 무엇을 지시했는가"를 되짚는 근거다.
-- 매 재계산마다 남기면 폭증하므로 route_id가 바뀔 때(경로 교체)만 기록한다.
CREATE TABLE IF NOT EXISTS evacuation_routes (
    route_id        TEXT PRIMARY KEY,
    node_id         TEXT NOT NULL,
    worker_id       BIGINT,
    worker_name     TEXT NOT NULL DEFAULT '',
    computed_at     TIMESTAMPTZ NOT NULL,
    route_status    TEXT NOT NULL,
    target_exit_id  TEXT,
    total_length_m  DOUBLE PRECISION,
    total_cost      DOUBLE PRECISION,
    switch_reason   TEXT,
    waypoints       JSONB NOT NULL,
    blocked_exits   JSONB NOT NULL DEFAULT '[]'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_evacuation_routes_node_time
    ON evacuation_routes (node_id, computed_at DESC);
```

### 4.4 프론트엔드

| 화면 | 표현 |
|------|------|
| **2D 평면도 영역** | nav graph 회색 실선, 경로 굵은 컬러선, 출구 아이콘, 차단 출구 X 표시 |
| **3D 트윈 화면** (`TwinScene.tsx`) | 바닥 위 경로 튜브 + 진행 방향 화살표 애니메이션. 사다리 구간은 수직 표시 |
| 신규 `EvacuationPanel.tsx` | 목표 출구명, 거리, 예상 시간, 경고 배지, 차단 출구 목록 |
| `SettingsScreen.tsx` | 토폴로지 탭 — 출구 `is_usable` 토글 (admin은 YAML 업로드) |

> **컴포넌트명 주의**: 대시보드 UI가 리팩터링 중이라 파일명이 유동적이다. 본 문서는 특정 파일명이 아니라 **역할**로 배치를 지정한다. 해당 브랜치(`frontend/FR-401-monitoring-console-redesign`)에서 `SpacePlan.tsx`는 제거되고 2D 평면도 역할이 재구성되었다. 구현 시점의 실제 컴포넌트를 확인하고 붙인다.

색상 규약 (`route_status` ↔ 기존 경보 색상 체계 재사용):

| `route_status` | 색 |
|----------------|-----|
| `safe` | 초록 |
| `degraded` | 주황 |
| `no_safe_route` | 빨강 (점선) |
| `unavailable` | 회색 (경로 미표시) |

- **MUST**: 좌표 변환은 `frontend/src/utils/coordinates.ts`의 기존 함수를 재사용한다. 경로용 변환 로직을 새로 만들지 않는다 (좌표계가 두 벌이 되는 순간 어긋난다).
- **MUST**: `assumed_level_id`를 화면에 배지로 표시한다 — "최하층 기준" (§7 한계 #2).

---

## 5. 웨어러블 연동 범위

웨어러블 노드에는 **화면이 없다.** 진동 모터만 있다.

- **MVP 범위**: 경로는 **대시보드에만** 표시한다. 감독자가 무전으로 지시하는 것을 전제한다.
- **OUT OF SCOPE**: 방향 지시 진동(좌/우 패턴 구분), 웨어러블 디스플레이.
- **MAY (FR-808)**: `no_safe_route` 발생 시 기존 `level3_critical` 연속 진동 패턴을 재사용한다. **새 진동 패턴을 만들지 않는다** — 작업자가 패턴을 구분해 외워야 하는 설계는 비상 상황에서 작동하지 않는다.

---

## 6. 실패 모드

### 6.1 입력 결손

| 결손 | 동작 |
|------|------|
| UWB 위치 없음 / 오래됨(>10초) | `route_status: "unavailable"`, 사유 `stale_position` |
| 작업자 미배정 | 경로는 계산하되 `worker_name` 공란 |
| HazardZone 정보 없음 | 위험 가중치 없이 계산 + `warnings: ["hazard_data_missing"]` |

### 6.2 그래프 결손

| 결손 | 동작 |
|------|------|
| 사용 가능한 exit 0개 | `route_status: "no_safe_route"`, 즉시 level3 경보 |
| 시작 노드에서 도달 가능한 exit 없음 | 동일 |
| 스냅 거리 초과 | `route_status: "unavailable"`, 사유 `off_graph` |

### 6.3 토폴로지 검증 실패 시 기동 정책

- **MUST**: 그래프 검증(고아 노드, 끊긴 참조, 음수 길이, exit 0개) 실패 시 **경로 기능만 비활성화**하고 나머지 시스템은 정상 기동한다.
- **MUST**: `/health` 응답에 `evacuation: {"enabled": false, "reason": "..."}` 를 포함한다. **조용히 죽지 않는다** — 이슈 #154(경보 엔진 무음 사망)와 같은 실패를 반복하지 않는다.
- **MUST**: 대시보드에 "탈출 경로 기능 비활성 — 토폴로지 미설정" 배너를 표시한다.

---

## 7. 알려진 한계 (문서·화면에 명시)

| # | 한계 | 영향 |
|---|------|------|
| 1 | nav graph는 사람이 수기로 작성한다 | 데이터가 틀리면 경로도 틀린다. 소프트웨어로 검증 불가 |
| 2 | **UWB 측위가 2D(z=0 고정)라 작업자의 비계 층을 알 수 없다** | 항상 `L0` 가정. 작업자가 비계 위에 있으면 경로 시작점이 틀리다 |
| 3 | 연기·시야·화재·구조물 붕괴를 인지하지 못한다 | 가스 농도만 반영 |
| 4 | HazardZone은 반경 0.5m 원형 근사다 | 실제 가스 분포와 다르다 |
| 5 | 통로 폭(`width_m`)을 병목으로 계산하지 않는다 | 다수 작업자 동시 대피 미고려 (MVP는 작업자 1명) |
| 6 | 경로는 대시보드에만 표시된다 | 작업자 본인은 볼 수 없다 (§5) |
| 7 | 그래프에 없는 임시 통로를 모른다 | 실제로는 더 빠른 길이 있을 수 있다 |
| 8 | 모니터링 화면(`FILL` 프리셋)에는 경로를 표시하지 않는다 | 비균일 배율이라 경로 형상이 왜곡된다. 경로는 3D 트윈과 2D 평면도에서만 본다 (§2.4) |
| 9 | UWB 실측 좌표는 축소 데모 공간을 균일 배율로 확대한 값이다 | 확대된 만큼 위치 오차도 6.5배로 확대된다. 실물 UWB 검증(SUBMISSION_1ST §4.4) 후 재평가가 필요하다 |

> 한계 #2는 근본적이다. 해결하려면 3D 측위 또는 웨어러블 기압계가 필요하며 둘 다 MVP OUT OF SCOPE다 (`01_PRD.md` §1.4). **화면에 가정을 명시하는 것이 유일한 정직한 대응이다.**

---

## 8. 기능 요구사항 (PRD 편입용)

`01_PRD.md`에 **기능 7: 비상 탈출 경로 안내**로 추가한다.

| ID | 강도 | 요구사항 |
|----|------|----------|
| FR-801 | MUST | 통행 가능 구조를 nav graph로 정의하고 설정 파일에서 관리한다 |
| FR-802 | MUST | 작업자 위치에서 사용 가능한 출구까지 위험 가중 최소비용 경로를 산출한다 |
| FR-803 | MUST | `level3_critical` HazardZone과 교차하는 구간을 차단하고, 대안이 없으면 최소 위험 경로를 `no_safe_route` 상태로 제시한다 (§3.5) |
| FR-804 | MUST | 경로를 2D 평면도와 3D 트윈에 표시하고, 목표 출구·거리·예상 시간을 함께 표시한다 |
| FR-805 | MUST | 경로 교체는 `route_switch_ratio` 히스테리시스를 적용해 깜빡임을 방지한다 (§3.4) |
| FR-806 | MUST | 토폴로지 검증 실패 시 경로 기능만 비활성화하고 `/health`에 사유를 노출한다 (§6.3) |
| FR-807 | SHOULD | 경로 교체 이력을 `evacuation_routes`에 기록한다 (사고 조사용) |
| FR-808 | MAY | `no_safe_route` 시 기존 level3 진동 패턴으로 웨어러블에 통지한다 |

### 실험 연결 (`07_EXPERIMENT_PLAN.md` 편입용)

| Test ID | 내용 | 합격 기준 |
|---------|------|-----------|
| EXP-8 | 알려진 그래프에서 경로 정확도 검증 | 손계산 최적 경로와 일치 |
| EXP-8.1 | HazardZone을 최단 경로 위에 주입 | 우회 경로로 전환, 지연 ≤ 1초 (P95) |
| EXP-8.2 | 전 출구 차단 시나리오 | `no_safe_route` + 최소 위험 경로 제시 + level3 경보 |
| EXP-8.3 | 경로 안정성 — 비용 유사한 두 경로 사이 왕복 | 30초간 경로 교체 ≤ 2회 |

---

## 9. 미결 사항

| ID | 항목 | 상태 |
|----|------|------|
| OQ-V1 | nav graph 좌표계 | **해결** — `ship-visual`(실제 선박 치수) 기준, `TRUE SCALE` 균일 배율 고정 (§2.4, ADR-010) |
| OQ-V2 | 출구 개수·구성 | **해결** — 전방·후방 접근 트렁크 2개 (§2.5) |
| OQ-V3 | `traverse_factor` 기본값의 근거 문헌 | 미해결 |
| OQ-V4 | 작업자 다수 확장 시 병목(`width_m`) 반영 여부 | MVP 제외 |
| OQ-V5 | nav graph 실측값 확보 — §2.5 골격의 좌표·길이를 실제 화물창 도면으로 채워야 한다 | **미해결 — 구현 착수 전 필수** |
