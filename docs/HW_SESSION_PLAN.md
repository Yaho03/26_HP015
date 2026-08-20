# 하드웨어 검증 세션 계획 (2026-08-19)

작성 2026-08-18 · 로컬 상태 기준

---

## 0. 한 장 요약

```
전체 이슈             139건 (열림 49 / 닫힘 90)  → 전수 인벤토리는 §14
실물 검증 필요         28건
당일 판정 가능         23건
당일 판정 불가          5건  (UWB 4 + 열화상 1)
최우선 블로커          #107  — 막히면 그날 전체가 막힌다
```

**오늘 밤 할 일은 하나뿐입니다 → §1.3 R0 교정 시작.**
MQ 센서는 예열에만 24시간이 걸립니다. 내일 아침에 시작하면 CO·H₂S는 못 봅니다.

**코드는 오늘 밤에 건드리지 마세요.** 알려진 결함이 하나 있지만(§1.5) NTP만
붙으면 발동하지 않고, 고치는 쪽이 내일 블로커를 깨뜨릴 위험이 더 큽니다.

---

## 1. 전날 준비 (오늘)

### 1.1 펌웨어 상태 확인

브랜치 `codex-hw-firmware-review-fixes` (워크트리 `.worktrees/hw-firmware-review-fixes`)에
커밋 3개가 쌓여 있습니다. **원격에 없고 PR도 없습니다** — 실물 검증 후에 냅니다.

| 커밋 | 내용 | 확인 |
|---|---|---|
| `2d4136c` | NTP 재시도 + 미동기 시 발행 보류 / `co_ppm`·`h2s_ppm` 발행 / O₂ `Sen0322Driver` 경유 | 코드 확인 |
| `1b73d33` | R0 노드별 분리 / `calibration.h` 복원 / `[MQ CAL]` 교정 보조 출력 / lib_deps 9개 버전 고정 | 코드 확인 + **빌드 6종 직접 재실행** |
| `4a4bd3d` | R0 후보 출력에 보드 uptime·예열 확인 문구 추가 | **빌드 6종 직접 재실행** |

빌드는 확인됐습니다. **시리얼 출력과 실물 동작은 확인 안 됐습니다.**

```bash
cd .worktrees/hw-firmware-review-fixes/firmware
PLATFORMIO_CORE_DIR=/Users/choihwanseok/26_HP015/firmware/.pio-core pio run -e sensor-01
```

### 1.2 인프라 기동 확인

```bash
docker compose -f docker/docker-compose.yml ps     # timescaledb, mosquitto 둘 다 healthy
curl -s localhost:8000/health | jq                 # status: "ok"
```

`status`가 `degraded`면 MQTT 인증이나 DB가 죽은 것입니다. **내일 아침에 이걸 디버깅하면 하루가 날아갑니다.**

### 1.3 ★ MQ 센서 R0 교정 시작 — 오늘 밤 필수

CO·H₂S 경보는 R0 값 없이는 **영원히 발화하지 않습니다.** 펌웨어가
`r0Ohm > 0` 일 때만 `co_ppm`을 발행하고, 현재 빌드 플래그 기본값은 `0.0`입니다.

R0는 **센서 개체마다 다릅니다.** `platformio.ini`에 `sensor-01`~`04` 각각
별도로 들어갑니다 — 네 벌을 따로 측정해야 합니다.

```
[env:sensor-01]                [env:sensor-02] ... 04 도 동일
  -D MQ7_R0_OHM=0.0            ← 노드마다 다른 값이 들어갑니다
  -D MQ136_R0_OHM=0.0
  -D MQ2_R0_OHM=0.0
```

절차 (`docs/03_HARDWARE_DESIGN.md` 교정 절, 이슈 #48):

1. 센서를 **청정 공기**(실외 또는 환기된 곳)에 노출하고 전원 인가
2. 예열 — **MQ-7 최소 24시간, MQ-136 48시간**
3. 시리얼을 보면 10초마다 안정도가 찍힙니다

   ```
   [MQ CAL] mq7 rs=12400.00 avg60s=12380.00 spread=1.20% r0_candidate=450.18 | mq136 ... | mq2 ...
   ```

4. 5분간 안정되면 R0 후보가 뜹니다. **펌웨어가 계산해주므로 직접 나눌 필요 없습니다**

   ```
   [MQ CAL] mq7 5분간 안정. R0 후보: 450.18 ohm
            보드 uptime 00:06:12 — 보드 기준입니다. 센서 예열 시간이 아닙니다.
            MQ-7 24h / MQ-136 48h 예열이 끝났는지 직접 확인한 뒤에만
            platformio.ini 의 해당 노드 R0 에 옮겨 적으세요.
   ```

5. 해당 노드 `[env:sensor-0N]` 에 기입 → 재빌드 → 재업로드

> ⚠️ **`보드 uptime` 을 반드시 보세요.** 안정 판정은 "Rs가 흔들리지 않는다"는
> 뜻일 뿐, 예열이 끝났다는 뜻이 아닙니다. **차가운 센서도 6분이면 안정 판정에
> 들어갑니다.** 예열 안 된 값을 넣으면 `calibration_status`가 `"calibrated"`가
> 되면서 **틀린 ppm이 정상값으로 발행됩니다** — 미교정보다 나쁩니다.
>
> 보드는 센서가 언제부터 전원을 받았는지 알 수 없습니다. **예열 완료 여부는
> 사람만 압니다.**

**시간이 없으면**: CO·H₂S는 `uncalibrated` 상태로 두고 raw ADC만 수집하세요.
그날 판정은 "미교정으로 판정 보류"로 남기면 됩니다. **거짓 ppm을 내보내는 것보다 낫습니다.**

### 1.4 판정 도구 준비

PR #171에 만들어둔 도구입니다. 현장에서 SQL을 짜지 않아도 됩니다.

```bash
git worktree add /tmp/hw-verify tools/hw-verification
cd /tmp/hw-verify && python scripts/hw_verify.py --help
```

환경변수는 `backend/.env`와 같은 키를 씁니다 (`MQTT_HOST/PORT/USERNAME/PASSWORD`, `TIMESCALE_URL`).

> ⚠️ 기존 래퍼 `/private/tmp/hp015_hw_tap_sensor_01.sh` 는 `/private/tmp/26_HP015-hw-verify/`
> 를 가리킵니다. **macOS 는 재부팅 시 `/private/tmp` 를 비웁니다.** 내일 아침에
> 스크립트가 사라져 있을 수 있으니, 위 명령으로 워크트리를 다시 만들 수 있다는 것을
> 기억하세요.

### 1.5 알려진 결함 — 연결 끊김 감지 (오늘은 고치지 마세요)

**NTP 미동기 상태에서만 발동합니다.** 확인해둔 사실만 적습니다.

```
firmware  connectionPayload()  →  {"status":"offline","timestamp":null}
backend   _parse_ts(None)      →  InvalidMessage: timestamp must be a string
```

LWT 페이로드는 **MQTT 연결 시점에 한 번** 브로커에 등록됩니다. 부팅 때 NTP 가
안 붙어 있으면 그 LWT 는 `timestamp: null` 로 굳고, 나중에 NTP 가 동기돼도
갱신되지 않습니다. 그 상태로 노드가 죽으면 **offline 이 반영되지 않습니다.**

**그런데 오늘 밤 고치면 안 됩니다. 이유가 셋입니다.**

1. **NTP 만 붙으면 발동하지 않습니다.** 부팅 순서가 `WiFi → NTP → MQTT 연결`
   이라, 동기가 되면 LWT 에 정상 시각이 박힙니다
2. **새 결함이 아닙니다.** 수정 전에는 1970 년 timestamp 가 stale 가드에 막혀
   똑같이 유실됐습니다. 나아지지도 나빠지지도 않았습니다
3. **고치는 게 더 위험합니다.** 수정 방향(NTP 동기 전 MQTT 연결 보류)이
   **연결 시퀀스를 건드립니다.** 그게 내일 최우선 블로커 `#107` 이 지나갈
   경로입니다. 보드 없이 밤에 고쳐서 `#107` 이 깨지면 그날 전체가 막힙니다

**내일 아침에 이것만 하세요** (5초):

```bash
nc -vzu pool.ntp.org 123
```

| 결과 | 조치 |
|---|---|
| 성공 | 이 결함은 발동 안 함. **그냥 진행** |
| 실패 | 폰 핫스팟으로 전환. 안 그러면 telemetry 자체가 안 옵니다 |

> NTP 가 막히면 이 결함보다 큰 문제가 먼저 옵니다 — 동기 전엔 telemetry 를
> 아예 발행하지 않도록 돼 있어 **화면에 아무것도 안 뜹니다.**

**세션 후에 고치고, 검증 결과와 함께 PR 에 넣으세요.**

### 1.6 준비물 체크리스트

- [ ] ESP32 보드 6개 (센서 4 + 웨어러블 1 + 열화상 1), USB 케이블
- [ ] 현장 WiFi SSID/PW → `firmware/include/config/network_config.local.h` 에 기입
- [ ] 브로커가 **노트북**이면 노트북 IP를 `MQTT_BROKER` 에 기입 (localhost 아님)
- [ ] CO₂ 카트리지, 에탄올 100mL 이하, 소화기
- [ ] 줄자 (UWB 앵커 실측용 — 앵커가 있다면)
- [ ] **안전 감독 1인 포함 최소 3인**

---

## 2. 당일 진행 순서

의존 관계가 한 방향입니다. **위에서부터 막히면 아래는 시도하지 마세요.**

```
A. 백엔드 전송 (E2E)    #107 #103 #104     ← 여기가 막히면 그날 끝
        ↓
B. 센서 정확도·교정      #39~#42 #48 #49
        ↓
C. 웨어러블 안전         #113 #86 #11
        ↓
D. 경보 엔진             #54 #55 #56 #67
        ↓
E. 화면·트윈 확인        #159 #160 #162
        ↓
F. UWB / 위치            #68 #69 #70 #121  ← 오늘은 불가 (§7)
G. 열화상                미배선            ← 오늘은 불가 (§8)
```

---

## 3. A. 백엔드 전송 — 최우선

### A-1. #107 센서 노드 E2E 파이프라인

**이것 하나가 나머지 전부의 전제입니다.**

판정 기준 — 실물 `sensor-01`이 발행한 데이터가 `sensor_data` 테이블에 INSERT 될 것.

```bash
# 1) 브로커 tap 을 먼저 켠다 (보드 전원 인가 전에)
python scripts/hw_verify.py tap --node sensor-01

# 2) 보드 전원 인가 → 시리얼 모니터로 진행 확인
pio device monitor -b 115200
```

시리얼에서 순서대로 나와야 하는 것:

```
[WiFi] Connected.               ← 안 나오면 SSID/PW 또는 2.4GHz 여부 확인
[TIME] Synced: true             ← false 면 §A-2 로
[MQTT] Connected.
[MQTT] Online status published (QoS 1).
[MQTT GAS] {"schema_version":"1.1",...}
```

```bash
# 3) 판정
python scripts/hw_verify.py check --node sensor-01
```

**막혔을 때 순서대로 의심할 것**

| 증상 | 확인 |
|---|---|
| WiFi 연결 실패 | ESP32는 **2.4GHz만** 됩니다. 5GHz 전용 AP면 안 붙습니다 |
| MQTT 연결 실패 | `MQTT_BROKER`가 노트북 IP인지 (localhost면 보드에서 자기 자신을 찾습니다) |
| 연결됐는데 DB 비어있음 | `curl localhost:8000/health` → `mqtt.connected` 확인 |
| GAS 로그는 뜨는데 DB 비어있음 | 백엔드 로그에서 `InvalidMessage` 검색 → §A-2 |

### A-2. #103 NTP 시각 동기

판정 기준 — `sampled_at`이 UTC 벽시계와 **±2초 이내**.

Codex 수정으로 `loop()`에서 재시도하지만, **현장 네트워크가 NTP(UDP 123)를 막으면 영원히 동기가 안 됩니다.**

```bash
# 보드에서 NTP 가 나가는지 노트북에서 먼저 확인
nc -vzu pool.ntp.org 123
```

막혀 있으면 노트북을 NTP 서버로 쓰거나, 폰 핫스팟을 쓰세요.
**동기 실패 시 펌웨어는 발행을 보류합니다 — DB가 비어도 정상 동작입니다.**

### A-3. #104 message_id 재부팅 중복

판정 기준 — **재부팅 3회** 후 부팅 세션 간 `message_id` 교집합이 **0건**.

tap을 켜 둔 채로 보드를 3번 재부팅한 뒤 `check`를 돌리면 됩니다.

> DB로는 검증할 수 없습니다. `message_id`가 재사용되면 백엔드가 중복으로 보고
> 조용히 버려서, **사고일수록 DB에 흔적이 적게 남습니다.** 그래서 브로커를 직접 뜹니다.

### A-4. 연결 끊김 감지 (#52 / #111 / #153)

판정 기준 — 보드 전원을 뽑으면 대시보드가 **offline**으로 바뀔 것.

```bash
# 전원 차단 후
psql $TIMESCALE_URL -c "SELECT node_id, connection_status, connection_updated_at FROM node_status;"
```

⚠️ **PR #153이 아직 main에 없습니다.** LWT의 timestamp가 online보다 과거라
stale 가드에 막혀 **offline이 반영되지 않을 수 있습니다.** 그러면 그게 #153이
필요하다는 실물 증거입니다 — 결과를 기록해두세요.

---

## 4. B. 센서 정확도·교정

### B-1. #39 MH-Z19B (CO₂)

- 전원 인가 후 **최소 5분 예열**. 그 전 값은 정량 판정에서 제외
- 외기 기준값 약 400ppm 확인
- 사람이 밀폐 공간에 들어가면 상승하는지
- ⚠️ **2,000ppm 도달 시 즉시 중단·환기** (ASHRAE 62.1)

### B-2. #40 BME680 (온습도·기압·IAQ)

- BSEC burn-in 최소 5분, 정확도 향상엔 1시간
- `iaq_accuracy`가 0 → 1 → 2 로 올라가는지 확인 (0이면 아직 학습 중)

### B-3. #41 ADS1115 + MQ-7/136/2

- I2C 주소 `0x48` 인식 확인
- **§1.3 교정을 했다면** `co_ppm`·`h2s_ppm`이 페이로드에 실리는지
- 교정 안 했다면 `co_calibration_status: "uncalibrated"` 가 뜨는 것이 **정상**

### B-4. #42 SEN0322 (O₂) — 웨어러블

- 대기 중 약 20.9% 근처인지
- ⚠️ 이 센서의 fail-safe는 §5에서 별도로 봅니다

### B-5. #48 센서 교정

§1.3에서 시작한 R0 교정의 **결과를 여기서 확정**합니다.
빌드 플래그에 기입 → 재빌드 → 재업로드 → `co_ppm` 발행 확인.

### B-6. #49 EXP-1 센서 통신 안정성

- 4개 노드 동시 가동 상태로 **최소 30분** 연속 수집
- 판정: 메시지 손실률, 중복률, 재연결 횟수

```bash
psql $TIMESCALE_URL -c "
SELECT node_id, count(*), min(time), max(time)
FROM sensor_data WHERE time > now() - interval '30 min' GROUP BY node_id;"
curl -s localhost:8000/metrics | jq   # mqtt_reconnects, messages_processed
```

---

## 5. C. 웨어러블 안전

### C-1. #113 SEN0322 fail-safe ★ safety-critical

**이 프로젝트에서 가장 중요한 검증입니다.** 센서가 고장 났는데 정상값을
반환하면, 산소 결핍 상태에서 화면이 초록색으로 남습니다.

판정 기준 — I2C를 물리적으로 끊었을 때:

- [ ] `o2_pct`가 **발행되지 않을 것** (20.9% 같은 정상값이 나오면 **실패**)
- [ ] `quality.sensors.sen0322` 가 `"error"` 일 것
- [ ] 웨어러블이 **자율 진동**할 것 (#86)
- [ ] 대시보드가 `unknown`(판정 불가)로 표시할 것 (#165)

```bash
mosquitto_sub -h $MQTT_HOST -t 'wearable/+/vital' -v
# 이 상태에서 SEN0322 의 SDA 또는 전원선을 뽑는다
```

### C-2. #86 백엔드 장애 시 자율 진동

판정 기준 — **백엔드를 죽여도** 웨어러블이 스스로 진동할 것.

```bash
docker compose -f docker/docker-compose.yml stop mosquitto
# 이 상태에서 O2 를 위험 수준으로 만들거나 센서를 뽑는다
```

⚠️ 리뷰에서 확인한 바로는 `local_alert.h`·`vibration_*.h`가
`firmware/include/wearable/` 에 **보존만 되어 있고 `src/` 어디서도 참조하지 않습니다.**
배선이 안 돼 있으면 이 항목은 **판정 불가**입니다. 먼저 시리얼로 확인하세요.

### C-3. #11 낙상 감지 (MPU-6050)

- 웨어러블을 떨어뜨리거나 급격히 기울여 `magnitude` 급변 확인
- `wearable/wearable-01/imu` 수신 확인
- 낙상 판정 알고리즘이 백엔드에 있는지 먼저 확인 필요

---

## 6. D. 경보 엔진 / 임계값 / 추세

**소프트웨어는 이미 주입 데이터로 검증됐습니다.** 여기서는 *실제 센서 값으로도*
같은 동작이 나오는지만 봅니다.

### D-1. #54 시간 기반 판정 (enter_for_ms)

- CO₂를 1,000ppm 이상으로 올리고 **3초 유지**해야 L1이 뜨는지
- 순간 스파이크로는 안 뜨는지 (오탐 방지)

### D-2. #55 Hysteresis / De-escalation

- L1 진입 후 값을 낮춰 **exit 임계값 아래로 5초** 유지 → 해제되는지
- 임계값 근처에서 깜빡이지 않는지

### D-3. #56 O₂ 양방향 (o2_low / o2_high)

- 낮은 쪽만이 아니라 **높은 쪽(23.5% 초과)도** 경보가 뜨는지

### D-4. #67 EXP-4 E2E 경보 지연 ★

판정 기준 — **센서 임계값 초과 시점 → 화면 경보 표시**까지 걸린 시간.

```bash
# 경보 발생 시각 확인
psql $TIMESCALE_URL -c "
SELECT source_node_id, level, activated_at, published_at, published_at - activated_at AS delay
FROM alert_events ORDER BY activated_at DESC LIMIT 10;"
```

측정 구간을 나눠서 기록하세요: 센서 샘플링 → MQTT → DB → WS → 화면 렌더.

### D-5. #13 / #162 추세 기반 선제 표시

- 실제 CO₂ 상승 곡선에서 도달 예측 시각이 표시되는지
- 10분 창 · 최소 표본 4개가 필요하므로 **최소 10분은 수집**해야 합니다

---

## 7. E. 화면 / 트윈 시각 확인

어제 로컬에서 확인했지만 **실제 센서 데이터로는 처음**입니다.

| 이슈 | 확인할 것 |
|---|---|
| #159 좌표계 | 작업자 마커가 선체 안에서 실제 이동 방향과 맞게 움직이는지 |
| #160 평면도·IDW | 원거리에서 판독되는지, IDW 캡션이 보이는지 |
| #164 스크롤 | 1440x900에서 스크롤이 없는지 (PR #172로 수정됨) |
| #165 fail-safe | 임계값 미로딩 시 `unknown` 표시 |
| #123 연결 표시 | 사이드바 BE/MQTT/WS 가 실제 상태를 반영하는지 |
| #72~#76 3D 트윈 | 센서 마커 색상, 히트맵, HazardZone, WS 동기화 |

**#160 판독성은 시연 거리에서** 봐야 합니다. 노트북 앞이 아니라 **2~3m 떨어져서** 보세요.

---

## 8. F. UWB / 위치 — 오늘은 판정 불가

**펌웨어에 DWM1000 드라이버가 없습니다.**

- 통합된 하드웨어 팀 번들에 UWB 소스가 없습니다
- 기존 `firmware/src/sensors/dwm1000.h` 가 이번 통합에서 **삭제**됩니다
- 펌웨어가 `quality.sensors.dwm1000: "not_connected"` 를 하드코딩합니다
- `wearable/+/ranging` · `/location` 발행자가 없습니다

따라서 **#68 #69 #70 #21 #22 #121 #77 #78 전부 오늘 검증 불가**입니다.

**오늘 할 수 있는 것**

- 앵커 4개 물리 배치 + **줄자로 좌표 실측** → 나중에 ground truth로 씁니다
- DWM1000 모듈 SPI 배선만 해두기
- 백엔드 삼변측량 경로는 `worker_walk_uwb` 주입으로 이미 확인됨 (계산은 정상)

**결정이 필요합니다** — UWB를 되살릴지, 아니면 공모전 범위에서 빼고
"위치는 주입 데이터로 시연"할지. 시간을 보고 판단하세요.

---

## 9. G. 열화상 — 오늘은 판정 불가

`thermal-node`는 빌드만 통과합니다.

- 발행 토픽이 `thermal/thermal-01/summary`·`/status` 인데 **백엔드가 구독하지 않습니다**
- 상태 필드명이 계약과 다름 (`wifi_rssi` vs `wifi_rssi_dbm`)
- `battery_pct`·`free_heap_bytes`·`sensors_online`·`sensors_error` 누락
- LWT 미등록

**백엔드 수정이 같이 필요해서 오늘 범위 밖입니다.** MLX90640 배선과 시리얼 출력
확인까지만 하고, 백엔드 연동은 별도 PR로 처리하세요.

---

## 10. 막혔을 때 — 실패 지점 분리

**실패 자체보다 어디서 실패했는지가 중요합니다.** 위에서부터 하나씩 끊어보세요.

```
① 시리얼에 [MQTT GAS] 가 찍히나?
      아니오 → 펌웨어/센서 문제. ②로 가지 마세요
      예 ↓
② mosquitto_sub 로 브로커까지 오나?
      아니오 → 네트워크/브로커 인증 문제
      예 ↓
③ sensor_data 에 INSERT 되나?
      아니오 → 백엔드 ingest 문제. 로그에서 InvalidMessage 검색
      예 ↓
④ 화면에 값이 뜨나?
      아니오 → WebSocket 또는 프론트 문제
```

각 단계 확인 명령:

```bash
# ②
mosquitto_sub -h $MQTT_HOST -t 'sensors/#' -v
# ③
psql $TIMESCALE_URL -c "SELECT * FROM sensor_data ORDER BY time DESC LIMIT 5;"
# ④
curl -s localhost:8000/health | jq
```

**비교 기준이 필요하면 주입으로 같은 경로를 태워보세요.** 주입은 되는데 실물이
안 되면 문제는 ①②에 있습니다.

```bash
cd experiments/inject
python cli.py --list                                  # 사용 가능한 시나리오
python cli.py --scenario co2_warning --node-id sensor-01
```

> 진입점은 `cli.py` 입니다. `injector.py` 는 라이브러리라 직접 실행되지 않습니다.
> 시나리오 9종: `normal_steady` `worker_walk` `worker_walk_uwb` `gas_spread`
> `co2_warning` `h2s_warning` `o2_low` `fall_detection` `node_offline`

---

## 11. 기록 방법

**나중에 "확인했다"고 말하려면 근거가 남아 있어야 합니다.**

### 판정 표기는 5가지로 구분

애매하게 "확인함"이라고 쓰면 나중에 무엇을 믿을 수 있는지 알 수 없습니다.

```
실물 통과            실제 보드·센서로 확인함
실물 실패            실제로 해봤는데 안 됨
MQTT 주입 검증까지    주입으로만 확인. 실물 아님
로컬 코드 검증까지    빌드·테스트만. 동작 확인 아님
재현 불가            조건을 만들지 못함 (장비 없음 등)
```

### 세션 중 계속 켜 둘 것

```bash
python scripts/hw_verify.py tap --node sensor-01        # 원본 발행 기록
mosquitto_sub -h $MQTT_HOST -t '#' -v | tee /tmp/hw_session_$(date +%m%d).log
```

### 항목마다 남길 것

```text
이슈:
큰 주제:
검증 일시:            검증자:
펌웨어 커밋:          백엔드 커밋:

절차:
1.
2.

관찰 결과:
- 시리얼:
- MQTT:
- 백엔드 로그:
- DB:
- 화면:

판정:
  [ ] 실물 통과   [ ] 실물 실패   [ ] MQTT 주입 검증까지
  [ ] 로컬 코드 검증까지          [ ] 재현 불가

남은 일:
증거 파일:
```

### 증거 파일 구조

```text
test_results/hardware/2026-08-19/
  serial_sensor_01.log ~ 04.log
  serial_wearable_node.log
  serial_thermal_node.log
  mqtt_tap.jsonl
  backend.log
  db_checks.txt
  dashboard_screenshots/
  result_summary.md
```

`test_results/` 는 **커밋 대상이 아닙니다** (`firmware/.gitignore` 에 등록됨).

### 세션 종료 후

```bash
pg_dump $TIMESCALE_URL -t sensor_data -t alert_events -t node_status > /tmp/hw_session_$(date +%m%d).sql
```

---

## 12. 세션 후 처리

1. **PASS 항목** → 해당 이슈에 근거와 함께 댓글, PR 본문에 `Closes #N` 추가
2. **FAIL 항목** → 이슈에 실패 내용 기록, 닫지 말 것
3. **보류 항목** → 왜 보류인지 명시 (교정 미완? 하드웨어 부재?)
4. 펌웨어 PR 생성 — **검증 결과를 본문에 넣어서**

지금 하드웨어 대기 댓글이 달린 이슈: **#103 #104 #107 #113 #121**

---

## 13. 안전 수칙 — 타협 없음

```
CO₂ 2,000ppm 도달       → 즉시 중단 + 전체 환기
어지러움·두통 호소 1인   → 즉시 중단
에탄올 구간              → 화기 금지, 소화기 위치 사전 확인
CO₂ 1,000ppm 도달 후     → 최대 15분 이내 종료
최소 인원                → 안전 감독 포함 3인 (단독·2인 금지)
```

---

## 14. 전체 이슈 인벤토리 (139건)

이슈 전체를 훑어 **실물이 필요한 것과 아닌 것**을 갈랐습니다. 내일은 "실물 확인"
열만 보면 됩니다.

### 실물 확인 필요 — 28건

| 이슈 | 상태 | 주제 | 내일 판정 | 메모 |
|---|---|---|---|---|
| `#107` | 열림 | 펌웨어·전송 | ✅ §3 | **최우선 블로커** |
| `#103` | 열림 | 펌웨어·시간 | ✅ §3 | NTP 동기 후 sampled_at |
| `#104` | 열림 | 펌웨어·재부팅 | ✅ §3 | 재부팅 3회 message_id |
| `#113` | 열림 | 웨어러블·O₂ | ✅ §5 | ★ safety-critical |
| `#110` | 열림 | 위치 필터 | ⛔ | UWB 없이 불가 |
| `#121` | 열림 | 트윈·UWB | ⛔ | 드라이버 부재 |
| `#159` | 열림 | 트윈·좌표 | ✅ §7 | 실제 데이터로 재확인 |
| `#160` | 열림 | 트윈·판독성 | ✅ §7 | 2~3m 떨어져서 볼 것 |
| `#4` | 닫힘 | 센서 노드 펌웨어 | ✅ §4 | 가스/환경 수집 |
| `#5` | 닫힘 | 웨어러블 펌웨어 | ✅ §5 | O₂/IMU 수집 |
| `#7` | 닫힘 | 하드웨어 조립 | ✅ §1 | 배선·교정 |
| `#8` `#49` | 닫힘 | 센서 안정성 | ✅ §4 | 30분 연속 수집 |
| `#11` | 닫힘 | 낙상 감지 | ✅ §5 | IMU 급변 |
| `#12` | 닫힘 | 경보·진동 | ✅ §5 | 진동 패턴 |
| `#39` | 닫힘 | MH-Z19B | ✅ §4 | 5분 예열 후 |
| `#40` | 닫힘 | BME680 | ✅ §4 | BSEC burn-in |
| `#41` | 닫힘 | ADS1115·MQ | ✅ §4 | R0 교정 전제 |
| `#42` | 닫힘 | SEN0322 | ✅ §5 | |
| `#43` | 닫힘 | MPU-6050 | ✅ §5 | |
| `#46` `#47` | 닫힘 | 조립 | ✅ §1 | 노드 4개 + 웨어러블 |
| `#48` | 닫힘 | 센서 교정 | ⚠️ §1.3 | **24h 예열 필요** |
| `#80` `#30` | 닫힘 | IDW 일관성 | ✅ §7 | 실제 센서값으로 |
| `#86` | 닫힘 | 로컬 진동 fail-safe | ⚠️ §5 | 배선 확인 먼저 |
| `#68` `#69` `#21` `#22` `#70` | 닫힘 | UWB | ⛔ §8 | **드라이버 부재** |
| `#77` `#78` `#27` `#28` | 닫힘 | UWB 정확도 | ⛔ §8 | 앵커 실측만 가능 |
| `#73` `#24` | 닫힘 | 좌표 변환 | ✅ §7 | |

### 실물 보조 확인 — 실물이 있으면 더 확실해지는 것

`#96` `#87` `#81` `#31` `#75` `#74` `#72` `#67` `#20` `#63` `#57` `#56` `#52`
`#51` `#45` `#44` `#6` `#16` `#17` `#106` `#111` `#119` `#165`

내일 여유가 있으면 보고, 없으면 주입 검증으로 갈음합니다.

### 소프트웨어 확인으로 충분 — 내일 범위 밖

```
백엔드/API      #9 #50 #53 #54 #55 #58 #59 #60 #102 #108 #109
                #117 #118 #120 #122
프론트엔드      #17~#19 #61~#66 #71 #76 #105 #112 #114 #123
                #126 #127 #162 #164
인프라/CI       #2 #3 #33~#38 #84 #85 #88 #115 #128 #129 #167
시연/주입       #32 #82 #83 #161 #163
인증 (미착수)    #116 #131~#142
문서/정리       #124 #125 #130 #131
```

### 라벨 없는 닫힌 이슈

`#96` `#97` `#98` — 라벨이 없어 목록에서 빠지기 쉽습니다. `#96`(disconnect
reason 옵셔널)만 실물 보조 확인 대상이고 나머지는 소프트웨어 확인입니다.

**환기 담당 1인이 비상 시 창문·문을 즉시 열 수 있도록 상시 대기합니다.**
