# 펌웨어

이 PlatformIO 프로젝트는 하드웨어 팀 펌웨어를 HP015 백엔드 MQTT 계약에
맞춰 통합한 펌웨어 코드다.

## 구조

```text
include/config/      노드 및 네트워크 설정
include/drivers/     센서 드라이버 헤더
include/mqtt/        MQTT envelope, topic, time, ULID 헬퍼
include/wearable/    기존 저장소의 웨어러블 local alert 헬퍼
src/sensor_node/     센서 노드 진입점
src/wearable_node/   웨어러블 노드 진입점
src/thermal_node/    열화상 노드 진입점
src/drivers/         센서 드라이버 구현
src/mqtt/            MQTT 헬퍼 구현
tools/               Serial/MQTT 로깅 도구
```

## 로컬 네트워크 설정

`include/config/network_config.h`는 `network_config.local.h`가 있으면 해당
파일을 읽는다. 이 local 파일은 WiFi 정보와 broker 인증 정보를 담을 수
있으므로 gitignored 대상이다.

예시 파일을 복사해 local 설정을 만든다.

```bash
cp firmware/include/config/network_config.example.h \
  firmware/include/config/network_config.local.h
```

이후 아래 값을 현장 환경에 맞게 수정한다.

- `WIFI_SSID`
- `WIFI_PASSWORD`
- `MQTT_BROKER`
- `MQTT_PORT`
- `MQTT_USERNAME`
- `MQTT_PASSWORD`

## MQ 교정값

MQ-7, MQ-136, MQ-2의 R0 교정값은 `platformio.ini`의 빌드 플래그로 주입한다.
기본값은 모두 `0.0`이며, 기본값 상태에서는 CO/H2S ppm을 발행하지 않는다.

```ini
-D MQ7_R0_OHM=0.0
-D MQ136_R0_OHM=0.0
-D MQ2_R0_OHM=0.0
```

현장 교정값을 넣은 뒤에만 `co_ppm`, `h2s_ppm`이 발행된다. 교정 전에는
`co_calibration_status`, `h2s_calibration_status`로 `uncalibrated` 상태를
알린다.

## 빌드

기본 확인 대상:

```bash
cd firmware
PLATFORMIO_CORE_DIR=/Users/choihwanseok/26_HP015/firmware/.pio-core pio run -e sensor-01
```

다른 환경:

```bash
PLATFORMIO_CORE_DIR=/Users/choihwanseok/26_HP015/firmware/.pio-core pio run -e sensor-02
PLATFORMIO_CORE_DIR=/Users/choihwanseok/26_HP015/firmware/.pio-core pio run -e sensor-03
PLATFORMIO_CORE_DIR=/Users/choihwanseok/26_HP015/firmware/.pio-core pio run -e sensor-04
PLATFORMIO_CORE_DIR=/Users/choihwanseok/26_HP015/firmware/.pio-core pio run -e wearable-node
PLATFORMIO_CORE_DIR=/Users/choihwanseok/26_HP015/firmware/.pio-core pio run -e thermal-node
```

현재 로컬 저장소에서 `sensor-01`, `sensor-02`, `sensor-03`, `sensor-04`,
`thermal-node`, `wearable-node` 여섯 환경 모두 빌드 성공을 확인했다.

NTP가 아직 동기화되지 않은 상태에서는 telemetry를 발행하지 않는다. 각 노드는
loop에서 NTP를 백오프로 재시도하고, 발행을 건너뛴 경우 시리얼 로그에 남긴다.

## 하드웨어 검증 범위

1차 통합 대상은 `sensor-01`이다.

- #107: 센서 노드가 MQTT로 발행한 데이터가 백엔드 `sensor_data`에 insert되는지 확인
- #103: `sampled_at`이 NTP 동기화된 UTC 시간 기준인지 확인
- #104: 재부팅 3회 후에도 `message_id`가 중복되지 않는지 확인

웨어러블 O2 fail-safe(#113)와 UWB 정확도(#121)는 별도 실물 중심 작업이
필요하다.

웨어러블 O2 값은 `Sen0322Driver` 유효성 검사를 통과한 경우에만 `o2_pct`로
발행한다. 무효 읽기에서는 `o2_pct`를 보내지 않고 `quality.sensors`에
`sen0322: "error"`를 싣는다.
