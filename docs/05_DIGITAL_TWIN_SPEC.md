# DIGITAL TWIN SPEC — 디지털 트윈 사양서

| 항목 | 내용 |
|------|------|
| 문서명 | 디지털 트윈 사양서 |
| 버전 | v2.0 |
| 상태 | 확정 |
| 최종 수정일 | 2026-07-13 |

---

## 1. 디지털 트윈 정의

본 프로젝트의 디지털 트윈은 실제 화물창/밸러스트 탱크를 연상시키는 선박 밀폐공간
형상, 고정 센서 노드, 작업자 웨어러블을 3D 공간 객체로 표현하고, 각 객체의 위치,
센서 상태, 경보 상태를 실시간 데이터와 동기화하는 **모니터링용 디지털 트윈**이다.

데모 하드웨어는 약 2.5m x 2.0m x 1.5m 수준의 축소 밀폐공간에서 검증할 수 있다.
이 공간은 하드웨어 실험과 안전한 데이터 주입을 위한 `demo-local` 공간이다.

대시보드의 선박형 3D 트윈은 실제 화물창/밸러스트 탱크의 공간감을 표현하기 위해
별도의 `ship-visual` 공간을 사용한다. 현재 표시 기준 크기는 **길이 60m x 폭 20m x
높이 14m**이며, 이는 축소 데모 공간이 실제 선박 크기로 측정되었다는 뜻이 아니라
관제 시각화를 위한 모델 공간 기준이다. 원본 UWB 좌표와 화면 표시 좌표는 반드시
서로 구분하고, 두 공간 사이의 비율 매핑 정보를 함께 보존한다.

가스 확산 분포는 실제 측정값이 아닌 공간 보간 추정 결과이며, 안전 판단의 단독 근거로 사용하지 않는다.

> Digital Twin Consortium은 디지털 트윈을 "실제 대상과 지정된 주기 및 정밀도로 동기화되는 데이터 기반 가상 표현"으로 정의한다. 본 프로젝트에서는 3D 모델 자체보다 실제 시스템과의 동기화 규칙이 핵심이다.

---

## 2. Twin 객체 모델

### 2.1 객체 정의

| 객체 | 정적 속성 | 동적 상태 |
|------|-----------|-----------|
| **Space** | 크기, 좌표계, 출입구 위치, 장애물 | 전체 위험 등급 |
| **SensorNode** | ID, 3D 위치(x,y,z), 센서 종류 | 측정값, 연결 상태, 교정 상태, 경보 |
| **Wearable** | 작업자 ID, 장착 센서 목록 | 위치(x,y), O2, 낙상 여부, 배터리, 위치 품질 |
| **HazardZone** | 중심 노드, 반경(m), 발생 규칙 | 활성 여부, 위험 등급 |
| **Alert** | 경보 종류, 기준 | 발생, 확인, 해제 상태 |

### 2.2 Physical ID와 3D Object ID 매핑

| Physical ID (node_id) | 3D Object ID | 객체 유형 |
|----------------------|--------------|-----------|
| sensor-01 | tw.sensor-01 | SensorNode |
| sensor-02 | tw.sensor-02 | SensorNode |
| sensor-03 | tw.sensor-03 | SensorNode |
| sensor-04 | tw.sensor-04 | SensorNode |
| wearable-01 | tw.wearable-01 | Wearable |

- 3D 객체 ID는 접두사 `tw.`를 사용한다
- 백엔드 WebSocket 메시지에 physical_id와 object_id를 모두 포함한다
- 시뮬레이션 데이터(`source_mode: "simulation"`)는 동일한 물리 노드 ID를 사용하며, 대시보드에서 `source_mode`로 구분 표시한다
- 좌표 비율 매핑이 적용된 경우 대시보드는 `source_coordinate_system`,
  `position_coordinate_system`, `visual_mapping` 상태를 함께 표시한다

---

## 3. 좌표계

### 3.1 물리 좌표계 (센서 데이터 / 백엔드 기준)

| 항목 | 정의 |
|------|------|
| 원점 | 측정 대상 공간의 왼쪽 전면 바닥 |
| X축 | 공간 가로/길이 방향 |
| Y축 | 공간 깊이/폭 방향 |
| Z축 | 높이 방향 (**Z-up**) |
| 단위 | meter |
| 3D 모델 단위 | 1 Three.js unit = 1 meter |
| 좌표계 식별자 | `model-local` |

센서 데이터(`04_DATA_CONTRACT.md`의 `x_m`, `y_m`)와 백엔드에서 처리하는 모든 좌표는 이 물리 좌표계(Z-up)를 기준으로 한다.

### 3.1.1 데모 좌표와 트윈 표시 좌표

MVP 데모에서는 실제 하드웨어가 축소 공간에서 동작할 수 있으므로, 좌표를 다음 두 층으로
분리한다.

| 좌표계 | 식별자 | 의미 | 사용처 |
|--------|--------|------|--------|
| 원본 데모 좌표 | `demo-local` | 축소 데모 공간에서 UWB가 산출한 실제 측정 좌표 | 검증, 로그, 위치 품질 판단 |
| 트윈 표시 좌표 | `ship-visual` | 선박형 3D 모델 안에 표시하기 위해 비율 매핑한 좌표 | 대시보드 3D 렌더링, 시연 화면 |
| 1:1 모델 좌표 | `model-local` | 원본 좌표를 별도 스케일링 없이 사용하는 좌표 | 실험 모형 1:1 렌더링 또는 백엔드 내부 기준 |

`source_mode`는 데이터가 실제 센서인지 소프트웨어 주입인지 구분한다. 좌표 비율 매핑 여부는
`source_mode`와 별개이며, `visual_mapping`으로 표시한다.

| 필드 | 예 | 설명 |
|------|----|------|
| `source_coordinate_system` | `demo-local` | 원본 위치가 측정된 좌표계 |
| `position_coordinate_system` | `ship-visual` | `position` 필드가 사용하는 표시 좌표계 |
| `visual_mapping` | `demo-to-ship-scale` | 축소 데모 좌표를 선박형 트윈 좌표로 비율 매핑했음을 표시 |
| `position_raw` | `{ "x_m": 1.2, "y_m": 0.8, "z_m": 0.0 }` | UWB/데모 공간 원본 좌표 |
| `position` | `{ "x_m": 28.8, "y_m": 0.7, "z_m": 0.0 }` | 3D 트윈 표시용 좌표 |

> **실시간 location WebSocket 프레임은 `position_raw` 와 `source_coordinate_system`
> 만 보낸다.** 표시 좌표(`position`)는 보내지 않는다 — 화면마다 매핑 프리셋이 다르므로
> (§3.1.4) 백엔드가 어느 하나를 고를 수 없다. 변환은 프론트엔드가 렌더 시점에 한다.
> 위 표의 `position` / `position_coordinate_system` 은 Snapshot(§4.2) 계약에만 남는다.
>
> `source_coordinate_system` 이 `ship-visual` 이면 이미 표시 좌표이므로 비율 매핑을
> 적용하지 않는다. 실제 선박 좌표를 직접 수신하는 경우가 여기 해당하며, 이 규칙이
> 좌표가 두 번 확대되는 것을 막는다.

비율 매핑 예시:

```text
source_x_ratio = raw_x / source_width_m
source_y_ratio = raw_y / source_depth_m

visual_x_m = target_min_x_m + source_x_ratio * target_width_m
visual_y_m = target_min_y_m + source_y_ratio * target_depth_m
visual_z_m = raw_z
```

예: 2.5m x 2.0m 데모 공간을 `FILL` 프리셋(60m x 13m 바닥 평면, §3.1.4)에 매핑할 경우
`raw_x=1.2`, `raw_y=0.8`은 `visual_x=28.8`, `visual_y=-1.3`으로 표시된다
(`target_y` 범위 -6.5m~+6.5m, 폭 방향 중심 0).

### 3.1.2 선박형 트윈 공간 기준

현재 프론트엔드 선박형 트윈의 공식 표시 공간은 다음과 같다.

| 축 | 범위 | 크기 | 의미 |
|----|------|------|------|
| X | 0m ~ 60m | 60m | 선박 화물창 길이 |
| Y | -10m ~ +10m | 20m | 폭 방향(물리 좌표계에서는 Y축) |
| Z | 0m ~ 14m | 14m | 높이 |

프론트엔드 센서 표시 위치는 이 `ship-visual` 공간에서 다음과 같이 관리한다.
바닥 중앙은 `(30, 0)` 이다.

| 노드 | X | Y | 용도 | 중앙 기준 오프셋 | Three.js `(x, y, z)` |
|------|---:|---:|------|------|------|
| sensor-01 | 15m | -3.25m | 전방 port 측 | (-15, 0) | (15, 0, +3.25) |
| sensor-02 | 45m | -3.25m | 후방 port 측 | (+15, 0) | (45, 0, +3.25) |
| sensor-03 | 15m | +3.25m | 전방 starboard 측 | (-15, 0) | (15, 0, -3.25) |
| sensor-04 | 45m | +3.25m | 후방 starboard 측 | (+15, 0) | (45, 0, -3.25) |

**X = 15 / 45 (길이 60m 의 사분점).** IDW 보간에서 "가장 가까운 센서까지의 거리"가
최악인 지점을 최소화하는 배치다.

| 배치 | 바닥 중앙까지 | 끝단 모서리까지 | 최댓값 |
|------|---:|---:|---:|
| x=15/45 (현행) | 15.35m | 약 15.0m | **≈ 15.4m** |
| x=10/50 (이전) | 20.6m | 10.0m | **≈ 20.6m** |

이전 배치는 끝단만 촘촘하고, 정작 작업자가 오래 머무는 중앙이 가장 부실했다.

**Y = ±3.25m (바닥 반폭 6.5m 의 절반).** 선체는 상자가 아니라 길이 방향으로
테이퍼진다(§3.1.3). x=15 지점의 바닥 반폭은 5.93m 이므로 y=±3.25 는 반폭의 **55%**
— 벽에서 충분히 떨어져 있다. 이전 x=10, y=±5 는 그 지점 반폭 5.43m 의 **92%** 로
사실상 벽에 붙어 있었고, 벽면 센서는 공간 평균 농도를 대표하지 못한다.

> 이 좌표는 **표시 전용**이다. 백엔드 UWB 측위(`backend/app/config.py` 의
> `uwb_anchors`)는 축소 데모 공간의 `demo-local` 좌표를 쓰고, 펌웨어에는
> `ship-visual` 좌표가 존재하지 않는다. 즉 경보 판정 경로와 무관하다.

실제 데모 측정값은 이 고정 표시 위치와 직접 혼합하지 않는다. 데모 좌표를 사용하는
경우 `demo-local -> ship-visual` 변환을 적용한 표시 좌표를 별도로 생성한다.

#### 3.1.2.1 `plan` 카메라 화면에서의 사분면

Screen 1 ① 칸은 화물창을 사선 탑뷰(`plan` CamMode)로 크롭해 보여준다. 카메라는
바닥 중앙을 타깃으로 `[30, fit*0.82, -fit*0.58]` 에 서고, 절개된 측벽 바깥에서
안을 들여다본다.

Three.js `lookAt` 기저를 풀면 이 화면의 축은 다음과 같다.

```text
화면 오른쪽 = world -X  →  x_ship 이 작을수록 오른쪽
화면 위쪽   = world +three_z = -y_ship  →  y_ship 이 작을수록 위쪽
```

지도처럼 "X 가 오른쪽"으로 착각하기 쉬우나 **반대다.** 따라서 화면 사분면은:

| 사분면 | 노드 | 위치 |
|--------|------|------|
| 좌상 | sensor-02 | 후방 port |
| 우상 | sensor-01 | 전방 port |
| 좌하 | sensor-04 | 후방 starboard |
| 우하 | sensor-03 | 전방 starboard |

Screen 1 ⑤ 칸(노드별 센서 데이터 2×2)은 이 순서를 그대로 따른다. 구현 상수는
`frontend/src/utils/coordinates.ts` 의 `SENSOR_SCREEN_ORDER` 가 단일 소스이고,
`coordinates.test.ts` 가 실제 카메라 투영과 대조해 검증한다. 좌표나 카메라 각도를
바꾸면 이 테스트가 먼저 깨진다.

#### 3.1.3 매핑 대상은 선체 폭이 아니라 바닥 평면 폭이다

위 표의 `Y -10m ~ +10m` 는 **선체 공간의 크기**다. 매핑 대상 공간이 아니다.

선체 단면은 상자가 아니라 높이에 따라 폭이 변한다. 반폭 10m 는 높이 5.5~9.0m 의
수직 측벽에서만 나오고, **바닥 평면의 반폭은 6.5m** 다. 작업자는 바닥을 걷고
히트맵도 바닥 격자이므로, 둘 다 바닥 평면 안에 있어야 화면이 실제 공간을 왜곡 없이
전달한다. 따라서 `demo-local -> ship-visual` 매핑의 **target 폭은 13m** 로 잡는다.

| 값 | 크기 | 의미 |
|----|------|------|
| `space.dimensions.depth_m` | 20m | 선체 공간 폭 (측벽 기준) |
| 매핑 target 폭 | 13m | 바닥 평면 폭 (`-6.5m ~ +6.5m`) |

두 값이 다른 이유는 선체 테이퍼다. 구현 상수는 `frontend/src/utils/coordinates.ts`
(`SHIP_SPACE`, `SHIP_FLOOR_WIDTH_M`)가 단일 소스다.

#### 3.1.4 매핑 프리셋 — 표시 화면마다 다르다

`demo-local` 공간은 2.5 × 2.0m (형상비 1.25:1)이고 바닥 평면은 60 × 13m
(형상비 4.6:1)다. **형상비를 보존하면서 화물창을 꽉 채우는 것은 불가능하다.**
그래서 화면 목적에 따라 프리셋을 나눈다.

| 프리셋 | 대상 사각형 | 배율 | 쓰는 화면 | 성질 |
|--------|-------------|------|-----------|------|
| `FILL` | 60 × 13m | x 24배 / y 6.5배 | 모니터링(Screen 1) 축소 트윈 | 바닥을 다 쓰지만 형상이 4.6:1 로 늘어남 |
| `TRUE SCALE` | 16.25 × 13m (중앙) | 균일 6.5배 | 3D 트윈(Screen 2) | 정사각 보행이 정사각으로 보임. 길이의 27% 사용 |

균일 배율은 `min(60/2.5, 13/2.0) = 6.5` 로 결정된다 (폭이 먼저 찬다).

**프리셋은 데이터 속성이 아니라 뷰 파라미터다.** 백엔드는 표시 좌표를 보내지 않고,
어느 프리셋을 적용했는지는 화면의 좌표 스트립에 표시한다.

### 3.2 Three.js 렌더링 좌표계 (Y-up) 변환

Three.js는 **Y-up** 좌표계를 사용한다. 센서 데이터의 물리 좌표계(Z-up)와 Three.js 좌표계(Y-up)는 축 매핑이 다르다. 프론트엔드 렌더링 시 다음 변환 규칙을 적용한다.

```
three_x = physical_x
three_y = physical_z
three_z = -physical_y
```

| 물리 좌표계 (Z-up) | Three.js 좌표계 (Y-up) | 의미 |
|---------------------|------------------------|------|
| X (가로/폭) | X | 가로 방향 (변환 없음) |
| Y (깊이) | -Z | 깊이 방향 (부호 반전) |
| Z (높이) | Y | 높이 방향 (Y축으로 매핑) |

**변환 예시:**

| 위치 | 물리 좌표 (x, y, z) | Three.js 좌표 (x, y, z) |
|------|---------------------|-------------------------|
| sensor-01 | (0.5, 0.3, 0.8) | (0.5, 0.8, -0.3) |
| sensor-02 | (2.0, 0.3, 0.8) | (2.0, 0.8, -0.3) |
| wearable-01 | (1.2, 0.8, 0.0) | (1.2, 0.0, -0.8) |

> 이 변환은 프론트엔드 React Three Fiber 렌더링 코드에서만 적용한다. 백엔드, MQTT 페이로드, DB 저장은 모두 물리 좌표계(Z-up)를 사용한다.

### 3.3 UWB 좌표에서 물리 좌표로 변환

UWB 측위 결과는 2D (x, y)이다. 물리 좌표계에서 z축은 고정값으로 매핑한다.

```
물리 좌표:
  x_m = x_uwb
  y_m = y_uwb
  z_m = 0.0  (바닥 높이, 렌더링용 고정값)
```

데모 환경에서 `visual_mapping: "demo-to-ship-scale"`을 사용하는 경우, 위 좌표는
`position_raw`로 보존하고, 대시보드 표시용 `position`은 섹션 3.1.1의 비율 매핑을
적용한 `ship-visual` 좌표로 생성한다.

### 3.4 센서 노드 위치

각 센서 노드의 3D 위치는 고정값이며, 설정 파일에서 관리한다. 아래 좌표는 축소 데모
공간(`demo-local` 또는 1:1 `model-local`) 기준 예시이다.

```json
{
  "sensor-01": { "x_m": 0.5, "y_m": 0.3, "z_m": 0.8 },
  "sensor-02": { "x_m": 2.0, "y_m": 0.3, "z_m": 0.8 },
  "sensor-03": { "x_m": 0.5, "y_m": 1.5, "z_m": 0.8 },
  "sensor-04": { "x_m": 2.0, "y_m": 1.5, "z_m": 0.8 }
}
```

> 센서 노드의 원본 (x, y) 위치는 UWB 앵커 위치와 일치해야 한다. z_m은 설치 높이이다.
> 선박형 3D 트윈을 사용하는 경우, 원본 앵커 좌표는 비율 매핑을 거친 `ship-visual`
> 좌표로 렌더링한다.

---

## 4. 동기화 규칙

### 4.1 실시간 Delta 업데이트 (revision 추적)

백엔드는 WebSocket을 통해 상태 변화를 실시간으로 푸시한다. Delta 메시지에는 revision 번호가 포함되어 순서를 보장한다.

```json
{
  "type": "delta",
  "revision": 18322,
  "object_id": "tw.sensor-01",
  "physical_id": "sensor-01",
  "timestamp": "2026-07-13T01:20:31.120Z",
  "changes": {
    "co2_ppm": 612,
    "alert_level": "normal"
  }
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `type` | string | `"delta"` |
| `revision` | integer | 객체별 증가 리비전 번호. 1부터 시작. 대시보드는 revision 번호로 순서 검증 및 누락 감지 |
| `object_id` | string | 3D 객체 식별자 |
| `physical_id` | string | 물리 노드 식별자 |
| `timestamp` | string | 상태 변화 시각 (UTC) |
| `changes` | object | 변경된 필드와 값 |

> 대시보드는 수신한 revision이 예상 revision(이전 + 1)과 일치하는지 확인한다. 빈 구간이 발견되면 Snapshot을 재요청한다.

### 4.2 전체 Snapshot

대시보드 초기 연결 또는 WebSocket 재연결 시 전체 상태 Snapshot이 전송된다.

```json
{
  "type": "snapshot",
  "revision": 2,
  "timestamp": "2026-07-13T01:20:31.120Z",
  "space": {
    "dimensions": { "width_m": 60.0, "depth_m": 20.0, "height_m": 14.0 },
    "visual_model": "ship-tank",
    "source_coordinate_system": "demo-local",
    "position_coordinate_system": "ship-visual",
    "visual_mapping": "demo-to-ship-scale",
    "mapping_scale": {
      "source_width_m": 2.5,
      "source_depth_m": 2.0,
      "target_width_m": 60.0,
      "target_depth_m": 13.0
    },
    "overall_risk_level": "normal"
  },
  "sensor_nodes": [
    {
      "object_id": "tw.sensor-01",
      "physical_id": "sensor-01",
      "position_raw": { "x_m": 15.0, "y_m": -3.25, "z_m": 0.8 },
      "source_coordinate_system": "ship-visual",
      "position": { "x_m": 15.0, "y_m": -3.25, "z_m": 0.8 },
      "position_coordinate_system": "ship-visual",
      "visual_mapping": "none",
      "latest_values": { "co2_ppm": 612 },
      "alert_level": "normal",
      "connection_status": "online",
      "calibration_status": "uncalibrated"
    }
  ],
  "wearable": {
    "object_id": "tw.wearable-01",
    "physical_id": "wearable-01",
    "position_raw": { "x_m": 1.2, "y_m": 0.8, "z_m": 0.0 },
    "source_coordinate_system": "demo-local",
    "position": { "x_m": 28.8, "y_m": -1.3, "z_m": 0.0 },
    "position_coordinate_system": "ship-visual",
    "visual_mapping": "demo-to-ship-scale",
    "location_quality": {
      "quality_score": 0.87,
      "anchor_count": 4,
      "is_filtered": true
    },
    "o2_pct": 20.9,
    "fall_detected": false,
    "battery_pct": 78
  },
  "active_alerts": [],
  "hazard_zones": []
}
```

**Snapshot 주요 필드:**

| 필드 | 설명 |
|------|------|
| `revision` | Snapshot의 리비전 번호. 이후 Delta는 revision + 1부터 시작 |
| `position_raw` | UWB/데모 공간에서 산출된 원본 위치. 원본 검증과 로그에 사용 |
| `source_coordinate_system` | 원본 위치 좌표계 식별자 (`demo-local` 또는 `model-local`) |
| `position` | 3D 트윈에 표시할 위치. `visual_mapping` 적용 후 좌표일 수 있음 |
| `position_coordinate_system` | 표시 위치 좌표계 식별자 (`ship-visual` 또는 `model-local`) |
| `visual_mapping` | 좌표 비율 매핑 상태 (`none` 또는 `demo-to-ship-scale`) |
| `mapping_scale` | 축소 데모 공간과 선박형 표시 공간의 매핑 크기 |
| `location_quality` | 웨어러블 위치 품질 정보 (quality_score, anchor_count, is_filtered) |

> Snapshot의 `position` 필드는 `position_coordinate_system`에 명시된 좌표계를 사용한다.
> `position_coordinate_system: "ship-visual"`인 경우 이미 선박형 모델의 표시 좌표로
> 비율 매핑된 값이다. Three.js 렌더링 시에는 섹션 3.2의 Z-up → Y-up 축 변환을 추가로
> 적용한다.

### 4.3 WebSocket 재연결 복구

1. WebSocket 연결 끊김 감지
2. 자동 재연결 시도 (지수 백오프: 1s, 2s, 4s, 8s, 최대 30s)
3. 재연결 성공 시 `type: "snapshot"` 요청
4. 백엔드가 현재 전체 상태 Snapshot을 응답
5. Zustand Store를 Snapshot으로 교체
6. 이후 Delta 업데이트 재개 (revision 연속성 확인)

---

## 5. HazardZone 객체

### 5.1 정의

HazardZone은 Level 2 이상 경보가 발령된 센서 노드 주변의 위험 영역이다.

```json
{
  "object_id": "tw.hazard-zone.sensor-01",
  "source_node_id": "sensor-01",
  "geometry": {
    "type": "circle",
    "center": { "x_m": 0.5, "y_m": 0.3 },
    "radius_m": 0.5
  },
  "trigger_level": "level2_warning",
  "active": true
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `object_id` | string | `tw.hazard-zone.{node_id}` |
| `source_node_id` | string | 경보를 발생시킨 센서 노드 |
| `geometry.type` | string | `"circle"` (MVP는 원형만 지원) |
| `geometry.center` | object | 중심 좌표 (물리 좌표계, x/y만 사용) |
| `geometry.radius_m` | number | 반경 (기본값 0.5m, 설정 가능) |
| `trigger_level` | string | HazardZone 생성 기준 등급 (`level2_warning` 이상) |
| `active` | boolean | 현재 활성 여부 |

### 5.2 반경 기본값

기본 반경은 **0.5m**이며, 이는 축소 데모 공간(`demo-local`) 기준 기본값이다.
선박형 표시 좌표(`ship-visual`)에 HazardZone을 렌더링할 때는 중심 좌표와 반경 모두
동일한 비율 매핑을 적용한다. 설정 파일에서 데모 기준 반경과 표시 기준 반경을 분리해
관리할 수 있다.

### 5.3 진입 감지

작업자 위치(x_m, y_m)와 HazardZone 중심 간의 2D 거리가 반경 이내이면 진입으로 판정한다.

```
distance = sqrt((worker_x - center_x)^2 + (worker_y - center_y)^2)
if distance <= radius_m: zone intrusion alert
```

---

## 6. IDW 히트맵 렌더링

> **연산 위치**: IDW 보간은 **프론트엔드(React Three Fiber)**에서 계산한다. 백엔드는 4개 센서 노드의 최신 측정값만 WebSocket으로 전송하며, IDW 가중치 계산(1/distance²)과 surface mesh 생성은 클라이언트 측에서 수행한다. 4개 데이터 포인트의 연산량은 미미하므로 백엔드 부하가 없다.


### 6.1 제한 사항

- 4개 센서가 비슷한 높이에 설치되므로 사실상 2D 평면 데이터
- MVP는 **2D 바닥 평면 Heatmap**으로 제한
- 3D Particle은 시각적 효과로만 사용하고 측정값이라고 표현하지 않음

### 6.2 렌더링 규칙

- Heatmap 색상 범위: 초록(낮음) -> 노랑 -> 주황 -> 빨강(높음)
- 투명도(Alpha)는 농도 추정값에 비례
- 화면 좌측 하단에 레이블 표시: **"Estimated concentration surface based on IDW interpolation"**
- 실제 가스 농도 분포가 아닌 센서 측정값 기반 추정 결과임을 명시

### 6.3 경보와의 분리

- IDW 추정값은 경보 판정에 사용하지 않는다 (ADR-005)
- 경보는 실제 센서 측정값으로만 발생
- IDW Heatmap이 빨간색이어도 해당 위치의 실제 센서가 임계값 미만이면 경보 없음

---

## 7. 데이터 품질 표시

### 7.1 센서 상태 표시

각 3D 마커에 센서 상태를 시각적으로 표시한다.

| 상태 | 표시 | 색상 |
|------|------|------|
| valid + calibrated | 정상 마커 | 위험도에 따른 색상 |
| valid + uncalibrated | "UNCAL" 배지 | 회색 배지 |
| warming_up | "WARM" 배지 | 주황색 배지 |
| error | "ERR" 배지 | 빨간색 배지 |
| offline | 반투명 마커 | 회색 |

### 7.2 위치 품질 표시

웨어러블 아바타에 위치 품질을 시각적으로 표시한다.

| quality_score | 표시 |
|---------------|------|
| >= 0.8 | 정상 아바타 (녹색 테두리) |
| 0.5 ~ 0.8 | "LOW QUALITY" 배지 (노란색) |
| < 0.5 | 반투명 아바타 + "POOR SIGNAL" 배지 (빨간색) |

### 7.3 IDW 품질 표시

- IDW Heatmap 상단에 센서 수 표시: "Interpolation based on 4 sensors"
- 센서 하나라도 오프라인 시: "Interpolation based on 3 sensors (1 offline)"
- 센서 2개 이상 오프라인 시: Heatmap 비활성화, "Insufficient data for interpolation" 표시

---

## 8. Timeline Replay

### 8.1 기능 (SHOULD)

- 특정 시간 범위를 선택하여 과거 상태를 재생
- 재생 속도 조절 (1x, 2x, 5x, 10x)
- 일시정지, 되감기, 빨리감기

### 8.2 데이터 소스

- TimescaleDB에서 해당 시간 범위의 시계열 데이터 조회
- 위치 이력은 5~10Hz 데이터를 보간하여 부드러운 궤적 표시
- 경보 이력은 이벤트 로그에서 조회

---

## 9. 3D 모델 요구사항

### 9.1 모델 형식

- 형식: glTF 2.0 / GLB
- 제작 도구: Blender
- 단위: 1 Three.js unit = 1 meter

### 9.2 필수 요소

| 요소 | 설명 |
|------|------|
| 밀폐공간 외형 | 벽, 바닥, 천장 (반투명 또는 와이어프레임) |
| 출입구 | 개구부 표시 |
| 센서 마커 위치 | 4개 고정 위치 (설정 파일과 일치, Three.js 좌표로 변환 필요) |
| 작업자 아바타 | 간단한 캡슐 또는 구체 |
| 위험 구역 표시 | 반투명 원형 영역 (동적 생성, 기본 반경 0.5m) |

### 9.3 카메라

- 궤도 카메라 (OrbitControls): 회전, 확대, 이동
- 프리셋 뷰: 전체, 탑뷰, 측면
- 작업자 추적 모드: 웨어러블 위치 중심
