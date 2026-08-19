# 하드웨어 검증 세션 인수인계 — 2026-08-19

세션 수행: Windows 11 노트북 · 이후 Codex 작업 환경으로 이관

---

## 0. 한 장 요약

```
GitHub main      391b453 → 08bcda1  (push 완료)
발견한 결함       5건 (4건 수정 완료 / 1건 하드웨어 원인 미해결)
실물 통과         #107 #103 #52 #111 #39 #40 #41 #49
최대 성과         센서→MQTT→백엔드→DB→대시보드 전 구간을 실물 데이터로 관통
남은 최대 블로커   MH-Z19B 배선 — 4보드 중 3보드에서 CO2 미수신
```

**이 문서만 읽으면 다음 세션을 이어갈 수 있게 썼습니다.**

---

## 1. 이번에 push 한 커밋 (5개)

```
08bcda1  test: 하드웨어 검증 세션 증거 + 판정 도구
20100ae  fix: wearable-node 빌드 실패 + 웨어러블 status 계약 위반 + wearable/+/status 미구독
e265fb4  fix(backend): 노드 복귀 시 connection_lost 경보가 해제되지 않던 문제
154d41a  Merge branch 'local-hw-work'
5ef9d9e  fix: 웨어러블 MQTT 인증 누락 + 프론트 Dockerfile vite build 누락
```

### 병합 경위 (중요)

두 컴퓨터가 같은 베이스(`cefa6d6`)에서 각자 작업한 것을 3-way 병합했습니다.

- **GitHub 쪽(다른 컴퓨터)**: DWM1000 UWB 드라이버, `scripts/hw_verify.py`,
  `platformio.ini` UWB 빌드 플래그, `sensor_node/main.cpp` SPI/ranging 연결
- **로컬 쪽(이 컴퓨터)**: 오늘 세션에서 고친 결함들

겹친 파일은 `firmware/src/wearable_node/main.cpp` 하나뿐이었고 수정 위치가 달라
**자동 병합, 충돌 0건**. 양쪽 변경이 모두 보존된 것을 확인했습니다.

---

## 2. 고친 결함 (4건)

### 2.1 웨어러블 MQTT 인증 누락 — `firmware/src/wearable_node/main.cpp`

```cpp
// 이전
if (mqttClient.connect(clientId.c_str())) {
// 이후
if (mqttClient.connect(clientId.c_str(),
        NetworkConfig::MQTT_USERNAME, NetworkConfig::MQTT_PASSWORD)) {
```

브로커가 `allow_anonymous false` 라 **웨어러블은 접속 자체가 불가능**했습니다.
증거: `Client wearable-01-... disconnected, not authorised.`
주입 데이터로만 검증해온 탓에 드러나지 않던 결함이고, 웨어러블 검증 전체를 막고 있었습니다.

### 2.2 프론트엔드 Dockerfile — `vite build` 누락

타입체크·린트만 하고 번들을 만들지 않아 `/app/dist` 가 없었습니다.
**프론트 컨테이너 빌드가 항상 실패**합니다. 한 줄 수정으로 해결.

### 2.3 connection_lost 경보가 해제되지 않음 — 백엔드

`connection_monitor` 에 `online→offline` 발생 경로만 있고 `offline→online`
해제 경로가 없었습니다. 노드가 복귀해도 alert 는 영구히 `active` 로 남습니다.
**안전 대시보드에서 안 꺼지는 L3 배너는 경보 자체를 무시하게 만듭니다.**

프론트(`useWebSocket.ts:32`)는 `to_level === 'normal'` 을 이미 처리하고 있었고,
publisher 도 NORMAL → resolved 변환을 갖고 있었습니다. **발행 측만 없었습니다.**

`ingest_connection` 이 upsert 전후 상태를 비교해 `offline→online` 일 때만
`emit_connection_restored()` 를 호출하도록 했습니다.

> 구현 중 스스로 만든 버그를 테스트가 잡았습니다. 조건을 `previous_status != "online"`
> 으로 쓰면 **처음 보는 노드(None)** 에서 참이 되어 없는 경보를 해제합니다.
> 반드시 `== "offline"` 으로 좁혀야 합니다.

전체 주기 검증(test-node-99): 최초등록 → 경보 0건 / 30초 무응답 → L3 active /
online 복귀 → resolved(17초). `alerts_published=1, alerts_resolved=1`.

### 2.4 `wearable/+/status` 미구독 + 웨어러블 status 계약 위반

백엔드가 `sensors/+/status` 만 구독하고 웨어러블용을 빠뜨려, **웨어러블이
node_status 에 올라오지 못했습니다 = 연결 끊김 감지 대상에서 통째로 제외.**
실측: `processed_messages` 에 wearable-01 379건인데 `node_status` 0행.

구독만 추가하면 안 됩니다. 페이로드가 계약 위반이라 `InvalidMessage` 로 버려집니다:

| 계약 | 수정 전 웨어러블 |
|---|---|
| `message_id` | 없음 |
| `data.wifi_rssi_dbm` | `wifi_rssi` (이름 다름) |
| `data.battery_pct` | 없음 |
| `data.free_heap_bytes` | 없음 |
| `data.sensors_online` / `sensors_error` | 없음 |

펌웨어와 백엔드를 함께 수정했습니다. **계획서 §9 가 열화상 노드에 대해 지적한 것과
동일 유형인데, 웨어러블도 같은 상태였다는 건 이번에 처음 드러났습니다.**
→ **열화상 노드도 같은 점검이 필요합니다 (미착수).**

### 2.5 wearable-node 빌드 실패 — `MqttTopics::wearableRanging()` 미구현

UWB ranging 발행 코드가 호출하는데 선언/정의가 없었습니다.
**GitHub main(391b453) 단독으로도 컴파일이 안 됩니다** — 컴파일되지 않는 상태로
push 되어 있었습니다. 계약대로 토픽 함수를 추가했습니다.

---

## 3. ⚠ 빌드 환경 함정 — 반드시 읽을 것

**한글이 포함된 경로에서는 `wearable-node` 링크가 실패합니다.**

```
ld.exe: cannot open map file .../firmware.map: Invalid argument
```

경로의 `바탕 화면` 이 깨져서 링커가 맵 파일을 쓰지 못합니다. **코드 문제가 아닙니다.**
나머지 5개 환경은 같은 경로에서도 빌드됩니다 — wearable-node 만 재현됩니다.

**대응: ASCII 경로에서 빌드할 것.**

```bash
cp -r <repo>/firmware /c/hp015build/ && cd /c/hp015build/firmware
python -m platformio run -e sensor-01 -e sensor-02 -e sensor-03 -e sensor-04 \
                         -e wearable-node -e thermal-node
```

이 경로에서 **6종 전부 SUCCESS** 확인했습니다.

또한 계획서의 `PLATFORMIO_CORE_DIR=$PWD/.pio-core` 는 **쓰지 마세요** —
지정하면 툴체인 1.2GB 를 처음부터 다시 받습니다. 기본 `~/.platformio` 를 씁니다.

---

## 4. 미해결 — 다음 세션 최우선

### 4.1 MH-Z19B 배선 (CO2) ★ 최우선

**4개 보드 중 sensor-01 만 CO2 가 나옵니다.** 나머지는 `Invalid response header`.

원시 UART 덤프로 원인을 확정했습니다 — **루프백입니다.**

```
보낸 명령:  FF 01 86 00 00 00 00 00 79
받은 것:    01 86 00 00 00 00 00 79      ← 보낸 것과 동일
TX/RX 반전: 0 바이트                      ← 센서 반응 전혀 없음
```

**GPIO16(RX)과 GPIO17(TX)이 서로 붙어 있고 MH-Z19B 는 신호 경로에 없습니다.**
브레드보드에서 두 점퍼를 같은 가로줄에 꽂으면 정확히 이렇게 됩니다.

올바른 배선:

```
MH-Z19B TX  → ESP32 GPIO16     (엇갈리게)
MH-Z19B RX  → ESP32 GPIO17
MH-Z19B VCC → ESP32 5V (VIN)   ← 3.3V 아님
MH-Z19B GND → ESP32 GND
```

**sensor-01 보드 배선이 정답이므로 그것과 나란히 놓고 비교하는 것이 가장 빠릅니다.**

진단 방법: 원시 바이트 덤프 스케치를 만들어 썼습니다(보레이트 3종 + TX/RX 반전 시도).
정상이면 `FF 86 ...` 으로 시작해야 합니다.

### 4.2 SEN0322 산소 센서 — 하드웨어 원인 추정

**웨어러블에서 가장 중요한 검증(#113)이 여기 막혀 있습니다.**

I2C 스캔에서 `0x73` 은 잡히고 주소 ACK 도 되는데 **읽기가 전 클럭에서 0바이트**입니다:

| 클럭 | 주소 ACK | 레지스터 write | 읽은 바이트 |
|---|---|---|---|
| 400 kHz | FAIL | FAIL | 0 |
| 100 kHz | OK | OK | **0** |
| 50 kHz | OK | OK | **0** |
| 10 kHz | OK | FAIL | 0 |

클럭을 낮춰도 안 되므로 신호 품질 문제가 아닙니다. `getOxygenData()` 가 0.00 을
반환하는 것도 이 때문입니다 (`_Key × (raw0 + raw1/10 + raw2/100)` 에서 raw 가 전부 0).

**확인 순서**: ① 산소 프로브(전극) 장착 여부 ② 모듈 VCC 실측(3.3~5.5V)
③ 5V 급전 시도 ④ SDA/SCL 풀업

부수 발견: SEN0322 는 콜드 버스에서 **선행 I2C 트랜잭션 20~30회**가 있어야
응답을 시작합니다(더미 5회 실패 / 30회 성공 / 전체 스윕 114회 성공).
DFRobot `begin()` 은 probe 를 1회만 하고 포기하므로 `oxygenReady` 가 영구히
false 로 굳습니다. **프라이밍+재시도 패치를 만들었으나 O2 값이 여전히 0.00 이라
근본 원인이 하드웨어일 가능성이 커서 이번 병합에서 의도적으로 제외했습니다.**
패치와 실측 근거는 백업 폴더에 보존돼 있습니다:

```
바탕 화면/26_HP015_hw_session_20260819_backup/patches/02-sen0322-i2c-priming.patch
```

하드웨어를 고친 뒤에도 필요하면 그때 적용하세요.

### 4.3 MQ R0 교정 — 값은 산출됨, 기입 미실시

`platformio.ini` 의 `MQ7/MQ136/MQ2_R0_OHM` 은 여전히 `0.0` 입니다.
R0 가 0 이면 펌웨어가 **의도적으로** ppm 계산을 생략하고 원시값만 보냅니다
(틀린 ppm 을 정상값으로 내보내지 않기 위함) → `co_calibration_status: uncalibrated`.

**sensor-01 R0 후보 (창가 이동 후 6분, 중앙값 기준):**

| 센서 | R0 평균 | CV | **R0 중앙값** |
|---|---:|---:|---:|
| MQ-7 (CO) | 6,783.9 | 2.65% | **6,683.6** |
| MQ-136 (H2S) | 6,184.3 | 2.74% | **6,233.5** |
| MQ-2 | 2,278.2 | 2.14% | **2,295.8** |

교정 조건: 창가, CO2 501ppm, 24.5°C / 60.9% RH.
예열 완료(MQ-7 24h / MQ-136 48h, 검증자 확인).
분 단위 추이에서 방향성 드리프트가 멈추고 ±1.5% 진동 확인.

**기입 전 판단이 필요합니다.** 넣는 순간 `calibration_status` 가 `calibrated` 로
바뀌어 ppm 이 신뢰값으로 발행됩니다. 실외 재측정이 더 정확하지만 **비 오는 날은
피하세요** — MQ 데이터시트 표준 조건이 20±2°C / 65±5% RH 라, 우천 실외(습도 90%+)는
현재 실내 창가보다 오히려 나쁩니다.

**도구**: `scripts/hw/r0.sh [분]` — 시리얼 `[MQ CAL]` 없이 DB 만으로 계산합니다.
보드가 USB 에서 빠져 무선으로만 돌 때도 쓸 수 있습니다.

> 펌웨어 `MqCalibrator` 보다 이쪽이 낫습니다. 펌웨어는 60샘플(1분) 창의 max-min 만
> 보므로 (a) 느린 드리프트를 놓치고 (b) 이상치 하나에 흔들립니다.
> 실제로 둘 다 관찰됐습니다 — R0 가 15% 상승하는 동안 펌웨어 spread 는 1.7% 였고,
> h2s 원시 spread 35% 는 단일 이상치(min=13,852) 탓이었습니다(p05~p95 는 5.3%).

### 4.4 열화상 노드 (미착수)

`thermal-node` 는 빌드만 통과합니다. 백엔드가 `thermal/#` 을 구독하지 않고
상태 필드명이 계약과 다릅니다 — **웨어러블에서 고친 것(2.4)과 동일한 유형**이므로
같은 방식으로 처리하면 됩니다.

---

## 5. 실물 통과 항목 (근거 포함)

| 이슈 | 판정 | 근거 |
|---|---|---|
| #107 E2E 전송 | 실물 통과 | `messages_processed` 35,178 / 손실 0 / 중복 0 |
| #103 NTP 시각동기 | 실물 통과 | 기기↔백엔드 편차 -15ms ~ 0.86s (기준 ±2s) |
| #52 #111 연결끊김 | 실물 통과 | offline 반영 + L3 경보, 발행 지연 **5.1ms** |
| #39 MH-Z19B | 실물 통과 | CO2 452~690ppm (sensor-01 한정) |
| #40 BME680 | 실물 통과 | 24.5°C / 60.9% / 1008.2hPa. **iaq_accuracy 0→1 (8분 19초)** |
| #41 ADS1115+MQ | 실물 통과 | 0x48 인식, MQ 3종 원시값 발행 |
| #49 통신 안정성 | 실물 통과(1노드) | 43분 연속, 손실·중복·재연결 0 |
| #123 연결 표시 | 부수 확인 | offline 표시가 실제 상태와 일치 |
| #160 IDW 캡션 | 부수 확인 | 화면에 캡션 표시됨 |

### UWB — 오전 판정을 뒤집었습니다

오전에 "펌웨어에 DWM1000 드라이버가 없어 UWB 전 항목 판정 불가"라고 기록했으나
**틀렸습니다.** 드라이버는 다른 컴퓨터에서 구현돼 GitHub 에 있었고, 하드웨어도
살아 있습니다:

```
[DWM1000] role=anchor, eui=02:00:22:EA:82:60:3B:9C, short=2,
          device=DECA - model: 1, version: 3, revision: 0, ready=true
```

`device=DECA` 는 DecaWave 칩이 자기 식별자를 반환했다는 뜻 — SPI·전원·통신 정상.
`"dwm1000":"valid"` 로 발행됩니다.

**다만 sensor-03 은 `device=DFCA` 로 읽힙니다 (E→F, 1비트 오류).**
동작은 하지만 SPI 신호 품질이 아슬아슬하다는 신호입니다. 나중에 거리값이 튀면
이것을 의심하세요.

**거리 측정에는 앵커 2개 이상, 위치 계산에는 3~4개가 필요합니다.**
앵커를 더 올리면 `wearable/+/ranging` 발행이 시작될 수 있습니다 (미확인).

---

## 6. 재현 불가 (하드웨어/구현 부재)

| 항목 | 사유 |
|---|---|
| #86 자율 진동 | `include/wearable/local_alert.h`·`vibration_*.h` 가 `src/` 에서 참조 0건 — **미배선** |
| #11 #43 낙상/IMU | MPU-6050(`0x68`) I2C 스캔에 없음 — 미배선 |
| #113 O2 fail-safe | O2 가 0.00 이라 정상값 상태에서의 절단 시험 불가 |

**#113 부분 관찰**: O2 가 invalid 인 상태에서 fail-safe 는 계약대로 동작했습니다.
`o2_pct` 미발행 + `quality.sensors.sen0322 == "error"` + `data: {}`.
판정 기준 4개 중 2개는 확인된 셈이나, **정상값(20.9%) 상태에서 물리 절단으로
다시 해야 정식 판정입니다.**

> 주의: SEN0322 fail-safe 는 `sen0322_driver.cpp:49` 의 **반환값 범위 검사
> (`<=0 || >30`)뿐**이고 I2C ACK 확인이 없습니다. 라이브러리가 0~30 범위의 그럴듯한
> 값을 주면 그대로 정상 발행됩니다. 코드로는 결과를 예측할 수 없어 실물 절단
> 시험이 반드시 필요합니다.

---

## 7. 현재 하드웨어 상태

| 보드 시리얼 | 노드 | 상태 |
|---|---|---|
| A803A1A4… | sensor-01 | **정상 가동 중** (외부 전원, 무선). CO2·온습도·MQ 전부 수집 |
| (COM8 연결분) | sensor-02 | CO2 미수신(루프백). ADS1115·BME680·DWM1000 정상 |
| 0224DA93… | sensor-03 | **진단 스케치가 올라가 있음 — 펌웨어 재플래시 필요** |
| 469A05E2… | wearable | SEN0322 읽기 실패. MPU-6050 미배선 |

sensor-03 보드 복구:

```bash
cd /c/hp015build/firmware
python -m platformio run -e sensor-03 -t upload --upload-port COM<N>
```

네트워크: iPad 핫스팟 `iPad (74)` (2.4GHz, Channel 6). 노트북 `172.20.10.13`.
**ESP32 는 2.4GHz 전용** — iOS 핫스팟은 "최대 호환성"을 켜야 합니다.

`firmware/include/config/network_config.local.h` 는 머신별 파일이며
`firmware/.gitignore` 에 등록되어 커밋되지 않습니다. 새 환경에서는 직접 작성하세요.

---

## 8. 인프라 / 도구

```bash
cd docker && docker compose up -d      # timescaledb, mosquitto, backend, frontend
curl -s localhost:8000/health          # {"status":"ok",...}
curl -s localhost:8000/api/metrics     # 계획서의 /metrics 는 오답. /api/metrics 입니다
```

대시보드: `localhost:5173`

### 판정 도구 (`scripts/hw/`)

```bash
scripts/hw/tap.sh [토픽]    # 브로커 tap → test_results/.../mqtt_tap.jsonl
scripts/hw/check.sh [노드]  # DB 판정 일괄 (sensor_data / node_status / alert_events / metrics)
scripts/hw/r0.sh [분]       # MQ R0 후보 + 분 단위 드리프트 추이
```

로컬에 `mosquitto_sub`/`psql` 이 없어 `docker exec` 로 컨테이너 것을 씁니다.
저장소에는 `scripts/hw_verify.py`(PR #171)도 있으나 이번 세션에서는 로컬 저장소가
git 이 아니어서 받을 수 없었습니다 — **다음 세션에서는 그쪽을 쓰면 됩니다.**

### 증거

```
test_results/hardware/2026-08-19/
  result_summary.md          판정 본문 (589줄)
  csv/01~06_*.csv            측정값 (요약통계/원시/피벗/R0추이/경보/노드상태)
  serial_*.log               시리얼 로그
  mqtt_tap.jsonl.gz          MQTT 원본 (11MB → 599KB)
  db_checks.txt
```

CSV 는 UTF-8 BOM 으로 저장해 엑셀에서 바로 열립니다.
**차트용은 `03_시계열_피벗.csv`** (1초 단위, metric 이 열로 펼쳐짐).

---

## 9. 데이터 해석 주의

**`h2s_rs_ohm` 의 전체 CV 81.65% 를 그대로 인용하면 안 됩니다.**
센서 불안정이 아니라 06:02 창가 이동에 따른 환경 변화입니다.

```
06:01 이전  Rs 약  4,400 Ω  (실내)
06:03 이후  Rs 약 21,000 Ω  (창가)
```

실내 미량 H2S 가 사라져 저항이 오른 것으로 **센서가 정상 반응한 증거**입니다.
이동 후 구간만 계산하면 CV 2.74%. 보고서에는 이동 시점(06:02)으로 분리해 기재하세요.

DB 보존: `sensor_data` 원시 30일 / `sensor_data_1min` 영구 / `alert_events` 영구.

---

## 10. 다음 세션 권장 순서

1. **MH-Z19B 배선 수정** (§4.1) — sensor-01 과 비교. 이게 풀려야 다중 노드 CO2 가 열립니다
2. **sensor-03 펌웨어 복구** (§7) — 진단 스케치가 올라가 있습니다
3. **SEN0322 프로브 확인** (§4.2) — #113 safety-critical 이 여기 막혀 있습니다
4. **R0 기입 판단** (§4.3) — 값은 준비됨. 넣으면 CO·H2S ppm 이 화면에 뜹니다
5. **4노드 동시 30분 수집** (#49 정식) — 지금은 1노드 43분까지만 확인
6. **경보 시험** — #54(CO2 1000ppm 3초 유지) #55(히스테리시스) #67(화면까지 E2E 지연)
7. **UWB 앵커 3개 이상** 올려 `wearable/+/ranging` 발행 확인
8. **열화상 노드** (§4.4) — 웨어러블과 같은 방식으로 계약·구독 정리

### 안전 수칙 (계획서 §13, 타협 없음)

```
CO2 2,000ppm 도달       → 즉시 중단 + 전체 환기
어지러움·두통 호소 1인   → 즉시 중단
CO2 1,000ppm 도달 후     → 최대 15분 이내 종료
최소 인원               → 안전 감독 포함 3인
```

---

## 11. 계획서(`HW_SESSION_PLAN.md`) 오류 정정

| 위치 | 계획서 | 실제 |
|---|---|---|
| §4 B-6 | `localhost:8000/metrics` | **`/api/metrics`** (`routers/health.py:21`). `/metrics` 는 404 |
| §1.1 §6 | `PLATFORMIO_CORE_DIR=.../.pio-core` | 지정 시 툴체인 1.2GB 재다운로드. 기본 코어를 쓸 것 |
| §1.4 | `git worktree add ... tools/hw-verification` | 당시 로컬이 git 이 아니어서 불가. 지금은 `scripts/hw_verify.py` 가 저장소에 있음 |
| §8 | "UWB 판정 불가 — 드라이버 부재" | **오류.** 드라이버 존재하며 하드웨어 동작 확인 (§5) |
| §3 §10 §11 | `mosquitto_sub` / `psql` 직접 호출 | 미설치 환경에서는 `docker exec` 경유 |
