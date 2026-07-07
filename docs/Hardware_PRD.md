# Hardware PRD(수정중)

## 1. Overview

본 문서는 IoT 센서 시계열 분석 기반 조선소 밀폐공간 질식재해 예방 실시간 모니터링 시스템의 하드웨어 요구사항 및 아키텍처를 정의한다.

본 시스템은 조선소의 탱크, 화물창, 이중선저 등 밀폐공간에 설치되는 4개의 센서 노드와 작업자가 착용하는 1개의 웨어러블 노드로 구성된다.

센서 노드는 밀폐공간의 여러 위치에서 유해가스 및 환경 데이터를 실시간으로 수집하며, 동시에 UWB Anchor 역할을 수행한다.

웨어러블 노드는 작업자의 산소 농도, 움직임 및 위치 데이터를 수집하며, 위험 상황 발생 시 진동 모터를 통해 작업자에게 경고를 제공한다.

각 노드에서 수집된 데이터는 ESP32를 통해 서버로 전송되며, 서버에서는 수집된 센서 데이터를 기반으로 위험 상황을 분석한다.

---

## 2. Objectives

하드웨어 시스템은 다음 기능을 수행하는 것을 목표로 한다.

- 밀폐공간 내 환경 데이터 실시간 측정
- CO₂ 농도 측정
- CO 농도 측정
- H₂S 농도 측정
- VOC 및 가연성 가스 측정
- 온도 및 습도 측정
- UWB 기반 작업자 위치 측정
- 작업자 주변 산소 농도 측정
- 작업자 움직임 데이터 수집
- 위험 상황 발생 시 작업자 진동 알림
- WiFi 기반 서버 통신
- MQTT 기반 실시간 센서 데이터 전송

---

# 3. Hardware Architecture

## 3.1 Hardware System Overview

본 시스템의 하드웨어는 다음과 같이 구성된다.

- Full-Spec Sensor Node × 4
- Wearable Node × 1
- MQTT Broker
- AI Server
- Power Supply

4개의 센서 노드는 동일한 하드웨어 구성으로 제작한다.

각 센서 노드는 밀폐공간의 서로 다른 위치에 설치되어 환경 및 가스 데이터를 측정한다.

또한 각 센서 노드의 DWM1000 BU01은 UWB Anchor 역할을 수행한다.

웨어러블 노드는 작업자가 착용하며 DWM1000 BU01을 UWB Tag로 사용하여 작업자의 위치 측정에 활용한다.

모든 노드는 WiFi를 이용하여 MQTT Broker 및 서버와 통신한다.

---

## 3.2 System Architecture
                         ┌───────────────────────────┐
                         │      MQTT Broker          │
                         │        AI Server          │
                         │                           │
                         │  - Sensor Data Collection │
                         │  - AI Risk Analysis       │
                         │  - Dashboard              │
                         │  - Alert Management       │
                         └─────────────▲─────────────┘
                                       │
                                  WiFi / MQTT
                                       │
            ┌──────────────────────────┼──────────────────────────┐
            │                          │                          │
            │                          │                          │
            ▼                          ▼                          ▼

   ┌────────────────┐        ┌────────────────┐        ┌────────────────┐
   │ Sensor Node 1  │        │ Sensor Node 2  │        │ Sensor Node 3  │
   │                │        │                │        │                │
   │ Full-Spec      │        │ Full-Spec      │        │ Full-Spec      │
   │ Gas Monitoring │        │ Gas Monitoring │        │ Gas Monitoring │
   │ UWB Anchor     │        │ UWB Anchor     │        │ UWB Anchor     │
   └───────▲────────┘        └───────▲────────┘        └───────▲────────┘
           │                         │                         │
           │                         │                         │
           └─────────────────────────┼─────────────────────────┘
                                     │
                                     │ UWB
                                     │
                        ┌────────────┴────────────┐
                        │                         │
                        ▼                         ▼

               ┌────────────────┐        ┌────────────────┐
               │ Sensor Node 4  │        │ Wearable Node  │
               │                │        │                │
               │ Full-Spec      │◄─ UWB ─│ UWB Tag        │
               │ Gas Monitoring │        │ Oxygen         │
               │ UWB Anchor     │        │ Motion         │
               └────────────────┘        │ Vibration      │
                                         └────────────────┘
```

---

## 3.3 Sensor Node Architecture

센서 노드는 총 4개이며 모든 센서 노드는 동일한 풀스펙 구성으로 제작한다.

각 센서 노드는 ESP32 DevKitC V4를 메인 MCU로 사용한다.

센서 노드는 다음 데이터를 수집한다.

- CO₂
- CO
- H₂S
- VOC 및 가연성 가스
- 온도
- 습도
- UWB 위치 측위 데이터

센서 노드의 기본 구조는 다음과 같다.

                           ┌──────────────────────┐
                           │ ESP32 DevKitC V4     │
                           │                      │
                           │ Main Controller      │
                           └───────────┬──────────┘
                                       │
          ┌──────────────┬─────────────┼─────────────┬──────────────┐
          │              │             │             │              │
          ▼              ▼             ▼             ▼              ▼

     ┌─────────┐    ┌─────────┐   ┌─────────┐   ┌─────────┐    ┌─────────┐
     │MH-Z19B  │    │ BME680  │   │ADS1115  │   │DWM1000  │    │  WiFi   │
     │         │    │         │   │         │   │ BU01    │    │         │
     │ CO₂     │    │Temp     │   │16-bit   │   │UWB      │    │ MQTT    │
     │ Sensor  │    │Humidity │   │ADC      │   │Anchor   │    │         │
     └─────────┘    └─────────┘   └────▲────┘   └─────────┘    └─────────┘
                                       │
                                       │
                            ┌──────────┼──────────┐
                            │          │          │
                            ▼          ▼          ▼

                        ┌────────┐ ┌────────┐ ┌────────┐
                        │ MQ-7   │ │ MQ-136 │ │ MQ-2   │
                        │        │ │        │ │        │
                        │ CO     │ │ H₂S    │ │ Gas    │
                        │ Sensor │ │ Sensor │ │ Sensor │
                        └────────┘ └────────┘ └────────┘
```

---

## 3.4 Sensor Node Components

| Component | Quantity per Node | Role | Interface |
|---|---:|---|---|
| ESP32 DevKitC V4 | 1 | Main MCU | WiFi |
| MH-Z19B | 1 | CO₂ Measurement | UART |
| BME680 | 1 | Temperature / Humidity / Gas Resistance | I2C |
| MQ-7 | 1 | CO Measurement | Analog |
| MQ-136 | 1 | H₂S Measurement | Analog |
| MQ-2 | 1 | Combustible Gas Measurement | Analog |
| ADS1115 | 1 | External ADC | I2C |
| DWM1000 BU01 | 1 | UWB Anchor | SPI |

---

## 3.5 Sensor Node Communication Architecture

센서 노드에서는 여러 종류의 통신 인터페이스를 사용한다.

```text
ESP32 DevKitC V4

├── UART
│   └── MH-Z19B
│
├── I2C
│   ├── BME680
│   └── ADS1115
│
├── SPI
│   └── DWM1000 BU01
│
└── WiFi
    └── MQTT Broker / Server
```

BME680과 ADS1115는 I2C Bus를 공유한다.

MQ-7, MQ-136 및 MQ-2는 아날로그 출력을 사용하며 ADS1115를 통해 디지털 데이터로 변환한다.

---

## 3.6 MQ Sensor ADC Architecture

MQ 계열 센서는 아날로그 출력 방식을 사용한다.

ESP32의 내부 ADC 대신 외부 16-bit ADC인 ADS1115를 사용하여 MQ 센서의 아날로그 데이터를 수집한다.

MQ-7 Analog Output
        │
        ▼
Voltage Divider
        │
        ▼
ADS1115 A0


MQ-136 Analog Output
        │
        ▼
Voltage Divider
        │
        ▼
ADS1115 A1


MQ-2 Analog Output
        │
        ▼
Voltage Divider
        │
        ▼
ADS1115 A2
```

ADS1115의 A3 Channel은 예비 채널로 유지한다.

---

## 3.7 Voltage Divider Design

MQ 센서의 아날로그 출력 전압이 ADS1115의 허용 입력 범위를 초과하지 않도록 저항 분압 회로를 적용한다.

기본적인 저항 분압 공식은 다음과 같다.

Vout = Vin × R2 / (R1 + R2)
```

기본 설계안은 다음과 같다.

MQ Analog Output

        │
        │
       R1
        │
        ▼
        ●──────────── ADS1115 Analog Input
        │
       R2
        │
        ▼
       GND
```

초기 검토 저항값은 다음과 같다.


R1 = 10kΩ

R2 = 20kΩ
```

입력 전압이 5V라고 가정하면 다음과 같다.


Vout
= 5V × 20kΩ / (10kΩ + 20kΩ)= 3.33V

따라서 센서 노드 1개당 필요한 분압 저항은 다음과 같다.

| Resistor | Quantity |
|---|---:|
| 10kΩ | 3 |
| 20kΩ | 3 |

센서 노드 4개 전체 기준 필요한 저항은 다음과 같다.

| Resistor | Quantity |
|---|---:|
| 10kΩ | 12 |
| 20kΩ | 12 |

MUST : 회로 설계 전 멀티미터로 전압 측정

---

## 3.8 Wearable Node Architecture

웨어러블 노드는 작업자가 직접 착용하는 장치이다.

웨어러블 노드는 다음 기능을 수행한다.

- 작업자 주변 산소 농도 측정
- 작업자 움직임 데이터 수집
- UWB 기반 작업자 위치 측정
- 위험 상황 발생 시 진동 알림
- 서버로 작업자 상태 데이터 전송

웨어러블 노드의 구조는 다음과 같다.

                           ┌──────────────────────┐
                           │ ESP32 DevKitC V4     │
                           │                      │
                           │ Wearable Controller  │
                           └───────────┬──────────┘
                                       │
          ┌──────────────┬─────────────┼─────────────┬──────────────┐
          │              │             │             │              │
          ▼              ▼             ▼             ▼              ▼

     ┌─────────┐    ┌─────────┐   ┌─────────┐   ┌──────────┐   ┌─────────┐
     │SEN0322  │    │MPU6050  │   │DWM1000  │   │Vibration │   │  WiFi   │
     │         │    │         │   │ BU01    │   │Motor     │   │         │
     │Oxygen   │    │6-axis   │   │UWB Tag  │   │Alert     │   │ MQTT    │
     │Sensor   │    │IMU      │   │         │   │          │   │         │
     └─────────┘    └─────────┘   └─────────┘   └──────────┘   └─────────┘
```

---

## 3.9 Wearable Node Components

| Component | Quantity | Role |
|---|---:|---|
| ESP32 DevKitC V4 | 1 | Main MCU |
| SEN0322 | 1 | Oxygen Measurement |
| MPU6050 | 1 | Acceleration / Gyroscope Measurement |
| DWM1000 BU01 | 1 | UWB Tag |
| TK1027A03-30 | 1 | Vibration Alert |

---

## 3.10 UWB Architecture

센서 노드에 설치된 DWM1000 BU01은 고정형 UWB Anchor로 사용한다.
웨어러블 노드에 설치된 DWM1000 BU01은 이동형 UWB Tag로 사용한다.

             Sensor Node 1
               Anchor 1

                   ●
                   │
                   │
                   │
Sensor Node 4 ●────★────● Sensor Node 2
   Anchor 4      Worker      Anchor 2
                UWB Tag
                   │
                   │
                   │
                   ●

             Sensor Node 3
               Anchor 3
```

UWB 시스템은 Anchor와 Tag 간 거리 측정 데이터를 이용하여 작업자의 위치 측위에 활용한다.

---

## 3.11 Power Architecture

### Sensor Node Power Architecture

센서 노드는 5V 외부 전원을 사용한다.

개발 및 테스트 단계에서는 USB 보조배터리를 전원으로 사용한다.

                         5V Power Supply
                               │
                ┌──────────────┴──────────────┐
                │                             │
                ▼                             ▼

         ESP32 DevKitC V4              Breadboard 5V Rail

                                              │
                              ┌───────────────┼───────────────┐
                              │               │               │
                              ▼               ▼               ▼

                          MH-Z19B          MQ Sensors      Other 5V Loads
```

ESP32와 외부 센서는 반드시 공통 GND를 사용해야 한다.


ESP32 GND

    │

    └──────────── Breadboard GND Rail
```

---

## 3.12 Sensor Node Power Requirements

센서 노드는 MQ 계열 센서의 히터 및 ESP32의 WiFi 통신으로 인해 비교적 높은 소비전류가 발생할 수 있다.

따라서 다음 사항을 고려한다.

- MQ 센서 전원을 ESP32 GPIO에서 직접 공급하지 않는다.
- 고전류 센서는 외부 5V 전원 레일에서 전원을 공급한다.
- ESP32와 센서 전원의 GND는 공통으로 연결한다.
- 순간 전류 증가에 대비하여 충분한 출력 용량의 전원을 사용한다.
- 최종 전원 용량은 실제 회로 구성 후 멀티미터를 이용하여 측정한다.

개발 단계의 초기 전원 요구사항은 다음과 같다.

Sensor Node

Input Voltage : 5V

Recommended Power Supply : 5V / 2A or higher
```

> **TBD**
>
> 최종 전원 사양은 전체 센서 동작 상태에서 실제 소비전류를 측정한 후 확정한다.

---

## 3.13 Wearable Power Architecture

웨어러블 노드는 휴대성을 고려하여 소형 보조배터리를 사용한다.


                     Portable Power Supply
                              │
                              ▼
                     ESP32 DevKitC V4
                              │
             ┌────────────────┼────────────────┐
             │                │                │
             ▼                ▼                ▼

          MPU6050          SEN0322          DWM1000

                              │

                              ▼

                      Vibration Motor
```

웨어러블 노드의 최종 배터리 용량은 실제 소비전류 측정 후 결정한다.

> **TBD**
>
> 웨어러블 노드의 최종 배터리 사양 및 목표 동작 시간은 추후 확정한다.

---

## 3.14 Breadboard Prototype Architecture

개발 및 테스트 단계에서는 830홀 브레드보드를 사용하여 회로를 구성한다.

센서 노드 1개당 브레드보드 1개를 사용한다.

MQ 센서 및 MH-Z19B와 같이 크기가 큰 센서는 브레드보드 외부에 배치하고 점퍼선을 이용하여 연결할 수 있다.


┌──────────────────────────────────────────────────────┐
│                                                      │
│   ESP32              BME680             DWM1000      │
│                                                      │
│                       ADS1115                        │
│                                                      │
│   MQ-7 Divider    MQ-136 Divider    MQ-2 Divider     │
│                                                      │
│   +5V Rail =======================================   │
│                                                      │
│   GND Rail =======================================   │
│                                                      │
└──────────────────────────────────────────────────────┘

        │                  │                  │
        ▼                  ▼                  ▼

      MQ-7              MQ-136              MQ-2


                       MH-Z19B
```

---

## 3.15 Hardware Constraints

하드웨어 설계 시 다음 제약사항을 고려해야 한다.

- ESP32의 GPIO Logic Level은 3.3V이다.
- DWM1000은 3.3V 기반으로 동작해야 한다.
- MQ 센서의 아날로그 출력은 ADC 입력 전압 범위를 초과하지 않아야 한다.
- MQ 센서는 히터를 사용하므로 충분한 전류 공급이 필요하다.
- 모든 센서는 공통 GND를 사용해야 한다.
- 센서별 통신 인터페이스 충돌이 발생하지 않아야 한다.
- I2C 장치는 동일한 SDA 및 SCL Bus를 공유할 수 있다.
- 동일 I2C Bus에서 장치 주소가 충돌하지 않아야 한다.
- UWB Anchor는 위치 측위가 가능하도록 서로 다른 고정 위치에 설치해야 한다.
- Wearable Node는 작업자의 활동을 방해하지 않는 크기와 무게를 고려해야 한다.

---

## 3.16 Thermal Camera Architecture

본 프로젝트에서는 저조도 환경의 작업자 상태 탐지를 위해 MLX90640ESF-BAB 열화상 센서를 사용한다.

그러나 현재 하드웨어 구성에서는 ESP32 DevKitC V4 5개가 센서 노드 4개 및 웨어러블 노드 1개에 모두 사용된다.

따라서 MLX90640의 최종 하드웨어 배치는 현재 미확정 상태이다.

> **TBD**
>
> 다음 방안 중 최종 구성을 결정한다.
>
> 1. ESP32를 추가하여 MLX90640 독립형 고정 노드를 구성한다.
> 2. 기존 노드의 ESP32에 MLX90640을 연결한다.
>
> 프로젝트의 작업자 감지 목적을 고려할 경우 독립형 고정 열화상 노드 구성을 우선 검토한다.

---

## 3.17 Hardware Architecture Summary

본 시스템의 하드웨어는 동일한 풀스펙 센서 노드 4개와 작업자 착용형 웨어러블 노드 1개로 구성된다.

센서 노드는 밀폐공간의 서로 다른 위치에 설치되어 CO₂, CO, H₂S, 가연성 가스, 온도 및 습도 데이터를 수집한다.

각 센서 노드에 설치된 DWM1000 BU01은 UWB Anchor 역할을 수행한다.

웨어러블 노드는 작업자가 착용하며 산소 농도, 움직임 및 위치 데이터를 수집한다.

웨어러블의 DWM1000 BU01은 UWB Tag 역할을 수행하며, 위험 상황 발생 시 진동 모터를 통해 작업자에게 경고를 제공한다.

모든 노드는 ESP32를 메인 MCU로 사용하며 WiFi 및 MQTT를 통해 서버와 통신한다.

개발 및 테스트 단계에서는 830홀 브레드보드를 이용하여 프로토타입을 제작하고, 각 센서의 정상 동작과 전체 시스템 소비전류를 측정한 후 최종 PCB 및 전원 시스템 설계를 진행한다.
