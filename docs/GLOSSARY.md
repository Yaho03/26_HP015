# GLOSSARY — 용어집

| 항목 | 내용 |
|------|------|
| 문서명 | 용어집 |
| 버전 | v1.0 |
| 상태 | 확정 |
| 최종 수정일 | 2026-07-17 |

---

## 1. 통신 프로토콜

### MQTT (Message Queuing Telemetry Transport)
경량 publish/subscribe 메시징 프로토콜. IoT 환경에서 센서 데이터 전송에 널리 사용된다. TCP 기반이며, 브로커가 발행자(publisher)와 구독자(subscriber) 사이에서 메시지를 중계한다. 오버헤드가 적어 저전력 디바이스에 적합하다.

### Mosquitto
Eclipse 프로젝트의 오픈소스 MQTT 브로커. MQTT 메시지를 수신하여 구독자에게 전달하는 중계 서버 역할을 한다. 본 프로젝트에서 로컬 개발 환경 및 시연 서버로 사용한다.

### Pub/Sub (Publish/Subscribe)
발행자(publisher)가 토픽(topic)에 메시지를 발행하고, 구독자(subscriber)가 관심 토픽을 구독하는 비동기 메시징 패턴. 발행자와 구독자가 직접 통신하지 않고 브로커가 중계하므로, 양쪽이 서로를 알 필요가 없다. 확장성이 좋다.

### QoS (Quality of Service)
MQTT 메시지 전달 보장 수준.

| QoS | 의미 | 특징 |
|-----|------|------|
| 0 | 최대 1회 (At most once) | 유실 가능, 확인 응답 없음, 가장 빠름 |
| 1 | 최소 1회 (At least once) | 중복 가능, 확인 응답(PUBACK) 있음 |
| 2 | 정확히 1회 (Exactly once) | 4단계 핸드셰이크, 오버헤드 큼 |

본 프로젝트에서 IMU 특징값은 QoS 0 (10Hz라 유실 허용), 경보 메시지는 QoS 1 (유실 방지 필수).

### Retain
MQTT 브로커가 토픽별로 마지막으로 발행된 메시지를 저장하는 기능. 새 구독자가 접속하면 즉시 저장된 메시지를 전달받는다. 대시보드 재연결 시 최신 센서 상태, 활성 경보를 즉시 복구하는 데 사용한다.

### LWT (Last Will and Testament)
MQTT 클라이언트 접속 시 미리 등록하는 "유언" 메시지. 클라이언트가 비정상적으로 연결 해제(전원 차단, WiFi 끊김 등) 시 브로커가 자동으로 이 메시지를 발행한다. 본 프로젝트에서 노드 오프라인 감지에 사용한다.

---

## 2. UWB / 위치 측위

### UWB (Ultra-Wideband)
초광대역 무선 기술. 500MHz 이상의 대역폭을 사용하여 수 ns 단위의 펄스를 송수신한다. Bluetooth나 WiFi보다 정밀한 거리 측정 (10~30cm)이 가능하다. 본 프로젝트에서 DWM1000 모듈을 사용한다.

### DS-TWR (Double-Sided Two-Way Ranging)
UWB 거리 측정 방식 중 하나. Tag가 Poll 메시지를 보내고, Anchor가 Response를 보내고, Tag가 Final을 보내는 3-way 메시지 교환을 통해 왕복 시간을 측정하고 거리를 계산한다. TDoA보다 구현이 단순하지만, Anchor-Tag 간 직접 통신이 필요하다.

> 상세한 수학 및 의사코드는 `APPENDIX_TECHNICAL.md` 섹션 1 참조.

### TDoA (Time Difference of Arrival)
도달 시간차 측위. 여러 수신기 간의 신호 도달 시간 차이로 위치를 추정하는 방식. 모든 수신기(Anchor)의 클럭이 정밀하게 동기화되어야 하므로 하드웨어 복잡도가 높다. 본 프로젝트에서는 제외 (ADR-002 참조).

### Anchor / Tag
UWB 측위에서 Anchor는 고정된 위치의 기준점, Tag는 위치를 추적하는 이동 대상이다. 본 프로젝트에서 센서 노드 4개가 Anchor 역할, 웨어러블 1개가 Tag 역할을 한다.

### NLOS (Non-Line-of-Sight)
신호가 직접 도달하지 못하고 벽, 기둥, 사람 등 장애물에 의해 반사 또는 회절되는 상황. UWB에서 NLOS 조건에서는 거리 측정값이 실제 거리보다 길게 측정되며, 위치 정확도가 크게 저하된다. 앵커 배치 시 LOS 확보가 중요하다.

### Antenna Delay
UWB 신호가 안테나를 통과할 때 발생하는 지연 시간. 보정하지 않으면 거리 측정에 수 cm~수십 cm 오차가 발생한다. 제조 편차로 인해 각 DWM1000 모듈마다 값이 다르며, 개별 보정이 필요하다.

---

## 3. 센서 / 하드웨어

### ADC (Analog-to-Digital Converter)
아날로그 전압을 디지털 값으로 변환하는 회로. ESP32 내장 ADC는 12-bit (0~4095)이나 선형성과 정밀도가 낮아, 본 프로젝트에서는 외부 16-bit ADC인 ADS1115를 사용한다.

### ADS1115
Texas Instruments 16-bit 4채널 ADC 모듈. I2C 통신으로 ESP32와 연결된다. MQ 센서 3종(MQ-7, MQ-136, MQ-2)의 아날로그 출력을 정밀하게 디지털 값으로 변환한다.

### 분압 회로 (Voltage Divider)
두 저항을 직렬로 연결하여 입력 전압을 낮추는 기본 회로.

```
Vout = Vin x R2 / (R1 + R2)
```

MQ 센서의 5V 출력을 ADS1115의 안전한 입력 범위로 낮추는 데 사용한다. 본 프로젝트에서 R1=20k ohm, R2=10k ohm으로 Vout = 1.67V.

### I2C (Inter-Integrated Circuit)
2선식 직렬 통신 프로토콜 (SDA 데이터선, SCL 클럭선). 여러 센서를 하나의 버스에 병렬 연결할 수 있다. 주소로 각 센서를 구분한다. 본 프로젝트에서 BME680, ADS1115, MPU-6050, SEN0322가 공유 버스를 사용한다.

### SPI (Serial Peripheral Interface)
4선식 고속 직렬 통신 (SCK 클럭, MOSI, MISO, CS). I2C보다 빠르며, 각 디바이스마다 별도의 CS(Chip Select) 선이 필요하다. DWM1000 UWB 모듈이 SPI를 사용한다.

### UART (Universal Asynchronous Receiver-Transmitter)
비동기 직렬 통신 (TX 송신, RX 수신). 클럭 선이 없고 미리 약속한 baud rate로 통신한다. MH-Z19B CO2 센서가 UART를 사용한다 (9600 baud).

### Rs / R0 (MQ 센서)
MQ 시리즈 가스 센서에서:
- **Rs**: 가스 존재 시 센서의 내부 저항값 (측정값)
- **R0**: 깨끗한 공기 중에서의 기준 저항값 (교정으로 결정)
- **Rs/R0**: 가스 농도에 비례하여 변화하는 비율. 이 비율과 센서 데이터시트의 그래프로 ppm을 추정한다.

교정 전까지 R0를 알 수 없으므로 estimated_ppm은 null이 된다.

> 교정 절차 상세는 `03_HARDWARE_DESIGN.md` 교정 섹션 참조.

### Hysteresis
경보 발생과 해제에 서로 다른 임계값을 사용하여, 임계값 부근에서 경보가 반복적으로 발생/해제되는 flickering 현상을 방지하는 기법. 발생 임계값(enter_threshold)이 해제 임계값(exit_threshold)보다 높다.

> 상세한 상태 머신과 예시는 `APPENDIX_TECHNICAL.md` 섹션 3 참조.

---

## 4. 데이터 / 소프트웨어

### ULID (Universally Unique Lexicographically Sortable Identifier)
UUID와 달리 시간순 정렬이 가능한 26자 고유 식별자. 생성 시각에 따라 사전식(lexicographic) 정렬이 되므로 DB 인덱스 성능이 우수하다. Crockford Base32 인코딩을 사용한다.

생성 예시:
```python
from ulid import ULID
msg_id = str(ULID())  # 예: "01H5X8V9J7T2K3M4N5P6Q7R8S9"
```

```typescript
import { ulid } from "ulid";
const msgId = ulid();  // "01H5X8V9J7T2K3M4N5P6Q7R8S9"
```

본 프로젝트에서 message_id, boot_id, alert_id에 사용한다. 정규식: `^[0-7][0-9A-HJKMNP-TV-Z]{25}$`

### Crockford Base32
32개 문자(0-9, A-Z 중 혼동하기 쉬운 I, L, O, U를 제외한 문자셋)로 데이터를 인코딩하는 방식. 사람이 읽기 쉽고 I/1, O/0 혼동을 방지한다. ULID 인코딩에 사용된다.

문자셋: `0123456789ABCDEFGHJKMNPQRSTVWXYZ`

### Hypertable
TimescaleDB의 핵심 개념. 시간 기반으로 자동 분할(partitioning)되는 테이블. 대량 시계열 데이터의 삽입 및 조회 성능을 최적화한다.

```sql
-- hypertable 생성 예시
CREATE TABLE sensor_data (
    time TIMESTAMPTZ NOT NULL,
    node_id TEXT NOT NULL,
    metric TEXT NOT NULL,
    value DOUBLE PRECISION
);
SELECT create_hypertable('sensor_data', 'time');
```

### Continuous Aggregate
TimescaleDB에서 미리 계산된 집계(예: 1분 평균, 1시간 평균)를 자동으로 유지하는 materialized view. 원시 데이터가 삽입되면 백그라운드에서 자동으로 갱신된다. 조회 성능을 크게 향상시킨다.

```sql
-- 1분 평균 continuous aggregate 생성
CREATE MATERIALIZED VIEW sensor_data_1min
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 minute', time) AS bucket,
    node_id,
    metric,
    AVG(value) AS avg_value
FROM sensor_data
GROUP BY bucket, node_id, metric;
```

### IDW (Inverse Distance Weighting)
거리 역수 가중 보간. 알려진 데이터 포인트(센서)들로부터 알려지지 않은 위치의 값을 추정하는 방법. 가까운 센서일수록 더 큰 가중치를 갖는다. 가중치 = 1/distance^p (p=2가 일반적). 본 프로젝트에서 4개 센서 노드의 가스 농도로 공간 분포를 시각화한다.

> 주의: IDW 추정값은 경보 판정에 사용하지 않는다 (ADR-005). 시각화 전용.

> 공식 및 계산 예시는 `APPENDIX_TECHNICAL.md` 섹션 7 참조.

### EWMA (Exponentially Weighted Moving Average)
지수 가중 이동 평균. 최근 데이터에 더 큰 가중치를 두어 평활화하는 기법.

```
EWMA_t = alpha * x_t + (1 - alpha) * EWMA_{t-1}
```

- alpha: 평활화 계수 (0 < alpha <= 1). 클수록 최신 데이터 반응이 빠름.
- 일반적으로 alpha = 0.1~0.3 사용.

> 공식 및 계산 예시는 `APPENDIX_TECHNICAL.md` 섹션 4 참조.

### Zustand
React 생태계의 경량 상태 관리 라이브러리. Redux 대비 보일러플랫트가 적고, TypeScript 지원이 우수하다. 본 프로젝트에서 대시보드 전역 상태 관리에 사용한다.

### React Three Fiber (R3F)
Three.js(웹 3D 렌더링 라이브러리)를 React 컴포넌트로 래핑한 프레임워크. JSX 문법으로 3D 씬을 선언적으로 작성할 수 있다. 본 프로젝트에서 디지털 트윈 3D 시각화에 사용한다 (ADR-003).

---

## 5. 경보 / 안전

### De-escalation
경보 해제 시 한 단계씩만 하향하는 규칙. L3(위험)에서 해제 시 L2(경고)로, L2에서 해제 시 L1(주의)로, L1에서 해제 시 Normal로 간다. L3에서 바로 Normal로 점프하지 않는다. 급격한 상태 변화로 인한 혼란을 방지한다.

### NPN Low-Side Switch
NPN 트랜지스터를 부하(모터)의 GND 측(저전압 측)에 배치하는 스위칭 회로 구성.

```
+5V ── 모터 ── Collector
                   │
                 Emitter ── GND
                   │
                 Base ── 1k ohm ── GPIO
```

ESP32 GPIO가 HIGH일 때 트랜지스터가 도통하여 모터에 전류가 흐른다. "Low-side"라는 이름은 스위치가 부하의 GND 측에 있기 때문이다.

### Flyback Diode (역기전력 보호 다이오드)
인덕티브 부하(모터, 릴레이 등)의 전원 차단 시 발생하는 역기전력(back-EMF)을 흡수하는 다이오드. 모터 양단에 역방향으로 연결한다 (Cathode를 +V측, Anode를 GND측). 이 다이오드가 없으면 전원 차단 순간의 높은 전압 스파이크로 인해 트랜지스터나 ESP32가 손상될 수 있다.

본 프로젝트에서는 1N4007 다이오드를 사용한다.

### enter_for_ms / exit_for_ms
시간 기반 경보 판정에서 사용하는 지속 시간 파라미터.

- **enter_for_ms**: 임계값 초과 상태가 이 시간(밀리초) 동안 연속으로 유지되어야 경보 발령. 오탐(false positive) 방지용.
- **exit_for_ms**: 임계값 미만 상태가 이 시간 동안 연속으로 유지되어야 경보 해제. 미해결 경보 방지용.

예: CO2 Level 2는 enter_threshold=2000ppm, enter_for_ms=3000(3초), exit_threshold=1800ppm, exit_for_ms=5000(5초).

### boot_id
노드가 부팅될 때마다 새로 생성되는 ULID. 재부팅 전후를 구분하는 데 사용한다. 메시지 중복 방지(message_id 기반)와 함께, 재부팅 후 sequence 번호 리셋을 감지하는 데 활용한다.

### source_mode
메시지가 실제 센서에서 온 것인지 시뮬레이션 데이터인지 구분하는 필드. 값은 `"live"` 또는 `"simulation"`. 실제 물리 노드의 node_id를 그대로 사용하되 이 필드로 구분한다 (`sim-NN` prefix 사용 금지).
