# 펌웨어 통합 문서

## 목적

이 문서는 하드웨어 팀이 전달한 펌웨어 zip을 HP015 저장소의
`firmware/` 구조에 통합한 방식과, 백엔드 MQTT/데이터 계약에 맞춰 조정한
내용을 기록한다.

이 작업의 목적은 머지만으로 하드웨어 검증을 완료했다고 주장하는 것이
아니다. 실제 센서 노드 펌웨어가 백엔드에서 받을 수 있는 형태의 데이터를
발행하도록 만들어, 이후 실물 하드웨어 검증을 진행할 수 있게 하는 것이다.

## 입력 번들

원본 zip:

```text
/Users/choihwanseok/Downloads/firmware (1).zip
```

zip에 포함되어 있던 주요 내용:

- PlatformIO 프로젝트 설정
- `sensor_node`, `wearable_node`, `thermal_node` 진입점
- MH-Z19B, BME680, ADS1115/MQ, SEN0322, MPU6050 센서 드라이버
- MQTT envelope/topic/time/ULID 헬퍼
- serial/MQTT 로깅 도구
- `.pio/` 아래의 로컬 빌드 산출물과 의존성 캐시
- `test_results/` 아래의 로컬 실행 로그
- 실제 WiFi 정보가 들어 있는 네트워크 설정 파일

## 통합 원칙

| 원칙 | 이유 |
|---|---|
| 하드웨어 팀 코드를 센서 노드 런타임 기준으로 사용 | 실제 WiFi, MQTT, NTP, 센서 읽기, publish 루프가 포함되어 있음 |
| 백엔드 스키마를 payload 형태의 기준으로 사용 | 검증 대상은 이 저장소의 백엔드 ingest 동작임 |
| `.pio/`, `.pio-core/`, 바이너리, `test_results/`는 커밋하지 않음 | 로컬 생성물 또는 빌드 산출물임 |
| 실제 네트워크 비밀값은 커밋하지 않음 | WiFi/MQTT 정보는 로컬 비밀 설정으로 분리해야 함 |
| 기존 웨어러블 local alert 헬퍼는 보존 | #113 fail-safe 후속 작업에 필요할 수 있음 |

## 통합 후 저장소 구조

```text
firmware/
  platformio.ini
  README.md
  include/
    config/
    drivers/
    mqtt/
    wearable/
  src/
    sensor_node/
    wearable_node/
    thermal_node/
    drivers/
    mqtt/
  tools/
```

## 제외한 zip 내용

| zip 경로 | 처리 |
|---|---|
| `.pio/` | 저장소에서 제외 |
| `.pio/build/` | 저장소에서 제외 |
| `.pio/libdeps/` | 저장소에서 제외 |
| `test_results/` | 저장소에서 제외. 로컬 참고 자료로만 사용 |
| 원본 `include/config/network_config.h` | 실제 비밀값이 있어 그대로 복사하지 않음 |

로컬 빌드 검증 중에는 zip에 있던 `.pio/libdeps/` 캐시를 gitignored 대상인
`firmware/.pio/libdeps/`로 복사해 PlatformIO가 라이브러리를 다시
다운로드하지 않아도 빌드되도록 했다. 이 캐시는 로컬 빌드 의존성 캐시이며
여전히 저장소 커밋 대상이 아니다.

## 백엔드 계약 반영 내용

| 영역 | 하드웨어 번들 기존 동작 | 통합 후 동작 |
|---|---|---|
| 네트워크 설정 | `network_config.h`에 실제 SSID/password/broker IP 포함 | `network_config.h`가 gitignored `network_config.local.h`를 읽고, 예시 파일은 별도 커밋 |
| MQTT 인증 | username/password 없음 | `NetworkConfig`에서 선택적으로 username/password 사용 |
| 온라인 연결 payload | `{"status":"online"}` | `schema_version`, `node_id`, `status`, `reason`, `boot_id`, `timestamp` 포함 |
| LWT offline payload | `{"status":"offline"}` | 동일한 `node-connection` 형태에 `reason:"lwt"` 포함. NTP 미동기 시 timestamp는 `null` |
| NTP 미동기 telemetry | 빈 `sampled_at`이 나갈 수 있음 | NTP 동기 전에는 발행하지 않고 시리얼 로그에 skip 기록. loop에서 백오프로 NTP 재시도 |
| MQ-7 필드 | `mq7_*` | 백엔드 gas 계약의 `co_*` 필드와, 교정 완료 시 `co_ppm` 발행 |
| MQ-136 필드 | `mq136_*` | 백엔드 gas 계약의 `h2s_*` 필드와, 교정 완료 시 `h2s_ppm` 발행 |
| 상태 payload | 일부 상태 필드만 발행 | `battery_pct`, `wifi_rssi_dbm`, `uptime_s`, `free_heap_bytes`, `sensors_online`, `sensors_error` 포함 |
| 노드 ID | 빌드 플래그로 설정 가능 | `sensor-01`부터 `sensor-04`까지 `NODE_ID_VALUE` 유지 |
| 웨어러블 O2 | 원시 `DFRobot_OxygenSensor` 직접 호출 | `Sen0322Driver` 유효성 검사를 거치고, 무효 읽기 시 `o2_pct`를 발행하지 않음 |

## MQ 교정값과 ppm 발행

MQ 계열 R0 교정값 출처는 빌드 플래그로 정했다.

```ini
-D MQ7_R0_OHM=0.0
-D MQ136_R0_OHM=0.0
-D MQ2_R0_OHM=0.0
```

기본값은 모두 `0.0`이다. 따라서 현장 교정값을 명시하지 않으면
`co_ppm`, `h2s_ppm`은 발행하지 않고 `co_calibration_status`,
`h2s_calibration_status`를 `uncalibrated`로 보낸다.

이 방식을 선택한 이유:

- 수요일 검증 전 빌드 재현성이 높다.
- 부팅 시 청정공기 자동 교정은 실제 현장 공기가 깨끗하다는 가정이 필요해
  안전 경보용 값으로 바로 쓰기 어렵다.
- NVS 저장 방식은 실물 교정 절차와 저장/초기화 UX가 필요해 별도 작업으로
  분리하는 편이 안전하다.

기존 `firmware/src/sensors/calibration.h`의 `MqCalibrator` 상태머신은
되살려두었다. 이번 PR에서는 자동 교정에 연결하지 않았고, 후속 교정/NVS
작업에서 재사용한다.

## 로컬 빌드 검증

실행한 명령:

```bash
cd firmware
PLATFORMIO_CORE_DIR=/Users/choihwanseok/26_HP015/firmware/.pio-core pio run -e sensor-01
PLATFORMIO_CORE_DIR=/Users/choihwanseok/26_HP015/firmware/.pio-core pio run -e sensor-02 -e sensor-03 -e sensor-04 -e thermal-node -e wearable-node
python3 -m py_compile firmware/tools/*.py
git diff --check -- firmware docs/FIRMWARE_INTEGRATION.md
```

확인 결과:

- `sensor-01`, `sensor-02`, `sensor-03`, `sensor-04`: 빌드 성공
- `thermal-node`: 빌드 성공
- `wearable-node`: 빌드 성공
- Python helper script 문법 검사 성공
- diff whitespace 검사 성공
- 백엔드 `_parse_ts('')`가 `InvalidMessage`를 던지는 것 확인
- `setR0Values()`가 센서 노드 setup에서 호출되는 것 확인
- `co_estimated_ppm`, `h2s_estimated_ppm` 대신 백엔드 threshold 이름인
  `co_ppm`, `h2s_ppm`을 사용하는 것 확인
- 웨어러블 O2가 `Sen0322Driver`를 거치고, 무효 읽기 시 `quality.sensors`
  안에 `sen0322: "error"`를 싣는 것 확인

아직 확인하지 않은 것:

- ESP32 실제 업로드
- 실물 보드의 WiFi/MQTT 접속
- 실제 센서 읽기값 정확도
- 실물 데이터의 백엔드 DB insert
- 실제 보드 재부팅 후 `message_id` 무중복 동작
- 실제 SEN0322 분리/고장 상황에서 진동 경보가 울리는지

## 하드웨어 검증 계획

1차 대상은 `sensor-01`이다.

ESP32 전원 인가 또는 재부팅 전에 tap을 실행한다.

```bash
/private/tmp/hp015_hw_tap_sensor_01.sh
```

데이터 수집과 보드 재부팅 3회를 마친 뒤 확인 스크립트를 실행한다.

```bash
/private/tmp/hp015_hw_check_sensor_01.sh
```

이슈별 판정 기준:

- #107: `sensor-01`의 실제 MQTT 데이터가 백엔드 `sensor_data`에 insert되면 통과
- #103: 수집된 `sampled_at`이 허용된 NTP 오차 범위 안이면 통과
- #104: 보드 재부팅 3회 후에도 `message_id` 중복이 없으면 통과

## 남은 하드웨어 작업

- #113 웨어러블 O2 fail-safe는 wearable 펌웨어 통합과 실제 SEN0322/I2C
  고장 상황 테스트가 필요하다.
- #121 UWB/DWM1000 정확도는 실제 anchor/tag 배치와 ground truth 실측이
  필요하다.
- `platformio.ini` 라이브러리 버전 핀은 별도 작업으로 남긴다. 이번에 핀을
  시도했지만 오프라인 `.pio/libdeps` 캐시와 충돌해 PlatformIO가 라이브러리를
  다시 설치하려 했고, 네트워크가 제한된 환경에서는 빌드가 막혔다.
