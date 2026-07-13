# DIGITAL TWIN SPEC — 디지털 트윈 사양서

| 항목 | 내용 |
|------|------|
| 문서명 | 디지털 트윈 사양서 |
| 버전 | v1.0 |
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
| **Wearable** | 작업자 ID, 장착 센서 목록 | 위치(x,y), O₂, 낙상 여부, 배터리 |
| **HazardZone** | 공간 범위, 발생 규칙 | 활성 여부, 위험 등급 |
| **Alert** | 경보 종류, 기준 | 발생, 확인, 해제 상태 |

### 2.2 Physical ID와 3D Object ID 매핑

| Physical ID (node_id) | 3D Object ID | 객체 유형 |
|----------------------|--------------|-----------|
| sensor-01 | tw.sensor-01 | SensorNode |
| sensor-02 | tw.sensor-02 | SensorNode |
| sensor-03 | tw.sensor-03 | SensorNode |
| sensor-04 | tw.sensor-04 | SensorNode |
| wearable-01 | tw.wearable-01 | Wearable |

- 시뮬레이션 데이터 주입 시: `sim-01` -> `tw.sim-01`
- 3D 객체 ID는 접두사 `tw.`를 사용한다
- 백엔드 WebSocket 메시지에 physical_id와 object_id를 모두 포함한다

---

## 3. 좌표계

### 3.1 정의

| 항목 | 정의 |
|------|------|
| 원점 | 모형 왼쪽 전면 바닥 |
| X축 | 모형 가로 방향 (폭) |
| Y축 | 모형 세로 방향 (깊이) |
| Z축 | 높이 방향 |
| 단위 | meter |
| 3D 모델 단위 | 1 Three.js unit = 1 meter |
| 좌표계 식별자 | `model-local` |

### 3.2 UWB 좌표에서 3D 좌표로 변환

UWB 측위 결과는 2D (x, y)이다. 3D 렌더링 시 z축은 고정값으로 매핑한다.

```
3D position:
  x_3d = x_uwb
  y_3d = y_uwb
  z_3d = FIXED_FLOOR_HEIGHT  // 기본값 0.0, 설정 가능
```

### 3.3 센서 노드 위치

각 센서 노드의 3D 위치는 고정값이며, 설정 파일에서 관리한다.

```json
{
  "sensor-01": { "x_m": 0.5, "y_m": 0.3, "z_m": 0.8 },
  "sensor-02": { "x_m": 2.0, "y_m": 0.3, "z_m": 0.8 },
  "sensor-03": { "x_m": 0.5, "y_m": 1.5, "z_m": 0.8 },
  "sensor-04": { "x_m": 2.0, "y_m": 1.5, "z_m": 0.8 }
}
```

> 센서 노드의 (x, y) 위치는 UWB 앵커 위치와 일치해야 한다. z_m은 설치 높이이다.

---

## 4. 동기화 규칙

### 4.1 실시간 Delta 업데이트

백엔드는 WebSocket을 통해 상태 변화를 실시간으로 푸시한다.

```json
{
  "type": "delta",
  "object_id": "tw.sensor-01",
  "physical_id": "sensor-01",
  "timestamp": "2026-07-13T01:20:31.120Z",
  "changes": {
    "co2_ppm": 612,
    "alert_level": "normal"
  }
}
```

### 4.2 전체 Snapshot

대시보드 초기 연결 또는 WebSocket 재연결 시 전체 상태 Snapshot이 전송된다.

```json
{
  "type": "snapshot",
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
    "o2_pct": 20.9,
    "fall_detected": false,
    "battery_pct": 78
  },
  "active_alerts": [],
  "hazard_zones": []
}
```

### 4.3 WebSocket 재연결 복구

1. WebSocket 연결 끊김 감지
2. 자동 재연결 시도 (지수 백오프: 1s, 2s, 4s, 8s, 최대 30s)
3. 재연결 성공 시 `type: "snapshot"` 요청
4. 백엔드가 현재 전체 상태 Snapshot을 응답
5. Zustand Store를 Snapshot으로 교체
6. 이후 Delta 업데이트 재개

---

## 5. IDW 히트맵 렌더링

### 5.1 제한 사항

- 4개 센서가 비슷한 높이에 설치되므로 사실상 2D 평면 데이터
- MVP는 **2D 바닥 평면 Heatmap**으로 제한
- 3D Particle은 시각적 효과로만 사용하고 측정값이라고 표현하지 않음

### 5.2 렌더링 규칙

- Heatmap 색상 범위: 초록(낮음) → 노랑 → 주황 → 빨강(높음)
- 투명도(Alpha)는 농도 추정값에 비례
- 화면 좌측 하단에 레이블 표시: **"Estimated concentration surface based on IDW interpolation"**
- 실제 가스 농도 분포가 아닌 센서 측정값 기반 추정 결과임을 명시

### 5.3 경보와의 분리

- IDW 추정값은 경보 판정에 사용하지 않는다 (ADR-005)
- 경보는 실제 센서 측정값으로만 발생
- IDW Heatmap이 빨간색이어도 해당 위치의 실제 센서가 임계값 미만이면 경보 없음

---

## 6. 데이터 품질 표시

### 6.1 센서 상태 표시

각 3D 마커에 센서 상태를 시각적으로 표시한다.

| 상태 | 표시 | 색상 |
|------|------|------|
| stable + calibrated | 정상 마커 | 위험도에 따른 색상 |
| stable + uncalibrated | "UNCAL" 배지 | 회색 배지 |
| warming_up | "WARM" 배지 | 주황색 배지 |
| error | "ERR" 배지 | 빨간색 배지 |
| offline | 반투명 마커 | 회색 |

### 6.2 IDW 품질 표시

- IDW Heatmap 상단에 센서 수 표시: "Interpolation based on 4 sensors"
- 센서 하나라도 오프라인 시: "Interpolation based on 3 sensors (1 offline)"
- 센서 2개 이상 오프라인 시: Heatmap 비활성화, "Insufficient data for interpolation" 표시

---

## 7. Timeline Replay

### 7.1 기능 (SHOULD)

- 특정 시간 범위를 선택하여 과거 상태를 재생
- 재생 속도 조절 (1x, 2x, 5x, 10x)
- 일시정지, 되감기, 빨리감기

### 7.2 데이터 소스

- TimescaleDB에서 해당 시간 범위의 시계열 데이터 조회
- 위치 이력은 5~10Hz 데이터를 보간하여 부드러운 궤적 표시
- 경보 이력은 이벤트 로그에서 조회

---

## 8. 3D 모델 요구사항

### 8.1 모델 형식

- 형식: glTF 2.0 / GLB
- 제작 도구: Blender
- 단위: 1 Three.js unit = 1 meter

### 8.2 필수 요소

| 요소 | 설명 |
|------|------|
| 밀폐공간 외형 | 벽, 바닥, 천장 (반투명 또는 와이어프레임) |
| 출입구 | 개구부 표시 |
| 센서 마커 위치 | 4개 고정 위치 (설정 파일과 일치) |
| 작업자 아바타 | 간단한 캡슐 또는 구체 |
| 위험 구역 표시 | 반투명 영역 (동적 생성) |

### 8.3 카메라

- 궤도 카메라 (OrbitControls): 회전, 확대, 이동
- 프리셋 뷰: 전체, 탑뷰, 측면
- 작업자 추적 모드: 웨어러블 위치 중심
