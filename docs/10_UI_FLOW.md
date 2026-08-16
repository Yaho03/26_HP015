# UI FLOW — 대시보드 UI/UX 사양서

| 항목 | 내용 |
|------|------|
| 문서명 | 대시보드 UI/UX 사양서 |
| 버전 | v1.0 |
| 상태 | 확정 |
| 최종 수정일 | 2026-07-14 |

---

## 1. 개요

본 문서는 웹 대시보드의 화면 구조, 컴포넌트 배치, 사용자 인터랙션 흐름, 상태 관리 구조를 정의한다. PRD의 FR-401~403, FR-501~502 요구사항을 화면 단위로 구체화한다.

### 기술 스택

| 계층 | 기술 |
|------|------|
| 프레임워크 | React 19 + TypeScript |
| 3D 렌더링 | React Three Fiber + Three.js |
| 상태 관리 | Zustand |
| 차트 | Recharts |
| 3D 모델 | glTF 2.0 / GLB (Blender) |

---

## 2. 전체 레이아웃

```
+--------------------------------------------------------------+
|  TopBar: 로고 | 전체 위험 등급 표시 | 연결 상태 | 시각       |
+--------+-----------------------------------------------------+
|        |                                                     |
| Side   |   Main Content Area                                |
| Nav    |   (선택한 화면에 따라 교체)                          |
|        |                                                     |
| - 모니터|                                                     |
| - 3D   |                                                     |
| - 차트 |                                                     |
| - 로그 |                                                     |
| - 설정 |                                                     |
|        |                                                     |
+--------+-----------------------------------------------------+
```

### 2.1 TopBar (공통)

| 요소 | 설명 | 데이터 소스 |
|------|------|------------|
| 로고 | 프로젝트명 | 정적 |
| 전체 위험 등급 | Space 객체의 `overall_risk_level` | Zustand: `space.overall_risk_level` |
| 연결 상태 | WebSocket 연결 상태 표시 (녹색 점=연결, 빨간 점=끊김, 노란 점=재연결 중) | Zustand: `ws.connection_status` |
| 현재 시각 | 시스템 UTC 시각 | `setInterval` 1초 |
| 테마 토글 | 다크·라이트 전환 (기본 다크) | `localStorage: hp015-theme` |

### 2.2 SideNav (공통)

| 메뉴 | 화면 | 기능 |
|------|------|------|
| 모니터링 | Screen 1 | 실시간 센서 카드 + 요약 |
| 3D 트윈 | Screen 2 | 3D 디지털 트윈 공간 |
| 시계열 | Screen 3 | 시계열 차트 조회 |
| 이벤트 로그 | Screen 4 | 경보 이력 조회 |
| 설정 | Screen 5 | 임계값, 시스템 설정 |

> Level 3 경보 발령 시 SideNav의 해당 메뉴 아이콘이 빨간색으로 점멸한다.

---

## 3. Screen 1: 실시간 모니터링

> 관련 요구사항: FR-401

### 3.1 레이아웃

```
+--------------------------------------------------------------+
|  [전체 노드 요약 바: 정상 3 / 주의 1 / 경고 0 / 위험 0]    |
+--------------------------------------------------------------+
|  +----------+  +----------+  +----------+  +----------+     |
|  |sensor-01 |  |sensor-02 |  |sensor-03 |  |sensor-04 |     |
|  | [녹색]   |  | [노랑]   |  | [녹색]   |  | [녹색]   |     |
|  | CO2: 612 |  | CO2:1230 |  | CO2: 580 |  | CO2: 650 |     |
|  | CO: raw  |  | CO: raw  |  | CO: raw  |  | CO: raw  |     |
|  | H2S: raw |  | H2S: raw |  | H2S: raw |  | H2S: raw |     |
|  | 온도:24.5|  | 온도:25.1|  | 온도:24.8|  | 온도:24.3|     |
|  | [미니차트]|  | [미니차트]|  | [미니차트]|  | [미니차트]|     |
|  +----------+  +----------+  +----------+  +----------+     |
|                                                              |
|  +----------------------------------------------------+      |
|  | 웨어러블 wearable-01                                |      |
|  | O2: 20.9% | 원본 위치: (2.41, 1.32) demo-local                  |      |
|  |           | 표시 위치: (57.84, 3.20) ship-visual | 배터리: 78% |      |
|  | 낙상: 정상 | 품질: 0.87 (4 anchor)                 |      |
|  +----------------------------------------------------+      |
+--------------------------------------------------------------+
```

### 3.2 센서 노드 카드 (SensorNodeCard)

| 컴포넌트 | 데이터 | Zustand 바인딩 | 갱신 주기 |
|-----------|--------|---------------|-----------|
| 카드 배경색 | `alert_level` | `sensor_nodes[id].alert_level` | 실시간 (Delta) |
| CO2 값 | `co2_ppm` | `sensor_nodes[id].latest_values.co2_ppm` | 1초 |
| CO 값 | `co_estimated_ppm` 또는 "raw" 표시 | `sensor_nodes[id].latest_values` | 1초 |
| H2S 값 | `h2s_ppm` | `sensor_nodes[id].latest_values` | 1초 |
| 온도/습도 | `temperature_c`, `humidity_pct` | `sensor_nodes[id].latest_values` | 5초 |
| 가스저항 | `gas_resistance_ohm` | `sensor_nodes[id].latest_values` | 5초 |
| 교정 배지 | `calibration_status` | `sensor_nodes[id].calibration_status` | 상태 변화 시 |
| 연결 상태 | `connection_status` | `sensor_nodes[id].connection_status` | Delta |
| 최근 수신 시각 | `last_seen_at` | `sensor_nodes[id].last_seen_at` | Delta |
| 미니 차트 (SHOULD) | 최근 1시간 CO2 추세 | Zustand 시계열 버퍼 | 5초 갱신 |

**카드 등급 표현:**

배경색은 등급과 무관하게 패널색으로 고정한다. 등급은 **테두리 · 브래킷 마크 · CO₂ 수치
색상 · 상태 아이콘 · 텍스트 라벨**이 함께 전달한다. 위험도를 색상 단독으로 전달하지
않는다(`PRODUCT.md` 접근성 항목).

| alert_level | 테두리 / 브래킷 | CO₂ 수치 | 아이콘 + 텍스트 |
|-------------|-----------------|----------|-----------------|
| normal | `--normal` | 기본 잉크색 | 체크 + `정상` |
| level1_caution | `--l1` | `--l1` | 삼각 경고 + `L1 주의` |
| level2_warning | `--l2` | `--l2` | 원형 경고 + `L2 경고` |
| level3_critical | `--l3` | `--l3` | 원형 오류 + `L3 위험` |

색상 토큰 값은 `frontend/src/styles/global.css`의 `:root` / `:root[data-theme="light"]`에
정의한다. 다크가 기본이며 라이트(주간) 모드는 같은 구조에 밝은 지면을 쓴다. 지켜야 할
것은 색값이 아니라 **정상 → 주의 → 경고 → 위험 순으로 위험도가 올라가는 의미 체계**다.

**교정 상태 배지:**

| calibration_status | 배지 | 표시 |
|--------------------|------|------|
| calibrated | 없음 | 정상 |
| uncalibrated | "UNCAL" | 회색 배지 |
| calibrating | "CALIBRATING" | 파란색 배지 (회전 아이콘) |

**센서 오류 배지:**

| quality.sensors 값 | 배지 | 색상 |
|---------------------|------|------|
| valid | 없음 | — |
| warming_up | "WARM" | 주황 |
| error | "ERR" | 빨강 |
| not_connected | "N/A" | 회색 |

### 3.3 웨어러블 카드 (WearableCard)

| 요소 | 데이터 | Zustand 바인딩 |
|------|--------|---------------|
| O2 농도 | `o2_pct` | `wearable.o2_pct` |
| O2 색상 | O2 범위에 따른 색상 | 파생 계산 |
| 위치 좌표 | `x_m`, `y_m` | `wearable.position` |
| 배터리 | `battery_pct` | `wearable.battery_pct` |
| 낙상 상태 | `fall_detected` | `wearable.fall_detected` |
| 위치 품질 | `quality_score`, `anchor_count` | `wearable.location_quality` |

**위치 품질 표시:**

| quality_score | 표시 |
|---------------|------|
| >= 0.8 | "GOOD" (녹색) |
| 0.5 ~ 0.8 | "FAIR" (노랑) |
| < 0.5 | "POOR" (빨강) |

> 낙상 감지 시 웨어러블 카드 전체가 빨간색 테두리 + "FALL DETECTED" 오버레이 표시.

### 3.4 전체 요약 바 (SummaryBar)

| 항목 | 계산 | 표시 |
|------|------|------|
| 정상 노드 수 | `alert_level == "normal"`인 노드 수 | 녹색 숫자 |
| 주의 노드 수 | `alert_level == "level1_caution"` | 노랑 숫자 |
| 경고 노드 수 | `alert_level == "level2_warning"` | 주황 숫자 |
| 위험 노드 수 | `alert_level == "level3_critical"` | 빨강 숫자 |

---

## 4. Screen 2: 3D 디지털 트윈

> 관련 요구사항: FR-501, FR-502
> 좌표 변환 규칙: `05_DIGITAL_TWIN_SPEC.md` 섹션 3.2 참조
> 데모 좌표 → 선박형 표시 좌표 비율 매핑: `05_DIGITAL_TWIN_SPEC.md` 섹션 3.1.1 참조

선박형 3D 트윈의 공식 표시 공간은 길이 60m x 폭 20m x 높이 14m이다.
하드웨어가 2.5m x 2.0m x 1.5m 축소 공간에서 측정되는 경우, 원본 좌표는
`demo-local`로 보존하고 화면 표시 좌표만 `ship-visual`로 변환한다.

### 4.1 레이아웃

```
+--------------------------------------------------------------+
|  [3D 캔버스 - WebGL: 화물창/밸러스트 탱크 visual model]      |
|                                                              |
|         +--- 반투명 벽 ---+                                  |
|         |                  |                                  |
|    (S1) |    (W) 아바타   (S2)                               |
|         |      o           |                                  |
|         | [IDW Heatmap]    |                                  |
|    (S3) |                  (S4)                               |
|         +------------------+                                  |
|                                                              |
|  [카메라 컨트롤: 전체 | 탑뷰 | 측면 | 작업자 추적]           |
+--------------------------------------------------------------+
|  [IDW 레이블: "Estimated concentration based on IDW         |
|   interpolation" | "Interpolation based on 4 sensors"]      |
|  [좌표 배지: LIVE/SIM | demo-local → ship-visual | mapped]  |
+--------------------------------------------------------------+
```

### 4.2 3D 캔버스 컴포넌트

| 컴포넌트 | 설명 | Zustand 바인딩 |
|-----------|------|---------------|
| SpaceModel | 밀폐공간 glTF 모델 (반투명 벽) | 정적 로드 |
| SensorMarker x4 | 센서 노드 3D 마커 (구체) | `sensor_nodes[id]` |
| WorkerAvatar | 작업자 캡슐/구체 | `wearable.position` |
| HazardZone | 위험 구역 반투명 원 | `hazard_zones[]` |
| IDWHeatmap | 2D 바닥 평면 색상 맵 | `sensor_nodes` 측정값 |
| AlertOverlay | Level 3 경보 시 화면 효과 | `active_alerts` |

### 4.3 좌표 변환 (Physical Z-up → Three.js Y-up)

센서 데이터의 물리 좌표계는 Z-up이지만, Three.js는 Y-up을 사용한다. 렌더링 시 다음 변환을 적용한다.

```
three_x = physical_x
three_y = physical_z
three_z = -physical_y
```

> `04_DATA_CONTRACT.md` 섹션 8.2, `05_DIGITAL_TWIN_SPEC.md` 섹션 3.2 참조.

### 4.3.1 좌표 매핑 상태 표시

3D 트윈은 길이 60m x 폭 20m x 높이 14m의 선박형 visual model scale을 사용한다.
데모 하드웨어가 축소 공간에서 동작하는 경우 대시보드는 원본 UWB 좌표를 선박형 표시
좌표로 비율 매핑한다.

| UI 요소 | 표시 조건 | 표시 예 |
|---------|-----------|---------|
| 데이터 출처 배지 | `source_mode` | `LIVE`, `SIM` |
| 원본 좌표계 배지 | `source_coordinate_system` | `demo-local` |
| 표시 좌표계 배지 | `position_coordinate_system` | `ship-visual` |
| 매핑 배지 | `visual_mapping != "none"` | `demo-local -> ship-visual` |

`source_mode`와 `visual_mapping`은 별도 상태이다. 실제 UWB 데이터(`source_mode: "live"`)도
축소 데모 공간에서 측정되었다면 `visual_mapping: "demo-to-ship-scale"`로 표시한다.

### 4.4 센서 마커 (SensorMarker)

| 상태 | 색상 | 효과 |
|------|------|------|
| normal | 녹색 (#4CAF50) | 없음 |
| level1_caution | 노랑 (#FFEB3B) | 없음 |
| level2_warning | 주황 (#FF9800) | 펄스 애니메이션 |
| level3_critical | 빨강 (#F44336) | 빠른 펄스 + 확장 |
| offline | 회색 (#9E9E9E) | 반투명 (opacity 0.4) |

**마커 클릭 인터랙션 (SHOULD):**

```
클릭 → 노드 상세 팝업
  - 노드 ID
  - 현재 측정값 전체 (CO2, CO raw, H2S raw, 온도, 습도)
  - 교정 상태
  - 연결 상태
  - 활성 경보 목록
  - 최근 5분 추세 미니 차트
```

### 4.5 작업자 아바타 (WorkerAvatar)

| 상태 | 표시 |
|------|------|
| 정상 | 녹색 테두리 캡슐 |
| 낙상 감지 | 빨간색 테두리 + "FALL" 라벨 + 진동 애니메이션 |
| 위치 품질 낮음 (< 0.5) | 반투명 + "POOR SIGNAL" 라벨 |
| 오프라인 | 회색 + 반투명 |

### 4.6 IDW 히트맵 (IDWHeatmap)

| 요소 | 설명 |
|------|------|
| 렌더링 | 2D 바닥 평면 (Z=0)에 Mesh 색상 매핑 |
| 색상 범위 | 초록(낮음) → 노랑 → 주황 → 빨강(높음) |
| 투명도 | 추정 농도에 비례 (높을수록 불투명) |
| 해상도 | 0.1m 그리드 (10cm 간격) |
| 센서 부족 시 | 2개 이상 오프라인 → "Insufficient data for interpolation" 오버레이 |

> IDW 추정값은 경보 판정에 사용하지 않는다. (ADR-005)

### 4.7 위험 구역 (HazardZone)

| 속성 | 표시 |
|------|------|
| 형상 | 반투명 원형 (실린더 메시, 바닥 평면) |
| 색상 | 주황 (Level 2) / 빨강 (Level 3) |
| 투명도 | opacity 0.3 |
| 반경 | 0.5m (기본값) |

> 작업자 아바타가 위험 구역 내에 진입하면 구역 테두리가 점멸한다.

### 4.8 카메라 컨트롤

| 프리셋 | 설명 | Three.js 카메라 위치 |
|--------|------|---------------------|
| 전체 | 모형 전체가 보이는 기본 각도 | 대각선 상단 |
| 탑뷰 | 위에서 내려다보는 각도 | Y축 상단 |
| 측면 | 옆에서 보는 각도 | X축 측면 |
| 작업자 추적 | 웨어러블 위치 중심으로 추적 | `wearable.position` 따라가기 |

**OrbitControls:**
- 드래그: 회전
- 스크롤: 확대/축소
- 우클릭 드래그: 이동

---

## 5. Screen 3: 시계열 차트

> 관련 요구사항: FR-402

### 5.1 레이아웃

```
+--------------------------------------------------------------+
|  [노드 선택 ▼] [항목 선택 ▼] [시간 범위 ▼] [조회] [CSV]   |
+--------------------------------------------------------------+
|                                                              |
|  CO2 농도 (ppm) - sensor-01 - 최근 1시간                    |
|                                                              |
|  5000 | - - - - - - - - - - - - - - - - - - - L3 임계값    |
|       |                                                      |
|  2000 | - - - - - - - - - - - - - - - - - - - L2 임계값    |
|       |      /\                                               |
|  1000 | ----/--\-----/- - - - - - - - - - - - L1 임계값    |
|       |    /    \   \                                          |
|   600 |---/      \---\--------                                 |
|       |                                                      |
|  00:00   00:15   00:30   00:45   01:00                      |
|                                                              |
|  [임계값 선: 빨간 점선] [측정값: 파란 실선]                  |
+--------------------------------------------------------------+
|  [경보 구간 하이라이트: 배경색 영역으로 표시]               |
+--------------------------------------------------------------+
```

### 5.2 선택 컨트롤

| 컨트롤 | 옵션 | 기본값 |
|--------|------|--------|
| 노드 선택 | sensor-01~04, wearable-01 | sensor-01 |
| 항목 선택 | CO2, CO(raw), H2S(raw), 온도, 습도, O2, 가스저항 | CO2 |
| 시간 범위 | 1시간, 6시간, 24시간, 7일, 사용자 지정 | 1시간 |

### 5.3 차트 기능

| 기능 | 설명 | 상태 |
|------|------|------|
| 임계값 기준선 | 항목별 Level 1/2/3 임계값을 빨간 점선으로 표시 | MUST |
| 측정값 라인 | 파란 실선으로 시계열 데이터 표시 | MUST |
| 경보 구간 하이라이트 | 경보 발생~해제 구간을 배경색으로 표시 | SHOULD |
| 축 줌/팬 | 마우스 드래그로 축 범위 조정 | SHOULD |
| CSV 내보내기 | 조회 결과를 CSV로 다운로드 | SHOULD |
| 실시간 모드 | 최신 데이터가 우측에 추가되는 모드 | MAY |

### 5.4 MQ 센서 미교정 시 표시

교정 전 MQ 센서는 `estimated_ppm`이 null이므로, 차트에서 다음과 같이 표시한다.

| 항목 | 교정 전 표시 | 교정 후 표시 |
|------|-------------|-------------|
| CO | Rs/R0 ratio 차트 + "UNCALIBRATED" 라벨 | ppm 차트 |
| H2S | Rs/R0 ratio 차트 + "UNCALIBRATED" 라벨 | ppm 차트 |
| MQ-2 | Rs/R0 ratio 차트 + "UNCALIBRATED" 라벨 | 추정 농도 차트 |

---

## 6. Screen 4: 이벤트 로그

> 관련 요구사항: FR-403

### 6.1 레이아웃

```
+--------------------------------------------------------------+
|  [필터: 날짜 ▼] [등급 ▼] [노드 ▼] [유형 ▼]    [새로고침]  |
+--------------------------------------------------------------+
|  시각            | 노드       | 유형     | 등급  | 메시지   |
|------------------|------------|----------|-------|----------|
|  01:20:33.080    | sensor-01  | 가스     | L2    | CO2...   |
|  01:20:31.120    | sensor-01  | 가스     | L1    | CO2...   |
|  01:15:22.450    | wearable-01| 낙상     | L3    | 낙상...  |
|  ...                                                          |
+--------------------------------------------------------------+
|  [페이징: < 1 2 3 ... >]  50건/페이지                       |
+--------------------------------------------------------------+
```

### 6.2 필터

| 필터 | 옵션 |
|------|------|
| 날짜 | 오늘, 최근 7일, 최근 30일, 사용자 지정 |
| 등급 | 전체, Level 1, Level 2, Level 3 |
| 노드 | 전체, sensor-01~04, wearable-01 |
| 유형 | 전체, 가스 임계값, 낙상, O2, 위험 구역, 연결 끊김 |

### 6.3 이벤트 행 데이터

| 컬럼 | 데이터 | 정렬 |
|------|--------|------|
| 시각 | `activated_at` | 시간 역순 (기본) |
| 노드 | `source_node_id` | — |
| 유형 | `alert_type` 한국어 표시 | — |
| 등급 | `level` 색상 배지 | — |
| 메시지 | `message` | — |
| 상태 | `status` (active=빨강, resolved=회색) | — |

**유형 표시 매핑:**

| alert_type | 표시 |
|------------|------|
| gas_threshold | 가스 임계값 |
| fall_detection | 낙상 감지 |
| o2_low | O2 저농도 |
| o2_high | O2 고농도 |
| zone_intrusion | 위험 구역 진입 |
| connection_lost | 연결 끊김 |

---

## 7. Screen 5: 설정

> 관련 요구사항: FR-201 (임계값 하드코딩 금지)

### 7.1 레이아웃

```
+--------------------------------------------------------------+
|  탭: [임계값] [위험 구역] [시스템]                           |
+--------------------------------------------------------------+
|                                                              |
|  CO2 임계값                                                  |
|  +-------+----------+----------+----------+----------+       |
|  | 등급  | 진입값   | 진입지속 | 해제값   | 해제지속 |       |
|  +-------+----------+----------+----------+----------+       |
|  | L1    | 1000 ppm | 3000ms   | 900 ppm  | 5000ms   |       |
|  | L2    | 2000 ppm | 3000ms   | 1900 ppm | 5000ms   |       |
|  | L3    | 5000 ppm | 0ms      | 4500 ppm | 5000ms   |       |
|  +-------+----------+----------+----------+----------+       |
|                                                              |
|  [저장] [초기화]                                             |
+--------------------------------------------------------------+
```

### 7.2 임계값 탭

각 경보 항목(CO2, CO, H2S, 온도, O2 저농도, O2 고농도)별로 enter_threshold, enter_for_ms, exit_threshold, exit_for_ms 값을 테이블 형태로 편집한다.

> 저장 시 DB에 반영되며, 백엔드 경보 엔진이 즉시 새 임계값을 사용한다.

### 7.3 위험 구역 탭

| 설정 항목 | 기본값 | 범위 |
|-----------|--------|------|
| 위험 구역 반경 | 0.5m | 0.1m ~ 2.0m |
| 트리거 등급 | Level 2 | Level 2, Level 3 |

---

## 8. 경보 알림 UX

### 8.1 Level 1 (주의)

| 요소 | 동작 |
|------|------|
| 카드 색상 | 노랑 |
| 사이드바 | 해당 메뉴 노랑 표시 |
| 팝업 | 없음 |
| 소리 | 없음 |
| 진동 | 웨어러블: 0.5초 진동 x 2회 |

### 8.2 Level 2 (경고)

| 요소 | 동작 |
|------|------|
| 카드 색상 | 테두리·브래킷·CO₂ 수치가 주황 (§3.2 등급 표현) |
| 사이드바 | 해당 메뉴 주황 점멸 |
| 팝업 | 우측 상단 Toast 알림 (5초 후 자동 닫힘) |
| 소리 | 경고음 1회 |
| 진동 | 웨어러블: 1초 진동 x 3회, 반복 |
| 3D 트윈 | 마커 주황 펄스 + 위험 구역 표시 |

### 8.3 Level 3 (위험)

| 요소 | 동작 |
|------|------|
| 카드 색상 | 테두리·브래킷·CO₂ 수치가 빨강 (§3.2 등급 표현) |
| 사이드바 | 전체 메뉴 빨강 점멸 |
| 팝업 | 전체 화면 모달 (확인 버튼까지 닫히지 않음) |
| 소리 | 사이렌 (확인 시까지 반복) |
| 진동 | 웨어러블: 연속 진동 |
| 3D 트윈 | 마커 빨강 빠른 펄스 + 화면 가장자리 빨강 오버레이 |
| 작업자 추적 | 자동으로 작업자 추적 카메라 모드 전환 (낙상 시) |

### 8.4 경보 해제

| 요소 | 동작 |
|------|------|
| 팝업 | "해제됨" Toast (3초) |
| 카드 | 단계적 하향 (L3 → L2 → L1 → Normal) |
| 사이드바 | 색상 단계적 복귀 |
| 소리 | 해제음 1회 |

### 8.5 O2 경보 특별 표시

| 요소 | 설명 |
|------|------|
| 지연 라벨 | O2 경보 카드에 "센서 응답 지연 가능성 (최대 15초)" 표시 |
| 아이콘 | 가스 경보와 다른 별도 아이콘 (O2 분자 형태) |
| 색상 | 저농도와 고농도를 구분 (저=파랑계, 고=보라계 배지) |

---

## 9. WebSocket 재연결 UX

### 9.1 연결 상태 표시

| 상태 | TopBar 표시 | 동작 |
|------|------------|------|
| connected | 녹색 점 "CONNECTED" | 정상 동작 |
| reconnecting | 노랑 점 "RECONNECTING..." | 데이터 일시 정지, 지수 백오프 재연결 |
| disconnected | 빨강 점 "DISCONNECTED" | 마지막 Snapshot 데이터 표시 + "데이터 연결 끊김" 배너 |

### 9.2 재연결 복구 흐름

```
1. WebSocket 끊김 감지
2. TopBar: 노랑 점 "RECONNECTING..."
3. 지수 백오프: 1s, 2s, 4s, 8s, 30s (최대)
4. 재연결 성공
5. Snapshot 요청 → 수신
6. Zustand Store 전체 교체
7. TopBar: 녹색 점 "CONNECTED"
8. Delta 업데이트 재개
```

> 재연결 중에는 기존 데이터를 그대로 표시하되, 상단에 "데이터 연결 끊김 - 재연결 중..." 배너를 표시한다.

---

## 10. Zustand Store 구조

### 10.1 전체 구조

```typescript
interface DashboardStore {
  // WebSocket 연결 상태
  ws: {
    connection_status: "connected" | "reconnecting" | "disconnected";
    last_snapshot_at: string | null;
  };

  // Space 객체
  space: {
    dimensions: { width_m: number; depth_m: number; height_m: number };
    overall_risk_level: AlertLevel;
  };

  // 센서 노드 (ID 기반 맵)
  sensor_nodes: Record<string, {
    object_id: string;
    physical_id: string;
    position: { x_m: number; y_m: number; z_m: number };
    position_coordinate_system: "model-local";
    latest_values: Record<string, number | null>;
    alert_level: AlertLevel;
    connection_status: "online" | "offline";
    calibration_status: "uncalibrated" | "calibrating" | "calibrated";
  }>;

  // 웨어러블
  wearable: {
    object_id: string;
    physical_id: string;
    position: { x_m: number; y_m: number; z_m: number };
    position_coordinate_system: "model-local";
    location_quality: {
      quality_score: number;
      anchor_count: number;
      is_filtered: boolean;
    };
    o2_pct: number;
    fall_detected: boolean;
    battery_pct: number;
  };

  // 활성 경보 (alert_key 기반 맵)
  active_alerts: Record<string, {
    alert_id: string;
    source_node_id: string;
    alert_key: string;
    alert_type: string;
    level: AlertLevel;
    message: string;
    status: "active" | "resolved";
    activated_at: string;
  }>;

  // 위험 구역
  hazard_zones: Array<{
    object_id: string;
    source_node_id: string;
    geometry: {
      type: "circle";
      center: { x_m: number; y_m: number };
      radius_m: number;
    };
    trigger_level: AlertLevel;
    active: boolean;
  }>;
}
```

### 10.2 상태 갱신 규칙

| 메시지 | 갱신 대상 | 방식 |
|--------|----------|------|
| Snapshot | 전체 Store | 전체 교체 |
| Delta (센서 값) | `sensor_nodes[id].latest_values` | 부분 갱신 (revision 확인) |
| Delta (경보 레벨) | `sensor_nodes[id].alert_level` | 부분 갱신 |
| Alert event (active) | `active_alerts[alert_key]` | 추가/갱신 |
| Alert state (resolved) | `active_alerts[alert_key]` | 제거 또는 status 변경 |
| Connection state | `sensor_nodes[id].connection_status` | 갱신 |
| Wearable position | `wearable.position` | 갱신 (좌표 변환 적용) |

### 10.3 렌더링 영역 격리

Recharts(2D 차트) 컴포넌트와 React Three Fiber(3D 캔버스) 컴포넌트는 Zustand selector를 통해 각각 필요한 상태만 구독한다. 대용량 스트림 유입 시 한쪽의 리렌더가 다른쪽에 영향을 주지 않도록 구독을 분리한다.

```typescript
// 2D 차트: sensor_nodes의 특정 값만 구독
const co2Value = useStore((s) => s.sensor_nodes["sensor-01"]?.latest_values.co2_ppm);

// 3D 캔버스: position만 구독
const workerPos = useStore((s) => s.wearable.position);
```

---

## 11. 시뮬레이션 데이터 표시

`source_mode: "simulation"` 데이터와 실제 센서 데이터를 시각적으로 구분한다.

| 요소 | 실제 데이터 (live) | 시뮬레이션 (simulation) |
|------|-------------------|----------------------|
| 센서 카드 테두리 | 실선 | 점선 |
| 3D 마커 테두리 | 실선 | 점선 |
| 카드 라벨 | 없음 | "SIM" 배지 (회색) |
| 차트 라인 | 실선 | 파선 (dashed) |
| 이벤트 로그 | 일반 표시 | "SIM" 태그 추가 |

> 시뮬레이션 데이터는 실제 센서와 동일한 node_id를 사용하므로, `source_mode` 필드로만 구분한다. (`04_DATA_CONTRACT.md` 섹션 2 참조)
>
> 좌표 비율 매핑은 시뮬레이션 여부와 별개이다. 예를 들어 실제 UWB 측정값도 축소 데모
> 공간에서 측정되어 선박형 트윈에 투영되면 `LIVE` 배지와 `demo-local -> ship-visual`
> 배지를 함께 표시한다.

---

## 12. 반응형 디자인

| 브레이크포인트 | 레이아웃 |
|---------------|---------|
| >= 1280px (Desktop) | SideNav + 4열 카드 + 3D 캔버스 전체 |
| 768~1279px (Tablet) | SideNav(아이콘만) + 2열 카드 + 3D 캔버스 |
| < 768px (Mobile) | 하단 탭바 + 1열 카드 + 3D 캔버스 (핀치 줌) |

> MVP의 주요 타겟은 Desktop (관리자 모니터)이다. Mobile은 SHOULD 수준이다.

---

## 13. 페이지 로딩 및 초기화

### 13.1 초기 로딩 순서

```
1. React 앱 마운트
2. WebSocket 연결 시도
3. 연결 성공 → Snapshot 요청
4. Snapshot 수신 → Zustand Store 초기화
5. 3D 모델(glTF) 로드
6. 카메라 초기 위치 설정
7. 첫 화면 렌더링 (Screen 1: 실시간 모니터링)
8. Delta 스트림 수신 시작
```

### 13.2 로딩 상태 표시

| 단계 | 표시 |
|------|------|
| WebSocket 연결 중 | 스피너 + "서버 연결 중..." |
| Snapshot 수신 대기 | 스피너 + "데이터 로드 중..." |
| 3D 모델 로드 중 | 프로그레스 바 + "3D 모델 로드 중..." |
| 완료 | 정상 화면 표시 |

> 페이지 로드 목표: 중앙값 <= 2초 (PRD 5.1 성능 기준)
