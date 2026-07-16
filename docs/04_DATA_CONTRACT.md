# DATA CONTRACT — MQTT 데이터 계약

| 항목 | 내용 |
|------|------|
| 문서명 | MQTT 데이터 계약서 |
| 버전 | v2.0 |
| 상태 | 확정 |
| 최종 수정일 | 2026-07-13 |
| 스키마 버전 | 1.1 |

---

## 1. 개요

본 문서는 센서 노드, 웨어러블 노드, 백엔드 서버, 대시보드 간에 MQTT를 통해 교환되는 모든 메시지의 페이로드 구조를 정의한다.

JSON Schema 파일은 `schemas/` 디렉토리에 위치한다.

---

## 2. 공통 Envelope (v1.1)

모든 센서/웨어러블 **telemetry** 메시지는 다음 공통 Envelope 구조를 따른다.

> LWT(Connection State) 메시지와 Alert 메시지는 별도 페이로드 구조를 사용한다 (섹션 5, 6 참조).

```json
{
  "schema_version": "1.1",
  "message_id": "01J6X3R8K7VQ2NTP5Z9MA4HWBC",
  "node_id": "sensor-01",
  "boot_id": "01J6X3R8K7VQ2NTP5Z9MA4HWBD",
  "sequence": 18321,
  "sampled_at": "2026-07-13T01:20:31.120Z",
  "published_at": "2026-07-13T01:20:31.145Z",
  "source_mode": "live",
  "simulation": null,
  "quality": {
    "message_status": "complete",
    "time_synced": true,
    "sensors": {
      "mh-z19b": "valid",
      "mq-7": "uncalibrated",
      "mq-136": "uncalibrated",
      "mq-2": "uncalibrated",
      "bme680": "valid",
      "ads1115": "valid"
    }
  },
  "data": {}
}
```

### 필드 정의

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `schema_version` | string | 예 | 스키마 버전. 현재 "1.1" |
| `message_id` | string | 예 | ULID 형식 고유 메시지 식별자. 중복 메시지 방지에 사용 |
| `node_id` | string | 예 | 송신 노드 식별자 (예: "sensor-01", "wearable-01") |
| `boot_id` | string | 예 | ULID 형식 부팅 식별자. 노드 재부팅 시 새로 할당. 펌웨어 재시작 추적에 사용 |
| `sequence` | integer | 예 | 노드별 증가 시퀀스 번호. 0부터 시작, 32비트 범위 |
| `sampled_at` | string | 예 | 센서 측정 시각 (ISO 8601 UTC, 밀리초 정밀도) |
| `published_at` | string | 예 | MQTT 발행 시각 (ISO 8601 UTC, 밀리초 정밀도) |
| `source_mode` | enum | 예 | `live` (실제 센서) 또는 `simulation` (데이터 주입) |
| `simulation` | object\|null | 예 | 시뮬레이션 메타데이터. `source_mode: "live"`인 경우 `null` |
| `quality` | object | 예 | 데이터 품질 정보 (하위 필드 참조) |
| `data` | object | 예 | 토픽별 페이로드 (아래 각 섹션 참조) |

### source_mode 및 simulation 필드

| 필드 | 타입 | 설명 |
|------|------|------|
| `source_mode` | enum | `"live"` = 실제 센서 데이터, `"simulation"` = 소프트웨어 주입 데이터 |
| `simulation.run_id` | string | 시뮬레이션 실행 식별자 (예: "demo-20260713-01") |
| `simulation.scenario_id` | string | 시나리오 식별자 (예: "co2_warning", "o2_low") |

> 시뮬레이션 데이터 주입 시 `node_id`는 실제 물리 노드 ID를 그대로 사용한다 (예: `sensor-01`). 별도의 `sim-NN` prefix를 사용하지 않는다. 대시보드는 `source_mode: "simulation"` 필드로 실제/시뮬레이션을 구분한다.

### quality 필드 정의

| 필드 | 타입 | 설명 |
|------|------|------|
| `quality.message_status` | enum | `complete` (모든 센서 정상), `partial` (일부 센서 오류), `degraded` (주요 센서 오류) |
| `quality.time_synced` | boolean | NTP 시간 동기화 완료 여부 |
| `quality.sensors` | object | 센서별 상태 맵. 키는 센서 식별자, 값은 상태 enum |

`quality.sensors` 값:

| 값 | 의미 |
|----|------|
| `valid` | 정상 측정 중 |
| `warming_up` | 예열 중 (MQ 센서 30초 이내) |
| `uncalibrated` | 교정 미완료 (raw 값만 유효) |
| `error` | 센서 오류 |
| `not_connected` | 센서 미연결 |

### 시간 규칙

- 모든 타임스탬프는 **UTC**를 사용한다.
- 형식: ISO 8601 (예: `2026-07-13T01:20:31.120Z`)
- 밀리초 정밀도를 유지한다.
- `sampled_at`은 센서에서 값을 읽은 시각이다.
- `published_at`은 ESP32가 MQTT publish를 호출한 시각이다.
- `backend_received_at`은 백엔드 서버가 MQTT 메시지를 수신한 시각이다 (백엔드에서 기록, MQTT broker가 자동 추가하지 않음).

### message_id 규칙

- ULID (Universally Unique Lexicographically Sortable Identifier) 형식을 사용한다.
- 26자 Crockford Base32 인코딩 문자열이다.
- 정규식: `^[0-7][0-9A-HJKMNP-TV-Z]{25}$`
- 시간 정렬 가능하며 중복 확률이 극히 낮다.
- 백엔드는 이 값을 기준으로 중복 메시지를 방지한다.

### boot_id 규칙

- ULID 형식이다 (message_id와 동일한 정규식).
- 노드가 부팅할 때마다 새 boot_id를 생성한다.
- 백엔드는 boot_id 변화를 감지하여 노드 재시작 이벤트를 기록한다.
- sequence 번호는 boot_id 단위로 0부터 리셋된다.

---

## 3. MQTT 토픽 구조

### 3.1 토픽 목록

| 토픽 | 발행 주체 | QoS | Retain | 스키마 | 설명 |
|------|---------|-----|--------|--------|------|
| `sensors/{node_id}/gas` | 센서 노드 | 1 | 아니오 | sensor-gas.schema.json | CO2, CO, H2S, MQ-2, BME680 가스저항/IAQ |
| `sensors/{node_id}/env` | 센서 노드 | 1 | 아니오 | sensor-env.schema.json | 온도, 습도, 기압 |
| `sensors/{node_id}/status` | 센서 노드 | 1 | **예** | sensor-status.schema.json | 배터리, WiFi RSSI, 업타임, 센서 상태 |
| `wearable/{node_id}/location` | 웨어러블 노드 | 1 | 아니오 | wearable-location.schema.json | UWB 계산 위치 (x, y, z, 품질) |
| `wearable/{node_id}/imu` | 웨어러블 노드 | 0 | 아니오 | wearable-imu.schema.json | 가속도, 자이로, 낙상 감지 여부 |
| `wearable/{node_id}/vital` | 웨어러블 노드 | 1 | 아니오 | wearable-vital.schema.json | O2 농도 |
| `alerts/events/{node_id}` | 백엔드 서버 | 1 | 아니오 | alert-event.schema.json | 경보 발령/해제 이벤트 (개별 이벤트 스트림) |
| `alerts/state/{node_id}/{alert_key}` | 백엔드 서버 | 1 | **예** | alert-event.schema.json | 현재 활성 경보 상태 (alert_key별 유지) |
| `nodes/{node_id}/connection` | 노드 / Broker | 1 | **예** | node-connection.schema.json | 연결 상태 (LWT + online/offline) |

### 3.2 QoS 정책

| QoS | 적용 토픽 | 이유 |
|-----|-----------|------|
| 0 (At most once) | IMU 데이터 | 고주기(10Hz), 일부 손실 허용 |
| 1 (At least once) | 가스, 환경, 위치, 상태, 경보, 연결 상태 | 데이터 누락 방지 필수 |

### 3.3 Retain 정책

- `sensors/{node_id}/status`: Retain 사용. 새 대시보드 연결 시 최신 상태 즉시 확인.
- `alerts/state/{node_id}/{alert_key}`: Retain 사용. alert_key별 활성 경보 상태 유지.
- `nodes/{node_id}/connection`: Retain 사용. 노드 온/오프라인 상태 유지.
- `alerts/events/{node_id}`: Retain 사용 안 함. 이벤트 스트림이므로 과거 이벤트는 DB에서 조회.
- 기타 센서 데이터: Retain 사용 안 함. 실시간 스트림이므로 최신값만 의미.

### 3.4 Alert 토픽 구조 (다중 경보 지원)

단일 `alerts/{node_id}` Retain 토픽은 동시 다중 경보 시 마지막 메시지가 이전 경보를 덮어쓰는 문제가 있다. 이를 해결하기 위해 두 개의 토픽으로 분리한다.

**1. 이벤트 토픽: `alerts/events/{node_id}`**

- Retain: 아니오
- 경보 발생(`status: "active"`) 및 해제(`status: "resolved"`) 이벤트를 순차적으로 발행
- 대시보드는 이 토픽을 구독하여 실시간 경보 알림을 수신
- 모든 이벤트는 DB에 영구 저장

**2. 상태 토픽: `alerts/state/{node_id}/{alert_key}`**

- Retain: 예
- `{alert_key}`는 경보를 고유하게 식별하는 키 (예: `co2_ppm`, `o2_low`, `fall_detection`, `zone_intrusion`)
- 활성 경보 시 해당 alert_key의 Retain 메시지를 경보 상태로 설정
- 경보 해제 시 해당 alert_key의 Retain 메시지를 `status: "resolved"`로 업데이트
- 대시보드 재연결 시 모든 alert_key의 Retain 메시지를 읽어 현재 활성 경보 목록을 복구

**alert_key 명명 규칙:**

| alert_key | 설명 |
|-----------|------|
| `co2_ppm` | CO2 농도 경보 |
| `co_ppm` | CO 농도 경보 (교정 후) |
| `h2s_ppm` | H2S 농도 경보 (교정 후) |
| `temperature_c` | 온도 경보 |
| `o2_low` | O2 저농도 경보 |
| `o2_high` | O2 고농도 경보 |
| `fall_detection` | 낙상 감지 경보 |
| `zone_intrusion` | 위험 구역 진입 경보 |
| `connection_lost` | 노드 연결 끊김 경보 |

### 3.5 {node_id} 명명 규칙

| 노드 유형 | node_id 형식 | 예 |
|-----------|-------------|-----|
| 센서 노드 | `sensor-NN` | sensor-01, sensor-02, sensor-03, sensor-04 |
| 웨어러블 노드 | `wearable-NN` | wearable-01 |

> 시뮬레이션 데이터 주입 시에도 실제 node_id를 그대로 사용하며, `source_mode: "simulation"` 필드로 구분한다. `sim-NN` prefix는 사용하지 않는다.

> **웨어러블 경보 구독**: 웨어러블 노드는 `alerts/events/+` (와일드카드)를 구독하여 모든 센서 노드의 환경 경보를 수신한다. 자기 자신의 `wearable-NN` 경보(낙상 등)뿐 아니라 sensor-01~04의 가스/O₂ 경보에도 진동으로 반응해야 하기 때문이다. 단, O₂ 저농도는 로컬 폴백 경보(`06_ALERT_RULES.md` 섹션 12)로도 동작한다.

> **백엔드 재시작 시 경보 상태 복구**: 백엔드는 시작 시 `alerts/state/#` Retain 메시지를 모두 읽어 활성 경보 상태를 복구한다. 경보 타이머(enter_for_ms)는 복구된 경보에 대해 리셋하지 않고, 이미 active인 경보는 그대로 유지한다. 백엔드 재시작 자체를 `connection_lost` 이벤트로 대시보드에 알린다.


---

## 4. Telemetry 페이로드 스키마

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
| `co2_ppm` | number | ppm | CO2 농도 (MH-Z19B) |
| `co_raw_adc` | integer | — | MQ-7 raw ADC 값 (ADS1115 16-bit) |
| `co_voltage_v` | number | V | MQ-7 분압 후 전압 |
| `co_rs_ohm` | number | Ohm | MQ-7 센서 저항 |
| `co_rs_r0_ratio` | number | — | MQ-7 Rs/R0 비율 |
| `co_estimated_ppm` | number\|null | ppm | 교정 전 null |
| `co_calibration_status` | enum | — | `uncalibrated`, `calibrating`, `calibrated` |
| `h2s_*` | — | — | MQ-136 H2S (CO와 동일 구조) |
| `mq2_*` | — | — | MQ-2 가연성 가스 (estimated_concentration 사용, ppm/LEL% 아님) |
| `gas_resistance_ohm` | number | Ohm | BME680 가스 저항 |
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
| `temperature_c` | number | Celsius | 온도 (BME680) |
| `humidity_pct` | number | % | 습도 (BME680) |
| `pressure_hpa` | number | hPa | 기압 (BME680) |

### 4.3 sensors/{node_id}/status

> JSON Schema: `schemas/sensor-status.schema.json`

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
| `x_m` | number | meter | X 축 위치 (물리 좌표계, UWB 측정값) |
| `y_m` | number | meter | Y 축 위치 (물리 좌표계, UWB 측정값) |
| `z_m` | number | meter | **항상 0.0** (2D 측위, 3D 렌더링용 고정값) |
| `coordinate_system` | enum | — | `model-local` (물리 좌표계) |
| `method` | enum | — | `ds_twr` |
| `anchor_count` | integer | — | 위치 계산에 사용된 앵커 수 |
| `quality_score` | number | — | 위치 품질 점수 (0.0~1.0) |
| `is_filtered` | boolean | — | 필터(EMA/Kalman) 적용 여부 |

> `x_m`, `y_m`은 **물리 좌표계(Z-up)** 기준이다. Three.js 렌더링 시 좌표 변환이 필요하다 (`05_DIGITAL_TWIN_SPEC.md` 섹션 3 참조).
>
> `z_m`은 UWB가 측정한 값이 아니라 렌더링용 고정 좌표이다. 2D 측위 결과를 3D 바닥 높이에 매핑한다.

### 4.5 wearable/{node_id}/imu

> JSON Schema: `schemas/wearable-imu.schema.json`

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

> JSON Schema: `schemas/wearable-vital.schema.json`

```json
{
  "data": {
    "o2_pct": 20.9
  }
}
```

| 필드 | 타입 | 단위 | 설명 |
|------|------|------|------|
| `o2_pct` | number | % | O2 농도 (SEN0322, 작업자 주변 공기) |

> SEN0322 응답 시간은 최대 15초이다. 급격한 O2 변화에 대한 즉각 탐지는 보장하지 않는다.

---

## 5. Connection State 페이로드 (LWT)

> JSON Schema: `schemas/node-connection.schema.json`

LWT 메시지는 공통 Envelope 구조를 따르지 않는다. 연결 상태 전용 페이로드를 사용한다.

### 5.1 Last Will and Testament (LWT)

각 노드는 연결 시 LWT 메시지를 등록한다.

- 토픽: `nodes/{node_id}/connection`
- Retain: 예
- QoS: 1

**오프라인 메시지 (LWT, Broker가 발행):**

```json
{
  "schema_version": "1.1",
  "node_id": "sensor-01",
  "status": "offline",
  "reason": "lwt",
  "boot_id": "01J6X3R8K7VQ2NTP5Z9MA4HWBD",
  "timestamp": "2026-07-13T01:20:31.120Z"
}
```

**온라인 메시지 (노드가 연결 성공 직후 발행):**

```json
{
  "schema_version": "1.1",
  "node_id": "sensor-01",
  "status": "online",
  "reason": "connect",
  "boot_id": "01J6X3R8K7VQ2NTP5Z9MA4HWBD",
  "timestamp": "2026-07-13T01:20:31.120Z"
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `schema_version` | string | "1.1" |
| `node_id` | string | 노드 식별자 |
| `status` | enum | `online`, `offline` |
| `reason` | enum | `connect` (정상 접속), `lwt` (Will 메시지), `timeout` (데이터 수신 시간 초과) |
| `boot_id` | string | ULID 형식 부팅 식별자 |
| `timestamp` | string | 상태 변화 시각 (UTC) |

> LWT 페이로드는 `message_id`, `sequence`, `sampled_at`, `quality` 등 telemetry 전용 필드를 포함하지 않는다. 연결 상태 정보만 전달한다.

### 5.2 오프라인 판정

백엔드는 다음 조건 중 하나로 노드를 오프라인으로 판정한다.

1. LWT 메시지 수신 (`status: "offline"`, `reason: "lwt"`)
2. 30초 이상 데이터 수신 없음 (status 토픽 기준) → 백엔드가 `reason: "timeout"`으로 오프라인 판정

오프라인 판정 시 해당 노드의 대시보드 표시를 "OFFLINE"으로 변경하고, 필요 시 `connection_lost` 경보를 발행한다.

---

## 6. Alert 이벤트 페이로드

> JSON Schema: `schemas/alert-event.schema.json`

이 메시지는 백엔드 서버가 발행한다.

```json
{
  "schema_version": "1.1",
  "message_id": "01J6X3RAL9VQ2NTP5Z9MA4HWDE",
  "alert_id": "01J6X3RAM0VQ2NTP5Z9MA4HWFG",
  "source_node_id": "sensor-01",
  "alert_key": "co2_ppm",
  "alert_type": "gas_threshold",
  "level": "level2_warning",
  "trigger_value": 2350.0,
  "threshold": 2000.0,
  "metric": "co2_ppm",
  "message": "CO2 농도 경고: 2,350 ppm (임계값 2,000 ppm 초과)",
  "status": "active",
  "activated_at": "2026-07-13T01:20:31.120Z",
  "resolved_at": null,
  "published_at": "2026-07-13T01:20:33.080Z"
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `schema_version` | string | "1.1" |
| `message_id` | string | ULID 형식 메시지 식별자 |
| `alert_id` | string | ULID 형식 경보 식별자 |
| `source_node_id` | string | 경보 발생 노드 |
| `alert_key` | string | 경보 키 (Retain 토픽의 `{alert_key}`와 일치) |
| `alert_type` | enum | `gas_threshold`, `fall_detection`, `o2_low`, `o2_high`, `zone_intrusion`, `connection_lost` |
| `level` | enum | `level1_caution`, `level2_warning`, `level3_critical` |
| `trigger_value` | number\|null | 경보를 발생시킨 측정값 |
| `threshold` | number\|null | 초과된 임계값 |
| `metric` | string\|null | 측정 항목 (예: "co2_ppm", "o2_pct") |
| `message` | string | 사람이 읽을 수 있는 경보 메시지 |
| `status` | enum | `active`, `resolved` |
| `activated_at` | string | 경보 발생 시각 (UTC) |
| `resolved_at` | string\|null | 경보 해제 시각 (해제 시에만) |
| `published_at` | string | 서버 발행 시각 (UTC) |

> Alert 페이로드는 telemetry Envelope과 다른 구조를 사용한다. 이유: alert는 서버가 생성하는 이벤트이므로 센서 수준의 quality, boot_id, sequence가 의미를 갖지 않는다.

---

## 7. MQTT 프로토콜 정책

### 7.1 중복 메시지 처리

- 백엔드는 `message_id`를 기준으로 중복 메시지를 식별한다.
- 동일 `message_id`가 수신된 경우 두 번째 메시지는 저장하지 않는다.
- `sequence` 번호는 순서 검증에 사용한다.

### 7.2 순서 보장

- MQTT QoS 1은 메시지 도달을 보장하지만 순서를 보장하지 않는다.
- 백엔드는 `sampled_at` 타임스탬프를 기준으로 데이터를 정렬하여 처리한다.
- `sequence` 번호가 감소하는 경우 로그에 경고를 기록한다.

### 7.3 스키마 버전 관리

본 프로젝트의 모든 JSON Schema는 `additionalProperties: false`를 적용한다. 이는 안전 필수 시스템에서 예상치 못한 필드로 인한 파싱 오류를 방지하기 위함이다.

> 예외: `twin-delta.schema.json`의 `changes`, `twin-snapshot.schema.json`의 `latest_values`, `active_alerts` 항목은 동적 키-값 객체이므로 `additionalProperties: true`를 허용한다. 이는 상태 델타/스냅샷의 유연성을 위한 것이며, 나머지 모든 객체는 `additionalProperties: false`를 적용한다.

**버전 정책:**

| 변경 유형 | 버전 변경 | 호환성 |
|-----------|-----------|--------|
| 새 필드 추가 | minor 버전업 (예: 1.0 → 1.1) | 소비자 코드 업데이트 필요 |
| 필드 제거 | major 버전업 (예: 1.x → 2.0) | 소비자 코드 업데이트 필수 |
| 필드 타입 변경 | major 버전업 | 소비자 코드 업데이트 필수 |
| enum 값 추가 | minor 버전업 | 소비자 코드 업데이트 필요 |
| 설명(description) 변경 | 버전 변경 없음 | 영향 없음 |

> `additionalProperties: false` 정책으로 인해 새 필드 추가 시 소비자(백엔드, 대시보드)의 스키마 검증이 실패한다. 따라서 새 필드 추가는 minor 버전업과 동시에 모든 소비자의 스키마 정의를 업데이트해야 한다. "새 필드는 기존 소비자에 영향을 주지 않는다"는 설명은 본 프로젝트에 적용되지 않는다.

---

## 8. 좌표계 정의

### 8.1 물리 좌표계 (센서 데이터 기준)

| 항목 | 정의 |
|------|------|
| 원점 | 모형 왼쪽 전면 바닥 |
| X축 | 모형 가로 방향 (폭) |
| Y축 | 모형 세로 방향 (깊이) |
| Z축 | 높이 방향 (Z-up) |
| 단위 | meter |
| 좌표계 식별자 | `model-local` |

### 8.2 Three.js 렌더링 좌표계 변환

Three.js는 Y-up 좌표계를 사용한다. 물리 좌표계(Z-up)와 Three.js 좌표계(Y-up) 간 변환 규칙:

```
three_x = physical_x
three_y = physical_z
three_z = -physical_y
```

| 물리 좌표계 | Three.js 좌표계 | 의미 |
|-----------|----------------|------|
| X (가로/폭) | X | 가로 방향 |
| Y (깊이) | -Z | 깊이 방향 (Three.js에서 카메라가 바라보는 방향) |
| Z (높이) | Y | 높이 방향 |

> 백엔드와 센서 데이터는 물리 좌표계(Z-up)를 사용하고, 프론트엔드 Three.js 렌더링 시에만 위 변환을 적용한다. 상세한 매핑은 `05_DIGITAL_TWIN_SPEC.md`를 참조한다.

---

## 9. 단위 규칙

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

---

## 10. 디지털 트윈 WebSocket 메시지

> JSON Schema: `schemas/twin-delta.schema.json`, `schemas/twin-snapshot.schema.json`

백엔드가 대시보드로 전송하는 WebSocket 메시지이다. MQTT 토픽과 별개이다.

### 10.1 Delta 메시지 (rev. 2)

```json
{
  "type": "delta",
  "revision": 2,
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
| `revision` | integer | 메시지 리비전 번호. 1부터 증가. 대시보드는 revision 번호로 순서 검증 |
| `object_id` | string | 3D 객체 식별자 (`tw.` prefix) |
| `physical_id` | string | 물리 노드 식별자 |
| `timestamp` | string | 상태 변화 시각 (UTC) |
| `changes` | object | 변경된 필드와 값 |

### 10.2 Snapshot 메시지 (rev. 2)

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

> Snapshot/Delta의 `revision` 필드는 메시지 구조의 리비전이며, 스키마 버전(`schema_version`)과 다르다. WebSocket 재연결 시 대시보드는 revision이 연속적인지 확인하고, 빈 구간이 있으면 Snapshot을 재요청한다.
