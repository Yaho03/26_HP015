# 1차 제출 — 구현 범위 · 검증 결과 · 알려진 한계

작성 2026-08-20 · 기준 브랜치 `fix/monitoring-viewport-fit`

> 제출 양식이 확정되면 이 문서의 §1~§4 를 옮겨 쓰면 된다. §5 는 시연자용이라 제출물에는 넣지 않는다.

---

## 1. 시스템 개요

조선소 밀폐공간(탱크 내부, 이중저 구획) 작업 시 유해가스 누출·산소 결핍·낙상을 실시간 감지해 관리자와 작업자에게 경보하는 IoT 안전 모니터링 시스템.

```
센서 노드 4대 (ESP32)          웨어러블 1대 (ESP32)
  CO2 / CO / H2S / 가스저항       O2 / 낙상 / 진동 알림
  온습도 / 기압 / UWB 앵커        UWB 태그
        │                              │
        └──────── MQTT ────────────────┘
                    │
        백엔드 (FastAPI) → TimescaleDB
                    │
        웹 대시보드 (React) — 실시간 수치 · 경보 · 2D 평면도 · 3D 트윈
```

---

## 2. 구현 범위

| 영역 | 구현 내용 | 상태 |
|---|---|---|
| 펌웨어 | 센서 6종 드라이버, MQTT 발행, NTP 시각 동기, ULID 기반 `message_id`, 재연결·버퍼링 | 동작 |
| 백엔드 | MQTT 수집 → TimescaleDB 적재, 중복·무효 메시지 방어, 경보 판정 엔진(3단계), WebSocket 브로드캐스트, 임계값 API | 동작 |
| 프론트엔드 | 실시간 대시보드, 경보 표시, 2D 평면도 + IDW 농도 보간, 3D 디지털 트윈, 임계값 설정 화면 | 동작 |
| 위치 측위 | UWB DS-TWR 삼변측량 (앵커 4 + 태그 1) | 코드 완료 · 실물 미검증 |
| 작업자 관리 | 작업자 프로필 + 웨어러블 배정 — 경보에 사람 이름 표시 | 동작 |
| 인프라 | Docker Compose 4개 컨테이너(DB·브로커·백엔드·프론트), 마이그레이션 자동 적용 | 동작 |

경보는 3단계다. `level1_caution` → `level2_warning` → `level3_critical`. 각 단계는 진입 임계값과 유지 시간을 함께 본다. 예를 들어 CO2 는 1,000ppm 이 3초간 지속돼야 `level1` 로 올라가고, 5,000ppm 은 즉시 `level3` 다 — 치명적 농도에서 3초를 기다릴 이유가 없다.

---

## 3. 검증 결과

### 3.1 실물 하드웨어 (2026-08-19)

ESP32 실물 4대로 43분간 연속 측정했다.

```
수집 구간   2026-08-19 05:29:29Z ~ 06:12:34Z (43분)
적재 행수   35,178 행 / 16 metric
백엔드 카운터
  messages_processed        35,178
  messages_dropped_invalid       0     ← 스키마 위반 0건
  messages_dropped_duplicate     0
  mqtt_reconnects                0     ← 43분간 재연결 0회
```

주요 측정값의 안정성:

| 항목 | 표본 | 평균 | CV% |
|---|---:|---:|---:|
| `pressure_hpa` | 858 | 1,008.20 hPa | **0.01** |
| `mq2_rs_ohm` | 2,568 | 21,835 Ω | 2.88 |
| `humidity_pct` | 858 | 60.87 % | 3.91 |
| `temperature_c` | 858 | 24.52 ℃ | 4.22 |
| `co_rs_ohm` (MQ-7) | 2,568 | 176,439 Ω | 5.21 |
| `co2_ppm` | 2,266 | 589.61 ppm | 11.32 |

> `h2s_rs_ohm` 의 전 구간 CV 는 81.65% 로 나오지만 **센서 불안정이 아니다.** 06:02 에 보드를 실내에서 창가로 옮겼고 그 시점에 MQ-136 저항이 4,400Ω → 21,000Ω 으로 올랐다. 실내 미량 H2S 가 사라지며 저항이 상승한 것으로, 센서가 환경 변화에 정상 반응한 증거다. 이동 후 구간만 계산하면 CV 2.74%. 보고서에는 이동 시점(06:02)으로 구간을 나눠 기재해야 한다.

실물로 통과를 확인한 항목:

- 센서 노드 E2E 파이프라인 (센서 → MQTT → 백엔드 → DB → 대시보드)
- NTP 시각 동기 — 하드코딩된 시각이 아닌 실제 UTC
- 연결 끊김 감지 → 경보 → 노드 복귀 시 해제

근거: [`test_results/hardware/2026-08-19/result_summary.md`](../test_results/hardware/2026-08-19/result_summary.md) (589줄, 이슈별 판정)
상세 경위: [`docs/HW_SESSION_HANDOFF_20260819.md`](HW_SESSION_HANDOFF_20260819.md)

### 3.2 소프트웨어 E2E (2026-08-20)

Docker 스택을 올리고 주입 시나리오로 전 경로를 확인했다.

```
컨테이너   timescaledb(healthy) · mosquitto · backend · frontend  모두 정상
/health    {"status":"ok","mqtt":{"connected":true},"db":{"pool_initialized":true}}
```

CO2 상승 시나리오 주입 결과 — 값에 따라 3단계가 순서대로 발화했다.

| 시각 | 주입값 | 결과 |
|---|---:|---|
| 06:24:26~29 | 1,100 ppm | 3초 유지 후 `level1_caution` 발화 |
| 06:24:30~33 | 2,100 ppm | 3초 유지 후 `level2_warning` 발화 |
| 06:24:34 | 5,500 ppm | 즉시 `level3_critical` 발화 (유지시간 0) |

주입 → MQTT → 적재 → 경보 판정 → 발행까지 전 구간이 동작한다.

---

## 4. 알려진 한계

솔직하게 적는다. 아래는 현재 동작하지 않거나 검증하지 못한 것이다.

### 4.1 MH-Z19B (CO2) — 보드 4대 중 1대만 안정

| 노드 | MH-Z19B | 그 외 센서 |
|---|---|---|
| sensor-01 | 값 고정 (불량) | 전부 정상 |
| sensor-02 | **정상** | 전부 정상 |
| sensor-03 | 무응답 | 전부 정상 |
| sensor-04 | 무응답 | 전부 정상 |

원인은 규명하지 못했다. 한 보드는 기본 핀(16/17)에서 무응답이지만 32/33 에서는 정상 동작했다 — WROOM 이라 PSRAM 충돌은 아니다. 그런 보드를 위해 핀을 빌드 플래그(`MHZ19B_RX`/`MHZ19B_TX`)로 뺐다. 진단 절차는 인수인계 문서 §12.7 에 5단계로 정리했다.

**ADS1115 · BME680 · MQ-2 · MQ-7 · MQ-136 은 네 보드 모두 정상이다.** 문제는 MH-Z19B 에만 있다.

### 4.2 SEN0322 (O2) — I2C 미검출

웨어러블의 산소 센서가 I2C 버스에서 검출되지 않아 O2 측정을 보류했다. 시도한 것과 결과:

| 시도 | 결과 |
|---|---|
| 0x73 재probe | FAIL |
| 0x70~0x72 형제 주소 | FAIL |
| 0x00 제너럴 콜 | FAIL |
| SCL 16회 수동 클럭 + STOP (버스 리커버리) | FAIL |
| I2C 클럭 400 / 20 / 10 kHz 강하 | FAIL |

읽기 실패 시 정상값을 반환하지 않고 `valid = false` 로 내리는 fail-safe 는 구현했다. 변환식 정확도 검증은 하드웨어 확보 후로 미뤘다.

### 4.3 MPU-6050 (낙상) — 미배선

물리적으로 연결되지 않았다. 낙상 감지는 코드만 있고 실물 검증이 없다.

### 4.4 UWB 위치 측위 — 실물 미검증

DS-TWR 삼변측량 코드는 완료했고 백엔드 프로덕션 경로에도 연결했다. 다만 DWM1000 모듈 실물로는 검증하지 못했다.

### 4.5 인증 없음

전 엔드포인트가 무인증이다. 안전 임계값을 누구나 변경할 수 있다. 데모 제어 API 도 마찬가지라 기본값을 꺼둔 상태로 두고 시연 때만 켠다.

### 4.6 경보 이력 누적 (2026-08-20 발견)

**판정 엔진 자체는 정상이다.** 값이 정상으로 돌아오면 단계를 순서대로 내려온다 — 백엔드 로그로 확인했다.

```
06:25:39  level3_critical → level2_warning
06:25:47  level2_warning  → level1_caution
06:25:54  level1_caution  → normal
```

문제는 그 기록 방식이다. 단계를 내려올 때마다 `alert_events` 에 **새 행이 `active` 로 추가되고, 원래의 상위 레벨 행은 `resolved` 로 갱신되지 않는다.** 그래서 CO2 한 번 상승·복귀에 6개 행이 남고 그중 5개가 `active` 로 고정된다.

여기에 더해 `alerts/state/<node>/<metric>` 토픽이 **retained** 라, 브로커에 남은 옛 경보가 새로 접속하는 대시보드에 그대로 재생된다. 실제로 8/16~8/17 의 미해제 경보 6건이 남아 있었다.

화면에서는 이렇게 나타난다 — 측정값이 정상으로 돌아와 노드 카드는 전부 `정상` 인데 상단 `ALERTS` 카운터만 남아, 요약 바(`4 정상 / 0 주의 / 0 경고 / 0 위험`)와 어긋난다.

시연 전 정리 절차는 §5.1 에 있다. 근본 수정은 미완이며 별도 이슈로 다뤄야 한다.

---

## 5. 시연 절차 (시연자용)

> **밀폐공간 안전 시스템은 실제 유해가스를 주입해 시연할 수 없다.** 따라서 MQTT 주입 시나리오로 경보 경로를 보여준다. 이는 이 분야의 표준 시연 방식이며, 영상·발표에서 **"주입 시나리오로 검증합니다"** 라고 반드시 밝힌다. 실측 데이터는 §3.1 의 43분 연속 측정으로 별도 제시한다.

### 5.1 사전 준비

```bash
cd docker && docker compose up -d
curl localhost:8000/health
```

`{"status":"ok", "mqtt":{"connected":true}, "db":{"pool_initialized":true}}` 가 나와야 한다.

**옛 경보를 비운다 (§4.6 때문에 필수). 두 곳 다 지워야 한다 — DB 와 브로커의 retained 메시지.**

```bash
scripts/hw/reset_alerts.sh
```

이걸 안 하면 대시보드에 며칠 전 경보가 그대로 떠 있는 상태로 시연하게 된다.

데모 제어 API 를 쓸 경우에만 `docker/.env` 에 `DEMO_CONTROL_ENABLED=true` 를 넣고 백엔드를 재시작한다. 시연이 끝나면 되돌린다.

### 5.2 시연 순서

주입 도구는 `backend/.venv` 의 파이썬을 쓴다 (`paho-mqtt` 가 거기 설치돼 있다).

```bash
export MQTT_USERNAME=hp015 MQTT_PASSWORD=<docker/.env 의 값>
```

| 순서 | 명령 | 화면에서 보여줄 것 |
|---|---|---|
| ① 정상 상태 | `backend/.venv/bin/python -m experiments.inject.cli --scenario normal_steady --node-id sensor-01,sensor-02,sensor-03,sensor-04 --duration 60` | 노드 4개 실시간 수치, 전부 정상 |
| ② 가스 상승 | `... --scenario co2_warning --node-id sensor-01` | L1 → L2 → L3 단계 상승, 경보 카드 |
| ③ 작업자 위치 | `... --scenario worker_walk_uwb --node-id wearable-01` | 2D 평면도 마커 이동, 3D 트윈 |
| ④ 확산 | `... --scenario gas_spread --node-id sensor-01,sensor-02` | IDW 농도 히트맵 |
| ⑤ 연결 끊김 | `... --scenario node_offline --node-id sensor-03` | 노드 오프라인 표시 + 경보 |

전체 시나리오: `normal_steady` `worker_walk` `gas_spread` `co2_warning` `h2s_warning` `fall_detection` `o2_low` `node_offline` `worker_walk_uwb`

### 5.3 리허설 시 확인

- ②에서 L3 발화 후 ①로 돌아가면 경보가 화면에 남는다 (§4.6). 시나리오 사이에 DB 를 비우거나, 순서를 되돌아가지 않게 구성한다
- 브라우저는 `localhost:5173`

---

## 6. 저장소 안내

| 위치 | 내용 |
|---|---|
| `docs/` | 설계 문서 (PRD, 아키텍처, 데이터 계약, 경보 규칙 등) |
| `docs/HW_SESSION_HANDOFF_20260819.md` | 하드웨어 검증 세션 인수인계 (§1~§13) |
| `test_results/hardware/2026-08-19/result_summary.md` | 이슈별 판정 본문 |
| `scripts/hw/` | 하드웨어 판정 도구 |
| `experiments/inject/` | MQTT 주입 시나리오 |

원시 측정 데이터(시리얼 로그, CSV, MQTT 캡처)는 용량 문제로 저장소에서 분리했다. 필요 시 별도 전달한다.
