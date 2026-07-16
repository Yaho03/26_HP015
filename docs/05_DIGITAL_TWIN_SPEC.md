# DIGITAL TWIN SPEC — 디지털 트윈 사양서

| 항목 | 내용 |
|------|------|
| 문서명 | 디지털 트윈 사양서 |
| 버전 | v2.0 |
| 상태 | 확정 |
| 최종 수정일 | 2026-07-13 |

---

## 1. 디지털 트윈 정의

본 프로젝트의 디지털 트윈은 축소 밀폐공간 모형, 고정 센서 노드, 작업자 웨어러블을 3D 공간 객체로 표현하고, 각 객체의 위치, 센서 상태, 경보 상태를 실시간 데이터와 동기화하는 **모니터링용 디지털 트윈**이다.

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

---

## 3. 좌표계

### 3.1 물리 좌표계 (센서 데이터 / 백엔드 기준)

| 항목 | 정의 |
|------|------|
| 원점 | 모형 왼쪽 전면 바닥 |
| X축 | 모형 가로 방향 (폭) |
| Y축 | 모형 세로 방향 (깊이) |
| Z축 | 높이 방향 (**Z-up**) |
| 단위 | meter |
| 3D 모델 단위 | 1 Three.js unit = 1 meter |
| 좌표계 식별자 | `model-local` |

센서 데이터(`04_DATA_CONTRACT.md`의 `x_m`, `y_m`)와 백엔드에서 처리하는 모든 좌표는 이 물리 좌표계(Z-up)를 기준으로 한다.

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

### 3.4 센서 노드 위치

각 센서 노드의 3D 위치는 고정값이며, 설정 파일에서 관리한다. 아래 좌표는 물리 좌표계(Z-up) 기준이다.

```json
{
  "sensor-01": { "x_m": 0.5, "y_m": 0.3, "z_m": 0.8 },
  "sensor-02": { "x_m": 2.0, "y_m": 0.3, "z_m": 0.8 },
  "sensor-03": { "x_m": 0.5, "y_m": 1.5, "z_m": 0.8 },
  "sensor-04": { "x_m": 2.0, "y_m": 1.5, "z_m": 0.8 }
}
```

> 센서 노드의 (x, y) 위치는 UWB 앵커 위치와 일치해야 한다. z_m은 설치 높이이다. 프론트엔드에서 Three.js 좌표로 변환하여 렌더링한다.

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
    "dimensions": { "width_m": 2.5, "depth_m": 2.0, "height_m": 1.5 },
    "overall_risk_level": "normal"
  },
  "sensor_nodes": [
    {
      "object_id": "tw.sensor-01",
      "physical_id": "sensor-01",
      "position": { "x_m": 0.5, "y_m": 0.3, "z_m": 0.8 },
      "position_coordinate_system": "model-local",
      "latest_values": { "co2_ppm": 612 },
      "alert_level": "normal",
      "connection_status": "online",
      "calibration_status": "uncalibrated"
    }
  ],
  "wearable": {
    "object_id": "tw.wearable-01",
    "physical_id": "wearable-01",
    "position": { "x_m": 1.2, "y_m": 0.8, "z_m": 0.0 },
    "position_coordinate_system": "model-local",
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
| `position` | 물리 좌표계(Z-up) 기준 위치. 프론트엔드에서 Three.js 좌표로 변환 |
| `position_coordinate_system` | 위치 좌표계 식별자 (`model-local`) |
| `location_quality` | 웨어러블 위치 품질 정보 (quality_score, anchor_count, is_filtered) |

> Snapshot의 `position` 필드는 물리 좌표계(Z-up)를 사용한다. `position_coordinate_system: "model-local"`로 명시한다. Three.js 렌더링 시 섹션 3.2의 변환 규칙을 적용한다.

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

모형 크기가 2.5m x 2.0m이므로 과도하게 큰 반경은 모형 전체를 덮는다. 기본 반경은 **0.5m**로 설정하며, 설정 파일에서 변경 가능하다.

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
