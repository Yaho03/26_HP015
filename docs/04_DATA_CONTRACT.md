# DATA CONTRACT — MQTT 데이터 계약

| 항목 | 내용 |
|------|------|
| 문서명 | MQTT 데이터 계약서 |
| 버전 | v1.0 |
| 상태 | 확정 |
| 최종 수정일 | 2026-07-13 |
| 스키마 버전 | 1.0 |

---

## 1. 개요

본 문서는 센서 노드, 웨어러블 노드, 백엔드 서버, 대시보드 간에 MQTT를 통해 교환되는 모든 메시지의 페이로드 구조를 정의한다.

JSON Schema 파일은 `schemas/` 디렉토리에 위치한다.

---

## 2. 공통 Envelope

모든 MQTT 메시지는 다음 공통 Envelope 구조를 따른다.

```json
{
  "schema_version": "1.0",
  "message_id": "01J6X3R8K7VQ2NTP5Z9MA4HWBC",
  "node_id": "sensor-01",
  "sequence": 18321,
  "sampled_at": "2026-07-13T01:20:31.120Z",
  "published_at": "2026-07-13T01:20:31.145Z",
  "quality": {
    "calibrated": false,
    "sensor_status": "warming_up"
  },
  "data": {}
}
```

### 필드 정의

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `schema_version` | string | 예 | 스키마 버전. 현재 "1.0" |
| `message_id` | string | 예 | ULID 형식 고유 메시지 식별자. 중복 메시지 방지에 사용 |
| `node_id` | string | 예 | 송신 노드 식별자 (예: "sensor-01", "wearable-01") |
| `sequence` | integer | 예 | 노드별 증가 시퀀스 번호. 0부터 시작, 32비트 범위 |
| `sampled_at` | string | 예 | 센서 측정 시각 (ISO 8601 UTC, 밀리초 정밀도) |
| `published_at` | string | 예 | MQTT 발행 시각 (ISO 8601 UTC, 밀리초 정밀도) |
| `quality.calibrated` | boolean | 예 | 센서 교정 완료 여부 |
| `quality.sensor_status` | string | 예 | 센서 상태: `warming_up`, `stable`, `error`, `offline` |
| `data` | object | 예 | 토픽별 페이로드 (아래 각 섹션 참조) |

### 시간 규칙

- 모든 타임스탬프는 **UTC**를 사용한다.
- 형식: ISO 8601 (예: `2026-07-13T01:20:31.120Z`)
- 밀리초 정밀도를 유지한다.
- `sampled_at`은 센서에서 값을 읽은 시각이다.
- `published_at`은 ESP32가 MQTT publish를 호출한 시각이다.

### message_id 규칙

- ULID (Universally Unique Lexicographically Sortable Identifier) 형식을 사용한다.
- 26자 base32 인코딩 문자열이다.
- 시간 정렬 가능하며 중복 확률이 극히 낮다.
- 백엔드는 이 값을 기준으로 중복 메시지를 방지한다.

---

## 3. MQTT 토픽 구조

### 3.1 토픽 목록

| 토픽 | 발행 주체 | QoS | Retain | 설명 |
|------|---------|-----|--------|------|
| `sensors/{node_id}/gas` | 센서 노드 | 1 | 아니오 | CO₂, CO, H₂S, MQ-2, BME680 가스저항/IAQ |
| `sensors/{node_id}/env` | 센서 노드 | 1 | 아니오 | 온도, 습도, 기압 |
| `sensors/{node_id}/status` | 센서 노드 | 1 | **예** | 배터리, WiFi RSSI, 업타임, 센서 상태 |
| `wearable/{node_id}/location` | 웨어러블 노드 | 1 | 아니오 | UWB 계산 위치 (x, y, z, 품질) |
| `wearable/{node_id}/imu` | 웨어러블 노드 | 0 | 아니오 | 가속도, 자이로, 낙상 감지 여부 |
| `wearable/{node_id}/vital` | 웨어러블 노드 | 1 | 아니오 | O₂ 농도 |
| `alerts/{node_id}` | 백엔드 서버 | 1 | **예** | 경보 발령/해제 이벤트 |
| `nodes/{node_id}/lwt` | MQTT Broker | 1 | **예** | Last Will and Testament (오프라인 통지) |

### 3.2 QoS 정책

| QoS | 적용 토픽 | 이유 |
|-----|-----------|------|
| 0 (At most once) | IMU 데이터 | 고주기(10Hz), 일부 손실 허용 |
| 1 (At least once) | 가스, 환경, 위치, 상태, 경보, LWT | 데이터 누락 방지 필수 |

### 3.3 Retain 정책

- `sensors/{node_id}/status`: Retain 사용. 새 대시보드 연결 시 최신 상태 즉시 확인.
- `alerts/{node_id}`: Retain 사용. 현재 활성 경보 상태 유지.
- `nodes/{node_id}/lwt`: Retain 사용. 노드 온/오프라인 상태 유지.
- 기타 센서 데이터: Retain 사용 안 함. 실시간 스트림이므로 최신값만 의미.

### 3.4 {node_id} 명명 규칙

| 노드 유형 | node_id 형식 | 예 |
|-----------|-------------|-----|
| 센서 노드 | `sensor-NN` | sensor-01, sensor-02, sensor-03, sensor-04 |
| 웨어러블 노드 | `wearable-NN` | wearable-01 |
| 시뮬레이션 주입 | `sim-NN` | sim-01 (데이터 주입 시 실제 센서와 구분) |

---

## 4. 페이로드 스키마

### 4.1 sensors/{node_id}/gas

> JSON Schema: `schemas/sensor-gas.schema.json`

```json
{
  "data": {
    "co2_ppm": 612,
    "co_raw_adc": 18342,
    "co_voltage_v": 1.724,
    "co_rs_ohm": 13450,
    "co_rs_r0_ratio": 1.42,
    "co_estimated_ppm": null,
    "co_calibration_status": "uncalibrated",
    "h2s_raw_adc": 9821,
    "h2s_voltage_v": 0.913,
    "h2s_rs_ohm": 28000,
    "h2s_rs_r0_ratio": 0.85,
    "h2s_estimated_ppm": null,
    "h2s_calibration_status": "uncalibrated",
    "mq2_raw_adc": 15230,
    "mq2_voltage_v": 1.418,
    "mq2_rs_ohm": 18500,
    "mq2_rs_r0_ratio": 1.12,
    "mq2_estimated_concentration": null,
    "mq2_calibration_status": "uncalibrated",
    "gas_resistance_ohm": 84320,
    "iaq_index": 72,
    "iaq_accuracy": 2
  }
}
```

| 필드 | 타입 | 단위 | 설명 |
|------|------|------|------|
| `co2_ppm` | number | ppm | CO₂ 농도 (MH-Z19B) |
| `co_raw_adc` | integer | — | MQ-7 raw ADC 값 (ADS1115 16-bit) |
| `co_voltage_v` | number | V | MQ-7 분압 후 전압 |
| `co_rs_ohm` | number | Ω | MQ-7 센서 저항 |
| `co_rs_r0_ratio` | number | — | MQ-7 Rs/R0 비율 |
| `co_estimated_ppm` | number\|null | ppm | 교정 전 null |
| `co_calibration_status` | enum | — | `uncalibrated`, `calibrating`, `calibrated` |
| `h2s_*` | — | — | MQ-136 H₂S (CO와 동일 구조) |
| `mq2_*` | — | — | MQ-2 가연성 가스 (estimated_concentration 사용, ppm/LEL% 아님) |
| `gas_resistance_ohm` | number | Ω | BME680 가스 저항 |
| `iaq_index` | number | — | BME680 BSEC IAQ 지수 |
| `iaq_accuracy` | integer | — | BME680 BSEC 정확도 (0-3) |

> BME680은 `voc_ppm` 필드를 사용하지 않는다. (`08_SAFETY_AND_LIMITATIONS.md` 참조)
>
> MQ 센서는 교정 전까지 `estimated_ppm` 또는 `estimated_concentration`이 null이다.

### 4.2 sensors/{node_id}/env

> JSON Schema: `schemas/sensor-env.schema.json`

```json
{
  "data": {
    "temperature_c": 24.5,
    "humidity_pct": 55.2,
    "pressure_hpa": 1013.25
  }
}
```

| 필드 | 타입 | 단위 | 설명 |
|------|------|------|------|
| `temperature_c` | number | °C | 온도 (BME680) |
| `humidity_pct` | number | % | 습도 (BME680) |
| `pressure_hpa` | number | hPa | 기압 (BME680) |

### 4.3 sensors/{node_id}/status

```json
{
  "data": {
    "battery_pct": 78,
    "wifi_rssi_dbm": -52,
    "uptime_s": 3600,
    "free_heap_bytes": 182344,
    "sensors_online": ["mh-z19b", "bme680", "mq-7", "mq-136", "mq-2", "ads1115", "dwm1000"],
    "sensors_error": []
  }
}
```

### 4.4 wearable/{node_id}/location

> JSON Schema: `schemas/wearable-location.schema.json`

```json
{
  "data": {
    "x_m": 2.41,
    "y_m": 1.32,
    "z_m": 0.0,
    "coordinate_system": "model-local",
    "method": "ds_twr",
    "anchor_count": 4,
    "quality_score": 0.87,
    "is_filtered": true
  }
}
```

| 필드 | 타입 | 단위 | 설명 |
|------|------|------|------|
| `x_m` | number | meter | X 축 위치 (UWB 측정값) |
| `y_m` | number | meter | Y 축 위치 (UWB 측정값) |
| `z_m` | number | meter | **항상 0.0** (2D 측위, 3D 렌더링용 고정값) |
| `coordinate_system` | enum | — | `model-local` |
| `method` | enum | — | `ds_twr` |
| `anchor_count` | integer | — | 위치 계산에 사용된 앵커 수 |
| `quality_score` | number | — | 위치 품질 점수 (0.0~1.0) |
| `is_filtered` | boolean | — | 필터(EMA/Kalman) 적용 여부 |

> `z_m`은 UWB가 측정한 값이 아니라 렌더링용 고정 좌표이다. 2D 측위 결과를 3D 바닥 높이에 매핑한다.

### 4.5 wearable/{node_id}/imu

```json
{
  "data": {
    "accel_x_g": 0.01,
    "accel_y_g": -0.02,
    "accel_z_g": 0.98,
    "accel_magnitude_g": 0.98,
    "gyro_x_dps": 0.5,
    "gyro_y_dps": -1.2,
    "gyro_z_dps": 0.3,
    "fall_detected": false
  }
}
```

### 4.6 wearable/{node_id}/vital

```json
{
  "data": {
    "o2_pct": 20.9
  }
}
```

| 필드 | 타입 | 단위 | 설명 |
|------|------|------|------|
| `o2_pct` | number | % | O₂ 농도 (SEN0322, 작업자 주변 공기) |

> SEN0322 응답 시간은 최대 15초이다. 급격한 O₂ 변화에 대한 즉각 탐지는 보장하지 않는다.

### 4.7 alerts/{node_id}

> JSON Schema: `schemas/alert.schema.json`

이 메시지는 백엔드 서버가 발행한다.

```json
{
  "schema_version": "1.0",
  "message_id": "01J6X3RAL9VQ2NTP5Z9MA4HWDE",
  "node_id": "sensor-01",
  "sequence": 1,
  "sampled_at": "2026-07-13T01:20:31.120Z",
  "published_at": "2026-07-13T01:20:33.080Z",
  "quality": {
    "calibrated": false,
    "sensor_status": "stable"
  },
  "data": {
    "alert_id": "01J6X3RAM0VQ2NTP5Z9MA4HWFG",
    "source_node_id": "sensor-01",
    "alert_type": "gas_threshold",
    "level": "level2_warning",
    "trigger_value": 2350.0,
    "threshold": 2000.0,
    "metric": "co2_ppm",
    "message": "CO₂ 농도 경고: 2,350 ppm (임계값 2,000 ppm 초과)",
    "status": "active",
    "activated_at": "2026-07-13T01:20:31.120Z",
    "resolved_at": null
  }
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `alert_id` | string | ULID 형식 경보 식별자 |
| `source_node_id` | string | 경보 발생 노드 |
| `alert_type` | enum | `gas_threshold`, `fall_detection`, `o2_low`, `zone_intrusion`, `connection_lost` |
| `level` | enum | `level1_caution`, `level2_warning`, `level3_critical` |
| `trigger_value` | number\|null | 경보를 발생시킨 측정값 |
| `threshold` | number\|null | 초과된 임계값 |
| `metric` | string\|null | 측정 항목 (예: "co2_ppm", "o2_pct") |
| `message` | string | 사람이 읽을 수 있는 경보 메시지 |
| `status` | enum | `active`, `acknowledged`, `resolved` |
| `activated_at` | string | 경보 발생 시각 (UTC) |
| `resolved_at` | string\|null | 경보 해제 시각 (해제 시에만) |

---

## 5. MQTT 프로토콜 정책

### 5.1 Last Will and Testament (LWT)

각 노드는 연결 시 LWT 메시지를 등록한다.

- 토픽: `nodes/{node_id}/lwt`
- 페이로드:
  ```json
  {
    "node_id": "sensor-01",
    "status": "offline",
    "timestamp": "2026-07-13T01:20:31.120Z"
  }
  ```
- Retain: 예
- QoS: 1

노드는 연결 성공 직후 동일 토픽에 `status: "online"` 메시지를 발행한다.

### 5.2 오프라인 판정

백엔드는 다음 조건 중 하나로 노드를 오프라인으로 판정한다.

1. LWT 메시지 수신 (`status: "offline"`)
2. 30초 이상 데이터 수신 없음 (status 토픽 기준)

오프라인 판정 시 해당 노드의 대시보드 표시를 "OFFLINE"으로 변경하고, 필요 시 `connection_lost` 경보를 발행한다.

### 5.3 중복 메시지 처리

- 백엔드는 `message_id`를 기준으로 중복 메시지를 식별한다.
- 동일 `message_id`가 수신된 경우 두 번째 메시지는 저장하지 않는다.
- `sequence` 번호는 순서 검증에 사용한다.

### 5.4 순서 보장

- MQTT QoS 1은 메시지 도달을 보장하지만 순서를 보장하지 않는다.
- 백엔드는 `sampled_at` 타임스탬프를 기준으로 데이터를 정렬하여 처리한다.
- `sequence` 번호가 감소하는 경우 로그에 경고를 기록한다.

### 5.5 스키마 버전 관리

- `schema_version`이 변경될 경우, 백엔드는 하위 호환성을 유지한다.
- 새 필드 추가는 기존 소비자에 영향을 주지 않는다 (additionalProperties 정책).
- 필드 제거 또는 타입 변경은 새 major 버전이 필요하다.

---

## 6. 좌표계 정의

| 항목 | 정의 |
|------|------|
| 원점 | 모형 왼쪽 전면 바닥 |
| X축 | 모형 가로 방향 (폭) |
| Y축 | 모형 세로 방향 (깊이) |
| Z축 | 높이 방향 |
| 단위 | meter |
| 3D 모델 단위 | 1 Three.js unit = 1 meter |
| 좌표계 식별자 | `model-local` |

> 상세한 디지털 트윈 좌표계 매핑은 `05_DIGITAL_TWIN_SPEC.md`를 참조한다.

---

## 7. 단위 규칙

모든 데이터 필드의 단위는 필드 이름에 접미사로 포함한다.

| 접미사 | 단위 | 예 |
|--------|------|-----|
| `_ppm` | parts per million | `co2_ppm` |
| `_pct` | percent | `humidity_pct`, `o2_pct` |
| `_c` | Celsius | `temperature_c` |
| `_hpa` | hectopascal | `pressure_hpa` |
| `_ohm` | ohm | `gas_resistance_ohm`, `rs_ohm` |
| `_v` | volt | `voltage_v` |
| `_g` | g-force | `accel_z_g` |
| `_dps` | degrees per second | `gyro_x_dps` |
| `_m` | meter | `x_m`, `y_m` |
| `_dbm` | decibel-milliwatts | `wifi_rssi_dbm` |
| `_s` | second | `uptime_s` |
| `_bytes` | bytes | `free_heap_bytes` |
