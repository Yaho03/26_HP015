# 통행 구조 실측 워크시트 — OQ-V5 (이슈 #225)

> **용도**: `config/space_topology.yaml` 에 들어갈 실측값을 현장에서 기록하는
> 양식이다. 기록이 끝나면 이 표를 보고 YAML 을 채우고, 맨 아래 서명란을
> 채운 뒤 `scripts/topology_check.py` 를 실행해 PASS 를 확인한다.
>
> **현재 YAML 은 전부 가정값이다** — 이 워크시트가 채워지기 전에는 어떤
> 좌표도 안전 판단 근거로 쓸 수 없다 (화면 배지·`/health` provisional 도
> 이 때문에 항상 켜져 있다).

## 0. 측정 전 준비

- [ ] 대상 구획의 도면(일반배치도/화물창 상세도) 확보 — 도면 번호: `___________`
- [ ] 좌표계 확인: **ship-visual** (선박 실치수, Z-up, 원점=화물창 바닥 중심).
  축 방향을 도면에 적어 확인한다: +x = ______ (선수/선미 방향), +y = ______
- [ ] 레이저 거리계 또는 줄자 (측정 오차 ±0.1m 이내 권장)

## 1. 층 (levels)

| level_id | 이름       | 바닥 높이 z (m, 실측) |
|----------|-----------|----------------------|
| L0       | 화물창 바닥 | 0.0 (기준)          |
| L1       | ___단 비계 | ______               |

## 2. 통행 노드 (nav_nodes)

> 측정 기준: 노드는 **사람이 서 있을 수 있는 지점**이다. 통로 교차점,
> 사다리 하단/상단, 출구 위치를 전부 찍는다. 좌표는 해당 층 바닥 기준.

| nav_node_id | 종류 (floor/ladder_bottom/exit/…) | x (m) | y (m) | z (m) | 층 | 라벨(위치 설명) |
|---|---|---|---|---|---|---|
| nav.floor.fwd   | floor | ___ | ___ | ___ | L0 | 선수 바닥 |
| nav.floor.mid   | floor | ___ | ___ | ___ | L0 | 중앙 통로 |
| nav.floor.aft   | floor | ___ | ___ | ___ | L0 | 선미 바닥 |
| nav.floor.stbd  | floor | ___ | ___ | ___ | L0 | 우현 우회로 |
| nav.ladder.fwd.bottom | ladder_bottom | ___ | ___ | ___ | L0 | 전방 트렁크 하단 |
| nav.exit.trunk-fwd    | exit | ___ | ___ | ___ | L1 | 전방 접근 트렁크 |
| nav.ladder.aft.bottom | ladder_bottom | ___ | ___ | ___ | L0 | 후방 트렁크 하단 |
| nav.exit.trunk-aft    | exit | ___ | ___ | ___ | L1 | 후방 접근 트렁크 |
| (추가 노드)      | ___ | ___ | ___ | ___ | ___ | ___ |

**노드 추가/삭제 원칙**: 실제 구획에 우회 통로·해치·추가 출구가 있으면 줄을
더한다. 골격(출구 2 + 우회로 1 + 사다리 2)은 데모 시나리오 EXP-8 이 그림을
보이는 최소 구성이다 — 실측 결과가 우선한다.

## 3. 통행 엣지 (nav_edges)

> length_m 은 **좌표 직선거리가 아니라 실제 걷는 거리**다. 우회 통로는 양
> 끝이 가까워도 돌아가야 하므로 실측값을 적는다. 종류별 traverse_factor
> 기본값: walk 1.0 / scaffold_plank 1.3 / ladder 2.5 / hatch 1.8 (OQ-V3 에서
> 근거 확보 전까지 기본값 유지).

| edge_id | from → to | 종류 | length_m (실측) | 폭 width_m (실측) | 비고 |
|---|---|---|---|---|---|
| e001 | nav.floor.fwd → nav.floor.mid   | walk   | ___ | ___ | |
| e002 | nav.floor.mid → nav.floor.aft   | walk   | ___ | ___ | |
| e003 | nav.floor.fwd → nav.floor.stbd  | walk   | ___ | ___ | 우회로 |
| e004 | nav.floor.stbd → nav.floor.aft  | walk   | ___ | ___ | 우회로 |
| e005 | nav.floor.fwd → nav.ladder.fwd.bottom | walk | ___ | ___ | |
| e006 | nav.ladder.fwd.bottom → nav.exit.trunk-fwd | ladder | ___ | ___ | 수직 __m |
| e007 | nav.floor.aft → nav.ladder.aft.bottom | walk | ___ | ___ | |
| e008 | nav.ladder.aft.bottom → nav.exit.trunk-aft | ladder | ___ | ___ | 수직 __m |

## 4. 출구 (exits)

> 사용 가능 출구는 **2개 이상**이어야 한다 (#225 수용기준 — EXP-8.2 전-출구-차단
> 시나리오의 전제).

| exit_id | 노드 | priority | 실제 확인 사항 |
|---|---|---|---|
| exit-fwd | nav.exit.trunk-fwd | 1 | 해치 개폐 확인: ___ |
| exit-aft | nav.exit.trunk-aft | 2 | 해치 개폐 확인: ___ |

## 5. 검증 및 서명 (OQ-V5)

YAML 반영 후 아래를 실행한다:

```bash
./backend/.venv/bin/python scripts/topology_check.py
# [PASS] 구조 검증 전 항목 통과 — 가 나와야 한다
```

- [ ] `scripts/topology_check.py` PASS 확인
- [ ] 화면 배지가 "통행 구조 가정값" 에서 실측 상태로 전환됐는지 확인
      (YAML 상단 가정값 경고 블록 주석 삭제 + `/health` 의 `provisional` 참조 제거)

**데이터 오너 서명** — 이 값들이 데모 placeholder 가 아닌 실측/도면 기반임을 확인한다:

| 항목 | 내용 |
|---|---|
| 데이터 출처 (도면 번호/실측일) | ____________________ |
| 작성자 (소속/이름) | ____________________ |
| 서명 / 일자 | ____________________ |

> 서명란이 채워지기 전까지 이슈 #225 는 열려 있어야 하고, 시스템은
> `provisional` 상태로 동작한다 (안전 판단 기준 제시 금지 — 08_SAFETY §3.5.3).
