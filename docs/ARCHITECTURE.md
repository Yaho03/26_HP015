# ARCHITECTURE — 시스템 아키텍처

| 항목 | 내용 |
|------|------|
| 문서명 | 시스템 아키텍처 설계서 |
| 최종 수정일 | 2026-07-05 |
| 버전 | v0.1 |

---

## 전체 시스템 구성도

```mermaid
graph TD
    %% 에지 디바이스 계층
    subgraph Edge_Devices [Edge Layer (ESP32 Firmware)]
        SN1[Sensor Node 1 <br/> Anchor 1]
        SN2[Sensor Node 2 <br/> Anchor 2]
        SN3[Sensor Node 3 <br/> Anchor 3]
        SN4[Sensor Node 4 <br/> Anchor 4]
        WN[Wearable Node 1 <br/> UWB Tag]
    end

    %% 인프라 및 파이프라인 계층
    subgraph Infra_Pipeline [Broker & Backend Infrastructure]
        Mosquitto[MQTT Broker <br/> Mosquitto]
        APIServer[Async API Server <br/> FastAPI / Node.js]
        TSDB[(Time-Series DB <br/> InfluxDB / TimescaleDB)]
    end

    %% 시각화 관제 계층
    subgraph UI_Layer [Visualization Layer (React 19)]
        Zustand[Zustand State Engine]
        Dashboard[2D Monitor <br/> Recharts]
        DigitalTwin[3D Digital Twin <br/> Three.js / Unity]
    end

    %% 데이터 흐름 인터페이스 연결
    SN1 & SN2 & SN3 & SN4 -->|WiFi: MQTT QoS 1| Mosquitto
    WN -->|WiFi: MQTT QoS 1| Mosquitto
    Mosquitto -->|Sub / Async Stream| APIServer
    APIServer -->|Write Buffer| TSDB
    APIServer -->|WebSockets Push| Zustand
    Zustand -->|Reactive Data Binding| Dashboard
    Zustand -->|Spatial Interpolation| DigitalTwin
```

---

## 컴포넌트 역할

### 센서 노드 × 4 (앵커)

| 항목 | 내용 |
|------|------|
| MCU | ESP32 DevKitC V4 |
| 측정 데이터 | CO2 (MH-Z19B), CO (MQ-7), H2S (MQ-136), VOC/LEL% (MQ-2), 온도/습도/VOC (BME680) |
| ADC | ADS1115 — MQ 센서 아날로그값 16비트 변환 |
| UWB 역할 | **앵커** — 웨어러블 태그와 거리 측정 (TWR) |
| 통신 | WiFi → MQTT publish |
| 발행 주기 | 가스: 5초, 환경: 10초 |

### 웨어러블 노드 × 1 (태그)

| 항목 | 내용 |
|------|------|
| MCU | ESP32 DevKitC V4 |
| 측정 데이터 | 피부 온도 (MLX90640), 산소농도 (SEN0322), 가속도/자이로 (MPU-6050) |
| 낙상 감지 | 합성 가속도벡터 ≥ 2.5g + 1초 이상 정적 상태 |
| UWB 역할 | **태그** — 앵커 4개와 거리 측정 → 위치 계산 |
| 알림 | 위험 감지 시 진동 모터 구동 |
| 통신 | WiFi → MQTT publish |

### MQTT Broker

| 항목 | 내용 |
|------|------|
| 소프트웨어 | Mosquitto (예정) |
| 배포 위치 | 로컬 서버 or 클라우드 VPS (OQ-4 미결정) |
| 역할 | 노드 → 서버 메시지 중계, QoS 1 보장 |

### API 서버

| 항목 | 내용 |
|------|------|
| 역할 | MQTT 수신 → DB 저장, 대시보드에 REST/WebSocket 제공 |
| 알람 처리 | 임계값 초과 감지 → 알림 발행 |

### 시계열 DB

| 항목 | 내용 |
|------|------|
| 후보 | InfluxDB / TimescaleDB (OQ-6 미결정) |
| 저장 단위 | 센서값 타임스탬프 + node_id 태그 |

### 대시보드 / 3D 디지털 트윈

| 항목 | 내용 |
|------|------|
| 대시보드 | 실시간 가스 농도 그래프, 임계값 경보 현황 |
| 3D 트윈 | 조선소 밀폐공간 3D 모델 + 노드 위치 + 가스 농도 히트맵 |
| 기술 스택 | 미결정 (OQ-5: Three.js / Unity WebGL 검토 중) |

---

## 데이터 흐름

```
센서 노드
  └─ MQ-7/136/2 → ADS1115(I2C) → ESP32
  └─ MH-Z19B(UART) → ESP32
  └─ BME680(I2C) → ESP32
  └─ DWM1000 BU01(SPI) → ESP32 [앵커]
       ↓ WiFi
    MQTT Broker
       ↓
    API 서버 ──→ 시계열 DB
       ↓
    대시보드 / 3D 트윈

웨어러블 노드
  └─ MLX90640(I2C) → ESP32
  └─ SEN0322(I2C) → ESP32
  └─ MPU-6050(I2C) → ESP32
  └─ DWM1000 BU01(SPI) → ESP32 [태그]
       ↓ WiFi
    MQTT Broker (위치 + 상태 publish)
```

---

## MQTT 토픽 구조  # JSON 페이로드 스펙 설정

| 토픽 | 발행 주체 | 내용 |
|------|---------|------|
| `sensors/{node_id}/gas` | 센서 노드 | CO2, CO, H2S, VOC 농도 | 
| `sensors/{node_id}/env` | 센서 노드 | 온도, 습도 |
| `sensors/{node_id}/status` | 센서 노드 | 연결 상태, 배터리 |
| `wearable/{node_id}/location` | 웨어러블 | UWB 계산 위치 (x, y, z) |
| `wearable/{node_id}/imu` | 웨어러블 | 가속도, 낙상 감지 여부 |
| `wearable/{node_id}/vital` | 웨어러블 | 피부 온도, 산소 농도 |
| `alerts/{node_id}` | API 서버 | 임계값 초과 경보 |

---
# 백엔드 AI분석 및 데이터베이스 파이프라인 
## LSTM 가스 농도 예측 및 복합 위험 점수 엔진
 - LSTM 데이터 윈도우 파이프라인: 백엔드 API 서버는 sensors/{node_id}/gas 토픽을 컨슈밍하여 각 노드별로 과거 $60\text{초}$ 동안 누적된 $12\text{개}$의 시계열 시퀀스 벡터를 메모리 내 슬라이딩 윈도우 큐에 유지합니다. 이를 LSTM 신경망 인풋으로 입력하여 $5\text{분 뒤}$의 가스 농도 예측 값($\hat{Y}_{t+5\min}$)을 선제 추론합니다
   
 - 복합 위험 점수 산정 알고리즘:
단순한 이진형 임계치 초과 판정이 아닌, 수행계획서 상에 명시된 다중 요소 가중 점수 결합 알고리즘을 수행합니다.
 $$\text{Total Risk Score} = (S_{O_2} \times 0.35) + (S_{Gas} \times 0.30) + (S_{Env} \times 0.10) + (S_{Worker} \times 0.25)$$
  - $S_{O_2}$: 산소 농도 감점 점수 (정상 범위 $20.9\%$ 기준 이탈 시 감점 적용)
  - $S_{Gas}$: 유해가스 복합 지수 ($CO, H_2S, VOC$ 정규화 가중합)
  - $S_{Env}$: BME680 기반 온·습도 불쾌/열지수 점수
  - $S_{Worker}$: MPU-6050 및 열화상 기반 이상 징후 매핑 점수
  - 판정 등급 매핑: 도출된 복합 위험 점수(0~100점)를 기준으로 4단계 등급 컷오프를 처리합니다. (SAFE < 40, CAUTION < 60, WARNING < 80, CRITICAL $\ge$ 80)

# 프론트엔드 관제 및 3D 디지털 트윈 시각화
## 데이터 상태 관리 체계

백엔드 웹소켓 라우터로부터 JSON Stream 형태로 초당 수십 번 유입되는 다지점 원시 데이터 및 위치 좌표는 React 19 웹 어플리케이션의 Zustand Global Store에 중앙 집중 바인딩됩니다.

 - 렌더링 영역 격리: 차트를 그리는 Recharts 컴포넌트와 3D 공간을 그리는 WebGL 캔버스 컴포넌트의 가상 돔 상태 구독을 완벽히 분리하여, 대용량 스트림 유입 시 화면 전체가 멈추는 프리징 현상을 방지합니다.

## 가스 확산 시뮬레이션 및 공간 보간법 알고리즘
4개의 고정식 센서 노드가 제공하는 특정 지점의 가스 데이터 값($V_1, V_2, V_3, V_4$)을 사용하여 3차원 공간 전체의 보이지 않는 유해가스 음영 구역을 도출하기 위해 역거리 가중치 보간법(IDW) 소프트웨어 필터를 적용합니다.
 - 임의의 복강 좌표 $P(x,y,z)$에서의 가스 추정 농도 $W(P)$는 각 센서 노드 고정 위상과의 거리 $d_i$의 역평방 가중치를 사용하여 실시간 계산됩니다.
   $$W(P) = \frac{\sum_{i=1}^{4} \frac{1}{d_i^p} V_i}{\sum_{i=1}^{4} \frac{1}{d_i^p}}$$
   
 - 계산된 그리드 공간 공간 매트릭스를 기반으로 프론트엔드 WebGL 뷰어 스페이스 상에 투명도가 조절된 3D 가스 밀집도 공간 히트맵을 알파 채널 텍스처 파티클로 실시간 렌더링합니다.

## 기술 스택 요약

| 계층 | 기술 |
|------|------|
| 펌웨어 | Arduino Framework (ESP32), PlatformIO |
| 통신 프로토콜 | MQTT (WiFi), UWB TWR (DWM1000) |
| 브로커 | Mosquitto |
| 백엔드 | 미결정 (FastAPI / Node.js 검토) |
| DB | 미결정 (InfluxDB / TimescaleDB — OQ-6) |
| 프론트엔드 | 미결정 (Three.js / Unity WebGL — OQ-5) |

---

## 미결정 사항 (Open Questions)

| ID | 내용 | 영향 범위 |
|----|------|---------|
| OQ-4 | MQTT 브로커 배포 위치 (로컬 vs 클라우드) | 네트워크 설계 |
| OQ-5 | 3D 트윈 렌더링 기술 (Three.js vs Unity WebGL) | 프론트엔드 전체 |
| OQ-6 | 시계열 DB 선택 (InfluxDB vs TimescaleDB) | 백엔드 스키마 |
