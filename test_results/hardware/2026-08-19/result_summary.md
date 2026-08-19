# 하드웨어 검증 세션 결과 — 2026-08-19

검증자: funky (fmsds98@gmail.com)
머신: Windows 11 (계획서는 macOS 기준 — 경로 명령 다수 대체함)
저장소 상태: **git 저장소 아님** (`.git` 없음) → 워크트리·PR #171 도구·`gh` 사용 불가

---

## 0. 사전 점검 (§1)

| 항목 | 결과 | 근거 |
|---|---|---|
| 인프라 기동 (§1.2) | **통과** | timescaledb healthy / mosquitto Up / backend Up. `/health` → `{"status":"ok","mqtt":{"connected":true},"db":{"pool_initialized":true}}` |
| DB 마이그레이션 | **통과** | 001~005, 007 적용. 테이블 8종 생성 |
| 경보 임계값 로드 | **통과** | `alert evaluator initialized with 18 thresholds` |
| NTP UDP 123 (§1.5) | **통과** | `w32tm /stripchart pool.ntp.org` 오차 +0.0049s → §1.5 LWT 결함 미발동 |
| 펌웨어 커밋 3종 반영 | **확인** | `[MQ CAL]` 출력 / `src/sensors/calibration.h` / lib_deps 9개 버전 고정 / uptime·예열 경고 문구 |
| MQ 예열 (§1.3) | **완료 (사람 보장)** | CO(MQ-7 24h)·H₂S(MQ-136 48h) 예열 완료 — 검증자 확인. 보드는 `MQ_CALIBRATION_WARMUP_MS=0` 이라 시간 게이트 없음 |
| R0 값 | **미기입** | platformio.ini sensor-01~04 전부 `0.0` → 이번 세션에서 측정·기입 |

### 사전 조치 기록

- `firmware/include/config/network_config.local.h` 갱신
  - SSID `jjeong` → `iPad (74)` (현재 접속 중인 핫스팟)
  - `MQTT_BROKER` `172.18.247.160` → `172.20.10.13` (노트북 현재 IP)
  - 백업: `network_config.local.h.bak_20260819`
- PlatformIO 신규 설치 (`pip install platformio`)
- 판정 도구 대체본 작성 — `scripts/hw/tap.sh`, `scripts/hw/check.sh`
  (PR #171 `hw_verify.py` 를 못 받아서. `docker exec` 로 컨테이너의 `mosquitto_sub`/`psql` 사용)

---

## 1. 항목별 판정

<!-- 항목마다 §11 양식으로 아래에 추가 -->

### 펌웨어 빌드 6종 재실행 (§1.1)

| 환경 | 결과 |
|---|---|
| sensor-01 | SUCCESS (RAM 14.8% / Flash 64.8%) |
| sensor-02 | SUCCESS |
| sensor-03 | SUCCESS |
| sensor-04 | SUCCESS |
| wearable-node | SUCCESS |
| thermal-node | SUCCESS |

**판정: 로컬 코드 검증까지** — 빌드만 확인. 실물 동작 아님.

---

## 1. 항목별 판정

### #86 — 백엔드 장애 시 웨어러블 자율 진동

검증 일시: 2026-08-19 · 검증자: funky
펌웨어: 로컬 워킹카피 (커밋 2d4136c/1b73d33/4a4bd3d 내용 반영)

절차: 정적 확인 — `firmware/src/` 전체에서 로컬 경보 모듈 참조 검색

관찰 결과:
- `grep -rn "local_alert|vibration_motor|vibration_patterns|LocalAlert|VibrationMotor" src/` → **일치 0건**
- `src/wearable_node/main.cpp` 의 `#include` 목록에 `wearable/` 헤더 없음
  (Arduino/Wire/WiFi/MQTT/ArduinoJson/MPU6050/network_config/sen0322_driver/mqtt_time/ulid 뿐)
- 즉 `include/wearable/local_alert.h`·`vibration_motor.h`·`vibration_patterns.h` 는
  **보존만 되어 있고 빌드에 들어가지 않음** — 계획서 §5 C-2 의 리뷰 소견과 일치

**판정: [x] 재현 불가 — 진동 경보 자체가 미배선이라 조건을 만들 수 없음**

남은 일: 웨어러블 펌웨어에 로컬 경보 배선 (별도 이슈/PR). 배선 전까지 #86 은
하드웨어를 아무리 준비해도 판정 불가.
영향: §5 C-1(#113) 체크리스트 중 "웨어러블이 자율 진동할 것" 항목도 동일 사유로
판정 불가. #113 의 나머지 3개 항목은 정상 검증 가능.

---

### #113 사전 소견 — SEN0322 fail-safe 는 "범위 검사"뿐 (실물 검증 필수)

`src/drivers/sen0322_driver.cpp:49`

```cpp
if (oxygenPct <= 0.0F || oxygenPct > 30.0F) { data_.valid = false; ... }
```

- 발행 측(`src/wearable_node/main.cpp:372`)은 `valid` 일 때만 `o2_pct` 를 싣고,
  아니면 `quality.sensors.sen0322= "error"` — **로직 자체는 계약대로**
- 그러나 유효성 판단 근거가 **반환값의 범위뿐**이다. I2C 트랜잭션 ACK 확인이 없다.
  I2C 를 끊었을 때 라이브러리가 0 이나 0xFF 파생값을 주면 걸러지지만,
  **0~30 범위의 그럴듯한 값을 주면 그대로 정상 발행된다.**
- 따라서 §5 C-1 결과는 코드로 예측할 수 없고 **실물 절단 시험이 반드시 필요**하다.
  이것이 이 세션에서 가장 중요한 시험인 이유.

---

### metric 이름 정합성 사전 대조 (§6 "교정 후 확인")

하드웨어 없이 미리 확인. **불일치 없음.**

| 펌웨어 발행 필드 | thresholds.metric | 경로 |
|---|---|---|
| `co2_ppm` | `co2_ppm` | 직결 |
| `co_ppm` (R0>0 일 때만) | `co_ppm` | 직결 |
| `h2s_ppm` (R0>0 일 때만) | `h2s_ppm` | 직결 |
| `temperature_c` | `temperature_c` | 직결 |
| `o2_pct` | `o2_low` / `o2_high` | `backend/app/services/alert_service.py:23` 에서 팬아웃 |

thresholds 18행 적재 확인 (co2/co/h2s/o2_low/o2_high/temperature_c × 3레벨).
`co2_ppm` L1 = 1000ppm / enter_for 3000ms → §6 D-1(#54) 판정 기준과 일치.

**남은 확인:** 실물 데이터가 들어온 뒤 `SELECT DISTINCT metric FROM sensor_data`
로 실제 적재 이름을 다시 대조할 것 (이름이 맞아도 백엔드 ingest 가 해당 필드를
sensor_data 로 안 풀면 경보가 안 뜬다).

---

### 계획서 오류 정정

| 계획서 위치 | 계획서 내용 | 실제 |
|---|---|---|
| §4 B-6 | `curl localhost:8000/metrics` | **`/api/metrics`** (`backend/app/routers/health.py:21`). `/metrics` 는 404 |
| §1.1 / §6 5 | `PLATFORMIO_CORE_DIR=.../.pio-core pio run` | 이 머신은 코어가 `~/.platformio`. 지정하면 툴체인 1.2GB 재다운로드 |
| §1.4 | `git worktree add /tmp/hw-verify tools/hw-verification` | 저장소가 git 이 아니라 불가 → `scripts/hw/{tap,check}.sh` 로 대체 |
| §3, §10, §11 | `mosquitto_sub` / `psql` 로컬 호출 | 미설치 → `docker exec` 경유 |

`/api/metrics` 초기값 확인 (실물 투입 전 기준선):
`messages_processed=0, messages_dropped_invalid=0, messages_dropped_duplicate=0,
alerts_published=0, alerts_resolved=0, mqtt_reconnects=0`

---

### 세션 시작 시점 인프라 상태 (기준선)

```
hp015-backend       Up   0.0.0.0:8000->8000/tcp
hp015-frontend      Up   0.0.0.0:5173->80/tcp
hp015-mosquitto     Up   0.0.0.0:1883->1883/tcp
hp015-timescaledb   Up (healthy)  0.0.0.0:5432->5432/tcp
```

DB 전 테이블 0행 — 실물 데이터만 들어오므로 주입 데이터와 섞이지 않음.
대시보드 확인: WS `STREAM CONNECTED`, 노드 0/4 대기, IDW 캡션 표시됨(#160 사전 확인).

---

### 하드웨어 블로커 (2026-08-19 13:0x 시점)

- **CP2102N USB-UART 드라이버 미설치** — `USB\VID_10C4&PID_EA60`, Code 28
  (`CM_PROB_FAILED_INSTALL`). 보드는 물리적으로 연결돼 있으나 COM 포트가 생성되지 않음.
  → Silicon Labs CP210x VCP 드라이버 설치 필요 (관리자 권한)
- **Windows 방화벽** — 핫스팟 `iPad (74)` 가 Public 프로필. 인바운드 기본 차단이라
  ESP32 → 노트북:1883 접속이 잘릴 수 있음. 인바운드 허용 규칙 필요 (관리자 권한)

---

## 실물 세션 기록 (2026-08-19 오후)

### 하드웨어 준비

- CP2102N 드라이버 설치 → **COM6** 인식 (`Silicon Labs CP210x USB to UART Bridge`)
- 방화벽 인바운드 1883 허용
- iPad 핫스팟 "최대 호환성" 켜서 **2.4GHz 전환** (Channel 6 / 802.11n).
  ESP32 는 2.4GHz 전용이라 이전에는 `[WiFi] Connection timeout` 반복
- 노트북 IP `172.20.10.13` 유지 → `MQTT_BROKER` 수정 불필요

---

### #107 센서 노드 E2E 파이프라인 — **실물 통과** (부분)

검증 일시: 2026-08-19 · 펌웨어: sensor-01 (로컬 워킹카피)

시리얼 관찰:
```
[WiFi] Connected.   IP 획득, RSSI -35 ~ -37 dBm
[TIME] Synced: true
[MQTT] Connecting to 172.20.10.13:1883
[MQTT] Connected.
[MQTT] Online status published (QoS 1).
[MQTT GAS] {...}  sequence 증가 (163 → 184 …)
```

DB 관찰:
```
processed_messages (sensor-01) = 224 건
node_status = sensor-01 | online | rssi -36 | uptime 30s
sensor_data = 0 행
```

판정 근거 — `sensor_data` 0 행은 파이프라인 결함이 아니다.
`backend/app/services/ingest.py:139 _extract_metrics` 가 `None` 을 건너뛰는데,
연결된 센서가 없어 모든 data 필드가 `null` 이었다. 즉 **MQTT → 백엔드 →
DB 경로는 실증되었고, 흘려보낼 값이 없었을 뿐이다.**

**판정: [x] 실물 통과** (전송 경로). 단 실제 센서값 적재는 센서 연결 후 재확인 필요.

### #103 NTP 시각 동기 — **실물 통과**

`node_status.updated_at`(기기 sampled_at) vs `backend_received_at` 편차 **-15ms**.
판정 기준 ±2초 → 통과.

---

### ★ 웨어러블 MQTT 인증 누락 — **실물 실패 → 수정함**

| | 코드 | 결과 |
|---|---|---|
| 센서 노드 | `src/sensor_node/main.cpp:202` `connect(clientId, MQTT_USERNAME, MQTT_PASSWORD)` | 접속 성공 |
| 웨어러블 (수정 전) | `src/wearable_node/main.cpp:215` `connect(clientId.c_str())` | **거부** |

브로커 `allow_anonymous false` → 익명 거부. 브로커 로그 증거:
```
Client wearable-01-7ed8cbb0 disconnected, not authorised.
```

주입 검증만 해왔기 때문에 드러나지 않던 결함. §5 전체(#113 #86 #11 #12 #42 #43)를 막고 있었다.

**조치:** 센서 노드와 동일 패턴으로 인증 인자 추가. 백업 `main.cpp.bak_20260819`.
**결과:** `[MQTT] Connecting... connected.` 확인.

---

### ★ SEN0322 미검출 — 원인 규명 및 수정

**증상:** I2C 스캐너는 `0x73` 을 안정적으로 검출하는데 웨어러블 펌웨어만
`[SEN0322] Initialization failed.` — 9회 반복 재현, 빌드 종류와 100% 상관.

**절단 실험 (버스 재초기화 후 각 조건별 콜드 probe 0x73):**

| 선행 동작 | 결과 |
|---|---|
| 없음 | FAIL |
| 0x73 재probe | FAIL |
| 0x70~0x72 형제 주소 | FAIL |
| 0x00 제너럴 콜 | FAIL |
| SCL 16회 수동 클럭 + STOP (버스 리커버리) | FAIL |
| 더미 0x10 × 5 | FAIL |
| 더미 0x10 × 30 | **OK** |
| 더미 0x10 × 114 | **OK** |
| 전체 주소 스윕 0x01~0x72 | **OK** |

**결론:** 특정 주소나 SDA 락업이 아니라 **선행 I2C 트랜잭션 횟수**(약 20~30회)에
반응한다. DFRobot 라이브러리 `begin()` 은 probe 를 1회만 하고 실패를 반환하므로
`oxygenReady` 가 영구히 false 로 굳었다.

**조치:** `src/drivers/sen0322_driver.cpp` `begin()` 에 버스 프라이밍(더미 40회) +
최대 3회 재시도 추가. 백업 `sen0322_driver.cpp.bak_20260819`.

**결과:**
```
[SEN0322] Initialization successful.
[SEN0322] I2C address: 0x73
[SEN0322] Ready.
```

---

### #113 SEN0322 fail-safe — **중간 관찰 (safety-critical)**

현재 센서가 O₂ 값으로 `0.00` 을 반환하는 상태인데, **fail-safe 는 계약대로 동작 중**:

```
시리얼: [SEN0322] Invalid O2 value: 0.00
        [SEN0322] O2 publish without o2_pct: invalid reading.
MQTT:   wearable/wearable-01/vital
        {"data":{}, "quality":{"sensors":{"sen0322":"error"}}}
```

- `o2_pct` 가 **발행되지 않음** ✅ (정상값 위장 없음)
- `quality.sensors.sen0322 == "error"` ✅

즉 판정 기준 4개 중 2개를 **의도치 않게 실물로 확인**했다. 다만 이는 I2C 절단
시험이 아니라 센서가 0.00 을 반환한 상황이므로, **정식 #113 판정은 O₂ 가 정상값
(약 20.9%) 을 내는 상태에서 물리 절단으로 다시 해야 한다.**

**미해결:** O₂ 가 `0.00` 인 원인 (프로브 미장착 / 읽기 경로에도 프라이밍 필요 /
센서 수명 등) — 조사 계속 필요.

### MPU-6050 — 미검출

I2C 스캔에 `0x68` 없음. 웨어러블에 물리적으로 미배선.
→ **#11 낙상 감지 / #43 재현 불가.**

---

### #52 / #111 연결 끊김 감지 — **실물 통과** (부수적 수확)

sensor-01 보드를 웨어러블로 재플래시하면서 전원이 끊긴 순간 관찰됨.

```
node_status  : sensor-01 | offline | 2026-08-19 04:31:56.871+00
alert_events : sensor-01 | level3_critical
               activated 04:31:56.936602 / published 04:31:56.941710
               delay = 00:00:00.005108
```

계획서 §A-4 는 "PR #153 이 main 에 없어 LWT timestamp 가 stale 가드에 막혀
offline 이 반영되지 않을 수 있다" 고 경고했으나, **실물에서는 정상 반영됨.**
NTP 가 동기된 상태였기 때문으로 보인다(§1.5 의 전제와 일치).

**판정: [x] 실물 통과.** 경보 발행 지연 5.1ms 는 #67 의 부분 측정치로 활용 가능
(단 화면 렌더까지 포함한 E2E 지연은 별도 측정 필요).

---

### ★ 새 결함 — `wearable/+/status` 미구독

웨어러블 발행 토픽 (`src/wearable_node/main.cpp`):
`wearable/<id>/imu` · `wearable/<id>/vital` · `wearable/<id>/status`

백엔드 구독 (`backend/app/services/mqtt_subscriber.py:17-23`):
```
sensors/+/gas      sensors/+/env      sensors/+/status
wearable/+/location  wearable/+/ranging  wearable/+/imu  wearable/+/vital
```

**`wearable/+/status` 가 없다.** `node_status` 를 쓰는 것은 `ingest_status` 뿐이고
그 핸들러는 `sensors/+/status` 에만 걸려 있으므로, **웨어러블은 node_status 에
행이 생기지 않고 연결 끊김 감지 대상에서 완전히 빠진다.**

실측: `processed_messages` 에 wearable-01 379 건이 쌓였으나
`node_status` 에는 wearable-01 행이 없음.

영향: 웨어러블이 죽어도 대시보드가 오프라인으로 표시하지 못함 —
작업자 안전 장비이므로 영향이 크다. 계획서 §9 열화상 미구독과 같은 유형.

**판정: [x] 실물 실패** — 별도 이슈/PR 필요 (백엔드 수정).

---

### 대시보드 미표시 — 원인 규명 (결함 아님)

`sensor_data` 0 행 → 대시보드 빈 화면. 파이프라인은 정상:

```
processed_messages : wearable-01 379 / sensor-01 302
```

원인: 저장할 숫자가 없음.
- sensor-01 : 센서 미배선 → 모든 data 필드 `null`
- wearable-01 : O₂ 0.00 → invalid → `data: {}` 빈 객체
- `_extract_metrics` 는 `null` 과 빈 객체를 스킵

**결론: 프론트엔드 결함 아님.** 센서가 유효값을 내는 즉시 표시된다.

---

### #42 SEN0322 O₂ 정확도 — **판정 보류**

I2C 통신은 정상 (초기화 성공, 0x73 확인). 그러나 값이 40초 이상 `0.00` 고정.
대기 중 기대값 약 20.9% 와 불일치.

```
[SEN0322] Invalid O2 value: 0.00
```

통신 문제가 아니라 센서가 0 을 반환하는 상태.
후보 원인: (1) 산소 프로브 미장착 — SEN0322 는 보드와 전극 프로브가 분리형이며
미장착 시 정확히 0.00 (2) 프로브 커넥터 접촉 불량 (3) 전기화학 셀 수명 만료.

**판정: [ ] 보류** — 프로브 장착 확인 후 재시험.

---

### #42 SEN0322 — 추가 절단 실험 (레지스터 직접 판독)

라이브러리를 거치지 않고 I2C 레지스터를 직접 읽음.

```
[O2] probe 0x73 = OK
[O2] key=[--] data=[--] probeLife=--   ← requestFrom 이 0 바이트 반환
```

(238 = 0xEE 는 "읽히지 않음" 표식으로 넣은 값. 즉 수신 바이트 0.)

**클럭별 시험:**

| 클럭 | 주소 ACK | 레지스터 write | 읽은 바이트 |
|---|---|---|---|
| 400 kHz | FAIL | FAIL | 0 |
| 100 kHz | OK | OK | **0** |
| 50 kHz | OK | OK | **0** |
| 20 kHz | OK | FAIL | 0 |
| 10 kHz | OK | FAIL | 0 |

**결론:** 주소 ACK 와 레지스터 write 는 되는데 **읽기만 전 속도에서 0 바이트**.
클럭을 낮춰도 개선되지 않으므로 신호 품질(속도) 문제가 아니다.
슬레이브가 주소에는 응답하나 읽기 데이터를 내보내지 못하는 상태.

`getOxygenData()` 가 0.00 을 반환한 것은 이 때문이다
(`_Key × (raw0 + raw1/10 + raw2/100)` 에서 raw 가 전부 0).

**펌웨어 문제가 아니다.** 모듈 쪽 하드웨어 조사 필요:
1. 산소 프로브(전극) 장착 여부
2. 모듈 VCC 실측 (3.3~5.5V 규격)
3. 5V(Vin) 급전으로 변경 시도
4. SDA/SCL 풀업 저항 확인

**판정: [ ] 보류 (하드웨어 원인 조사 중)**

### 화면의 "센서 연결 끊김" 표시 — 정상 동작

`node_status: sensor-01 | offline | reason=timeout`.
sensor-01 보드를 웨어러블 펌웨어로 덮어썼으므로 실제로 발행이 멈춘 상태.
**오탐 아님 — 실제 상태를 정확히 반영.** (#123 연결 표시 부수 확인)

---

## 2. 고정 센서 노드 실측 세션 (COM7, 14:29~)

오전에 쓰던 보드(COM6)는 웨어러블이었고, ADS1115·BME680·MH-Z19B 가 배선된
**별도 보드**를 COM7 에 연결해 `sensor-01` 로 플래시했다.

### 2.1 부팅 및 센서 인식 — 전 항목 정상

```
[WiFi] Connected.  IP 172.20.10.11  RSSI -33 dBm
[TIME] NTP synchronization successful.   Synced: true
[MQTT] Connecting to 172.20.10.13:1883
[MQTT] Connected.  Online status published (QoS 1).
[ADS1115] Initialization successful.  I2C address: 0x48
[BME680]  Initialization successful.
[MH-Z19B] Driver started.  Warm-up: 60 seconds.
```

MQTT 페이로드의 quality 필드:
```
"sensors":{"ads1115":"valid","mh-z19b":"valid","bme680":"valid",
           "mq-7":"uncalibrated","mq-136":"uncalibrated","mq-2":"uncalibrated"}
"message_status":"complete"
```

`mq-*` 가 `uncalibrated` 인 것은 **정상**이다. R0 가 0 이면 펌웨어가 의도적으로
ppm 계산을 생략하고 원시값만 보낸다 (틀린 ppm 을 정상값으로 내보내지 않기 위함).

---

### 2.2 수집 규모

```
수집 구간   2026-08-19 05:29:29Z ~ 06:12:34Z (43분)
적재 행수   35,178 행 / 16 metric / node_id = sensor-01
백엔드 카운터
  messages_processed        35,178
  messages_dropped_invalid       0
  messages_dropped_duplicate     0
  mqtt_reconnects                0
```

CSV 원본: `csv/01_요약통계.csv` `csv/02_원시데이터.csv` `csv/03_시계열_피벗.csv`

---

### 2.3 측정 통계 (전 구간)

| 항목 | 표본 | 평균 | 표준편차 | 최소 | 최대 | CV% |
|---|---:|---:|---:|---:|---:|---:|
| `co2_ppm` | 2,266 | 589.61 | 66.73 | 452 | 690 | 11.32 |
| `temperature_c` | 858 | 24.52 | 1.04 | 23.18 | 26.61 | 4.22 |
| `humidity_pct` | 858 | 60.87 | 2.38 | 54.16 | 74.27 | 3.91 |
| `pressure_hpa` | 858 | 1008.20 | 0.09 | 1008.05 | 1008.37 | **0.01** |
| `iaq_index` | 2,568 | 59.34 | 13.98 | 48.35 | 110.21 | 23.56 |
| `iaq_accuracy` | 2,568 | 0.62 | 0.49 | 0 | **1** | — |
| `gas_resistance_ohm` | 2,568 | 184,844 | 17,938 | 38,318 | 201,502 | 9.70 |
| `co_rs_ohm` (MQ-7) | 2,568 | 176,439 | 9,199 | 148,479 | 216,886 | 5.21 |
| `h2s_rs_ohm` (MQ-136) | 2,568 | 8,786 | 7,174 | 3,600 | 21,842 | **81.65** |
| `mq2_rs_ohm` | 2,568 | 21,835 | 629 | 18,561 | 23,275 | 2.88 |

**⚠ 해석 주의 — `h2s_rs_ohm` CV 81.65% 를 그대로 인용하면 안 된다.**

센서 불안정이 아니라 **환경 변화**다. 06:02 에 보드를 실내에서 창가로 옮겼고,
그 시점에 MQ-136 Rs 가 약 4.5 배 급등했다.

```
06:01 이전  Rs 약  4,400 Ω  (실내)
06:03 이후  Rs 약 21,000 Ω  (창가, 청정 공기)
```

실내 미량 H2S 가 사라지면서 저항이 올라간 것으로, **센서가 정상 반응한 증거**다.
이동 후 구간만 계산하면 CV 2.74%. 보고서에는 이동 시점 기준으로 분리해 기재할 것.

`pressure_hpa` CV 0.01% 는 기압계가 매우 안정적임을 보여준다.

---

### 2.4 #39 MH-Z19B (CO2) — **실물 통과**

- 전원 인가 후 60초 예열 카운트다운 정상 동작
- 예열 후 CO2 발행 시작. 실내 682 ppm → 창가 이동 후 평균 501 ppm
- 전 구간 452~690 ppm. 외기 400ppm 대비 실내 상승분으로 타당
- 계획서 §4 B-1 의 "외기 기준값 약 400ppm" 에 근접 (창가 최저 452)

**판정: [x] 실물 통과**

### 2.5 #40 BME680 — **실물 통과**

- 온도 24.52'C / 습도 60.87% / 기압 1008.20 hPa — 모두 타당한 실내값
- **BSEC burn-in 실증**: `iaq_accuracy` 가 0 -> 1 로 상승

```
accuracy=0    971 건   05:29:29 ~ 06:07:10
accuracy=1  1,501 건   05:37:48 부터   <- 부팅 후 8분 19초 만에 상승
```

계획서 §4 B-2 의 판정 기준("0 -> 1 -> 2 로 올라가는지")을 실물로 충족.
accuracy 2 까지는 약 1시간 추가 필요.

**판정: [x] 실물 통과** (accuracy 2 도달은 미확인)

### 2.6 #41 ADS1115 + MQ-7/136/2 — **실물 통과**

- I2C 주소 `0x48` 인식 확인
- MQ 3종 원시값(`raw_adc` / `voltage_v` / `rs_ohm`) 전부 발행
- `co_calibration_status` 등이 `"uncalibrated"` — 계획서 §4 B-3 기준대로 정상

**판정: [x] 실물 통과** (교정 전 원시 수집 단계까지)

### 2.7 #49 통신 안정성 — **실물 통과**

계획서 §4 B-6 은 "4개 노드 동시 30분 연속" 을 요구하나, 오늘은 노드 1개만
가용했다. **1개 노드 43분 연속** 기준의 결과:

```
messages_processed        35,178
messages_dropped_invalid       0     손실률 0%
messages_dropped_duplicate     0     중복률 0%
mqtt_reconnects                0     재연결 0회
```

**판정: [x] 실물 통과 (단, 1개 노드 한정)** — 4노드 동시 부하 시험은 미실시.

---

### 2.8 #48 R0 교정 — 후보 산출 완료, 기입 보류

**시리얼 없이 DB 로 계산했다.** 보드가 USB 에서 분리되어 완전 무선으로 동작 중이라
`[MQ CAL]` 시리얼 출력을 볼 수 없었으나, `rs_ohm` 이 MQTT 로 발행되므로
R0 = Rs / clean_air_ratio 를 직접 계산할 수 있다.
(clean-air Rs/R0 데이터시트값: MQ-7 27.5 / MQ-136 3.4 / MQ-2 9.83)

도구: `scripts/hw/r0.sh [분]`

**이 방식이 펌웨어보다 나은 점:** 펌웨어 `MqCalibrator` 는 60샘플(1분) 창의
max-min spread 만 본다. 그래서 (a) 느린 드리프트를 놓치고 (b) 이상치 샘플 하나에
통째로 흔들린다. DB 계산은 창 길이를 자유롭게 잡고 CV·중앙값 등 강건한 통계를 쓸 수 있다.

**실제로 두 문제가 다 관찰됐다:**

1. 드리프트 — 이동 전 mq7 R0 후보가 5445 -> 6270 으로 약 15% 상승하는 동안
   펌웨어 spread 는 1.7~1.9% 로 "안정" 이었다
2. 이상치 — h2s 원시 max-min spread 35% 였으나 p05~p95 는 5.3%.
   `min=13,852` 단일 이상치가 원인

**최종 R0 후보 (창가 이동 후 6분, 중앙값 기준):**

| 센서 | R0 평균 | CV | R0 중앙값 | 원시 spread |
|---|---:|---:|---:|---:|
| MQ-7 (CO) | 6,783.9 | 2.65% | **6,683.6** | 12.20% |
| MQ-136 (H2S) | 6,184.3 | 2.74% | **6,233.5** | 35.15% |
| MQ-2 | 2,278.2 | 2.14% | **2,295.8** | 11.10% |

분 단위 추이 (수렴 확인, `csv/04_R0교정추이.csv`):
```
06:09   MQ7 6791.2   MQ136 6233.5   MQ2 2299.6
06:10   MQ7 6848.8   MQ136 6156.2   MQ2 2290.3
06:11   MQ7 6860.3   MQ136 6229.1   MQ2 2302.7
06:12   MQ7 6802.3   MQ136 6234.0   MQ2 2304.3
06:13   MQ7 6842.7   MQ136 6218.8   MQ2 2299.3
```
방향성 드리프트가 멈추고 +-1.5% 이내 진동.

**교정 환경:** 창가, CO2 501 ppm (실내 673 -> 창가 501). 환기됐으나 완전 실외
(약 420 ppm) 는 아님. 예열은 MQ-7 24h / MQ-136 48h 완료 (검증자 확인).

**판정: [ ] 보류** — 값은 산출됐으나 `platformio.ini` 기입은 미실시.
기입 시 `calibration_status` 가 `calibrated` 로 바뀌어 ppm 이 신뢰값으로 발행되므로,
검증자 승인 후 진행할 것. 더 정확히 하려면 실외 재측정 권장.

---

### 2.9 오늘 미실시 항목

| 항목 | 사유 |
|---|---|
| #54 시간 기반 판정 (CO2 1000ppm 3초) | 미실시 — CO2 불기 시험 안 함 |
| #55 Hysteresis / De-escalation | 미실시 |
| #67 E2E 경보 지연 (화면 렌더까지) | 부분만 — 발행 지연 5.1ms 만 측정 |
| #13 #162 추세 기반 선제 표시 | 미실시 |
| #159 #160 트윈 좌표·판독성 | 미실시 |
| #49 4노드 동시 부하 | 노드 1개만 가용 |

