# HW 조립 체크리스트 (이슈 #46, #47, #48)

> 본 문서는 센서 노드 4개(#46) + 웨어러블 노드(#47) 조립 및 센서 교정(#48)의
> 단계별 체크리스트를 제공한다. 상세 회로도/핀맵은 `03_HARDWARE_DESIGN.md` 참조.

---

## 1. 센서 노드 조립 (#46) — 4세트 동일

### 1.1 부품 준비
- [ ] ESP32 DevKitC V4 × 1
- [ ] MH-Z19B (CO₂, UART) × 1
- [ ] BME680 (온습도/가스저항/IAQ, I2C) × 1
- [ ] ADS1115 (16bit ADC, I2C) × 1
- [ ] MQ-7 (CO), MQ-136 (H₂S), MQ-2 (가연성 가스) × 각 1
- [ ] DWM1000 (UWB 모듈, SPI) × 1
- [ ] 분압 저항 세트 (MQ 시리즈용)
- [ ] 점퍼 와이어, 브레드보드/만능기판

### 1.2 전원 확인
- [ ] USB 5V 전원 공급 안정 (전압 4.8–5.2V)
- [ ] ESP32 3.3V 레일 정상 (센서 I2C/VCC용)
- [ ] GND 공통 연결 확인 (ESP32 / 센서 / ADC / UWB)

### 1.3 I2C 버스 연결 (BME680, ADS1115)
- [ ] SDA → GPIO21, SCL → GPIO22
- [ ] 풀업 저항 4.7kΩ × 2 (SDA/SCL 각각 VCC로)
- [ ] I2C 스캔 (`Wire.scan()`) 으로 BME680(0x77), ADS1115(0x48) 인식 확인

### 1.4 UART 연결 (MH-Z19B CO₂)
- [ ] MH-Z19B TX → GPIO16 (RX2)
- [ ] MH-Z19B RX → GPIO17 (TX2)
- [ ] Serial2 @ 9600 baud 통신 확인

### 1.5 ADC + MQ 센서 (ADS1115)
- [ ] MQ-7 → ADS1115 A0, MQ-136 → A1, MQ-2 → A2
- [ ] 분압 회로 (03_HARDWARE_DESIGN.md 회로도) 정확히 연결
- [ ] ADS1115 raw 값 읽기 확인 (0–32767 범위, ±2g PGA)

### 1.6 UWB (DWM1000, SPI)
- [ ] MOSI → GPIO23, MISO → GPIO19, SCK → GPIO18
- [ ] CS → GPIO15, RST → GPIO4, IRQ → GPIO5
- [ ] SPI 통신 확인 (레지스터 0x00 DEV_ID 읽기 = 0xDECA0300)

### 1.7 노드별 ID 할당
- [ ] sensor-01: UWB Anchor ID 1
- [ ] sensor-02: UWB Anchor ID 2
- [ ] sensor-03: UWB Anchor ID 3
- [ ] sensor-04: UWB Anchor ID 4
- [ ] 각 노드 platformio.ini build_flags 에 `-D NODE_ID=\"sensor-0N\"` 설정

### 1.8 동작 확인
- [ ] WiFi 연결 성공
- [ ] MQTT 브로커 연결 성공 (LWT 등록)
- [ ] 각 센서 데이터 MQTT publish 확인 (`sensors/sensor-0N/gas`, `env`)
- [ ] UWB 거리 측정 동작 확인 (4개 앵커 간 상호 측정)

---

## 2. 웨어러블 노드 조립 (#47)

### 2.1 부품 준비
- [ ] ESP32 DevKitC V4 × 1
- [ ] SEN0322 (O₂, I2C, 0x73) × 1
- [ ] MPU-6050 (IMU 6축, I2C, 0x68) × 1
- [ ] DWM1000 (UWB Tag) × 1
- [ ] 진동 모터 (코인형 또는 실린더형) × 1
- [ ] S8050 NPN 트랜지스터 × 1
- [ ] 1kΩ 저항 × 1 (Base)
- [ ] 1N4007 다이오드 × 1 (역기전력 보호)

### 2.2 진동 모터 NPN Low-Side Switch 회로 (safety-critical)
> ⚠️ **회로 오류 시 모터 미구동 또는 ESP32 손상. 반드시 극성 확인.**

```
+5V 레일
  │
  진동 모터 (+)
  │
  진동 모터 (-)
  │
  1N4007 다이오드 (Cathode=+5V, Anode=아래 Collector)
  │
  S8050 NPN Collector (C)
  │
  S8050 NPN Emitter (E) ─── GND
  │
  S8050 NPN Base (B)
  │
  1kΩ 저항
  │
  ESP32 GPIO25
```

- [ ] 진동 모터를 **+5V와 Collector 사이**에 배치 (Emitter 아님)
- [ ] S8050 방향 확인 (flat 면 기준 E-B-C 핀 순서)
- [ ] 1N4007 다이오드 극성 (띠=Cathode=+5V측, 반대편=Collector)
- [ ] 1kΩ Base 저항 연결 (GPIO25 ↔ Base)
- [ ] GPIO25 LOW 시 모터 정지, HIGH 시 구동 확인

### 2.3 I2C 센서 (SEN0322 O₂, MPU-6050 IMU)
- [ ] SDA → GPIO21, SCL → GPIO22
- [ ] SEN0322 (0x73) 인식 확인
- [ ] MPU-6050 (0x68) 인식 확인
- [ ] O₂ 값 정상 범위 (20.5–21.0% in clean air)
- [ ] IMU accel 범위 확인 (정지 시 |a| ≈ 9.8 m/s²)

### 2.4 UWB (DWM1000, Tag 모드)
- [ ] SPI 배선 (센서 노드와 동일)
- [ ] Tag 모드 설정 (Anchor가 아닌 Tag로 구성)
- [ ] 4개 앵커와 거리 측정 확인

### 2.5 로컬 폴백 테스트 (safety-critical, #86)
- [ ] O₂ 시뮬레이션 값 15.5% 주입 → 진동 모터 즉시 구동 확인
- [ ] O₂ 시뮬레이션 값 20.9% 복귀 → 진동 정지 확인
- [ ] 백엔드/MQTT 연결 끊김 상태에서도 로컬 폴백 동작 확인

---

## 3. 센서 교정 (#48, safety-critical)

### 3.1 MQ 시리즈 R0 교정 (MQ-7, MQ-136, MQ-2)

> ⚠️ **교정 전 예열 필수. 교정 환경이 실제 사용 환경과 다르면 경보 정확도 저하.**

- [ ] 청정 공기 환경 조성 (실외, 환기 양호, 알려진 가스원 없음)
- [ ] **Warm-up**: MQ-7 최소 24시간, MQ-136 최소 48시간 예열
- [ ] 예열 완료 후 `MqCalibrator.begin()` 호출
- [ ] Rs 안정화 대기: ±5% 이내 변동을 5분간 유지
- [ ] R0 계산 완료 (`CalibrationState::DONE`)
- [ ] R0 값 EEPROM 저장 (백업, 별도 구현)
- [ ] 3개 센서(MQ-7/136/2) 각각 교정 완료

### 3.2 BME680 Burn-in

- [ ] `Bme680BurnIn.begin()` 호출
- [ ] burn-in 최소 1시간 (60분) 경과
- [ ] `iaq_accuracy` ≥ 2 도달 확인 (BSEC 라이브러리 상태)
- [ ] IAQ 값 안정화 확인 (실내 환경에서 50–150 범위)

### 3.3 MH-Z19B CO₂ 영점 교정

- [ ] 청정 공기 환경 (실외, CO₂ ≈ 400ppm) 에서 20분 안정화
- [ ] 영점 교정 명령 전송 (0xFF 0x01 0x87 0x00 0x00 0x00 0x00 0x00 0x3A)
- [ ] 교정 후 측정값 400±50ppm 확인

### 3.4 SEN0322 O₂ 교정

- [ ] 실외 청정 공기에서 측정값 20.9±0.5% 확인
- [ ] 편차 > 0.5% 시 SEN0322 내장 교정 절차 수행 (제품 설명서 참조)

### 3.5 교정 결과 기록

| 센서 | 노드 | R0 (Ω) / 교정값 | 교정 일시 | 환경 |
|------|------|------------------|-----------|------|
| MQ-7 (CO) | sensor-01 | _____ | ___-___-__ | 온도 __°C 습度 __% |
| MQ-7 (CO) | sensor-02 | _____ | ___-___-__ | 온도 __°C 습度 __% |
| MQ-136 (H₂S) | sensor-01 | _____ | ___-___-__ | 온도 __°C 습度 __% |
| MQ-136 (H₂S) | sensor-02 | _____ | ___-___-__ | 온도 __°C 습度 __% |
| BME680 | sensor-01 | iaq_acc=2 도달 시각: _____ | | |
| SEN0322 | wearable-01 | 영점: _____% | | |

---

## 4. 통합 테스트 (조립+교정 완료 후)

- [ ] 5개 노드 전원 On → WiFi → MQTT 연결
- [ ] 백엔드 /health 엔드포인트에서 5개 노드 online 확인
- [ ] 대시보드(`http://localhost:5173`)에서 실시간 데이터 표시 확인
- [ ] 경보 시나리오: 데이터 주입 도구로 CO₂ L3 시나리오 실행 → 백엔드 경보 발생 → 대시보드 표시 → (웨어러블 진동) → end-to-end 확인
- [ ] UWB 위치 추적: 웨어러블 이동 시 3D 트윈에서 실시간 위치 갱신 확인
- [ ] EXP-2/EXP-3 (UWB 정적/동적 정확도) 실제 환경에서 재측정
