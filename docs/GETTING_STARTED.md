# GETTING STARTED — 시작 가이드

| 항목 | 내용 |
|------|------|
| 문서명 | 시작 가이드 |
| 버전 | v1.0 |
| 상태 | 확정 |
| 최종 수정일 | 2026-07-17 |

---

## 1. 사전 지식 (Prerequisites)

본 프로젝트는 펌웨어, 백엔드, 프론트엔드, 3D 시각화, 하드웨어가 결합된 IoT 시스템이다. 팀원 전원이 모든 기술을 알 필요는 없으며, 담당 영역에 따라 필요한 지식이 다르다.

### 1.1 공통 (모든 팀원)

| 항목 | 수준 | 비고 |
|------|------|------|
| Git | clone, branch, commit, push, PR 생성 | GitHub flow 이해 |
| Linux/macOS 명령행 | 기본 (cd, ls, mkdir, grep) | Windows는 WSL 또는 Git Bash 권장 |
| Markdown | 읽기/쓰기 | 문서 작성 및 PR 설명 |
| IoT 개념 | 센서 → 통신 → 서버 → UI 흐름 이해 | `00_PROJECT_OVERVIEW.md` 참조 |

### 1.2 역할별 요구 지식

| 역할 | 필수 지식 | 권장 지식 |
|------|-----------|-----------|
| 펌웨어 | C/C++ 기본, Arduino Framework | 전자 회로 기본 (전압, 전류, 저항, breadboard) |
| 백엔드 | Python 3 중급 (async, class), REST API, SQL 기본 | Docker, async/await 패턴 |
| 프론트엔드 | JavaScript/TypeScript, React (hooks, state) | CSS, WebSocket |
| 3D 트윈 | React 경험, Three.js 개념 | Blender 기본 (모델링, GLB export) |
| 하드웨어 | 브레드보드 배선, 멀티미터 사용 | 데이터시트 읽기, 납땜 |

### 1.3 도메인 지식

프로젝트에 사용된 기술 용어는 `GLOSSARY.md`에서 정의한다. UWB, MQTT, Hysteresis, IDW, EWMA 등의 개념을 처음 접한다면 먼저 용어집을 읽는 것을 권장한다.

알고리즘의 수학적 원리와 계산 예시는 `APPENDIX_TECHNICAL.md`를 참조한다.

---

## 2. 학습 리소스 (Learning Resources)

각 기술의 공식 문서 및 튜토리얼 링크다. **필수**는 프로젝트 작업 전 반드시 읽어야 하고, **참고용**은 필요할 때 참조한다.

### 2.1 펌웨어

| 기술 | 링크 | 우선순위 |
|------|------|---------|
| PlatformIO | https://docs.platformio.org/ | 필수 |
| ESP32 Arduino | https://docs.espressif.com/projects/arduino-esp32/ | 필수 |
| PubSubClient (MQTT) | https://pubsubclient.knolleary.net/ | 필수 |
| ArduinoJson | https://arduinojson.org/ | 필수 |
| ADS1115 가이드 (Adafruit) | https://learn.adafruit.com/adafruit-4-channel-adc-breakouts | 참고용 |
| MQ 센서 원리 | https://learn.adafruit.com/ | 참고용 (검색: "MQ sensor tutorial") |

### 2.2 백엔드

| 기술 | 링크 | 우선순위 |
|------|------|---------|
| FastAPI | https://fastapi.tiangolo.com/tutorial/ | 필수 |
| paho-mqtt (Python) | https://pypi.org/project/paho-mqtt/ | 필수 |
| TimescaleDB | https://docs.timescale.com/getting-started/ | 필수 |
| asyncpg | https://magicstack.github.io/asyncpg/ | 참고용 |
| Docker Compose | https://docs.docker.com/compose/ | 참고용 |

### 2.3 프론트엔드 / 3D

| 기술 | 링크 | 우선순위 |
|------|------|---------|
| React | https://react.dev/learn | 필수 |
| TypeScript | https://www.typescriptlang.org/docs/ | 필수 |
| Zustand | https://docs.pmnd.rs/zustand/getting-started | 필수 |
| Recharts | https://recharts.org/en-US/guide | 필수 |
| React Three Fiber | https://docs.pmnd.rs/react-three-fiber/getting-started | 필수 (3D 담당) |
| Three.js | https://threejs.org/docs/ | 참고용 (3D 담당) |
| Blender | https://docs.blender.org/ | 참고용 (모델링 담당) |

### 2.4 공통 / 인프라

| 기술 | 링크 | 우선순위 |
|------|------|---------|
| MQTT 프로토콜 | https://mqtt.org/mqtt-glossary/ | 필수 |
| Git & GitHub | https://docs.github.com/ko | 필수 |

---

## 3. 프로젝트 이해하기

### 3.1 시스템이 해결하는 문제

조선소 밀폐공간(탱크 내부, 이중저 구획 등)에서 작업 시 발생할 수 있는 유해가스 누출, 산소 결핍, 낙상 위험을 실시간으로 감지하고, 관리자와 작업자에게 경보를 제공한다. 작업자는 웨어러블 기기로 진동 알림을 받고, 관리자는 웹 대시보드로 현장 상황을 모니터링한다.

### 3.2 데이터 흐름

```
센서 노드 (ESP32)
    | WiFi → MQTT (Mosquitto)
백엔드 (FastAPI)
    |→ TimescaleDB (저장)
    |→ 임계값 비교 → 경보 발령
    | WebSocket → 프론트엔드
대시보드 (React)
    |→ 실시간 카드 (Recharts)
    |→ 시계열 차트
    |→ 이벤트 로그
    |→ 3D 디지털 트윈 (React Three Fiber)
```

> 이 흐름의 각 단계는 `02_SYSTEM_ARCHITECTURE.md`에서 상세히 설명한다.

### 3.3 문서 읽기 순서

| 순서 | 문서 | 목적 |
|------|------|------|
| 1 | `00_PROJECT_OVERVIEW.md` | 전체 개요 파악 |
| 2 | `GETTING_STARTED.md` (본 문서) | 개발 환경 준비 |
| 3 | `GLOSSARY.md` | 기술 용어 숙지 |
| 4 | `01_PRD.md` | 요구사항 전체 이해 (FR-XXX) |
| 5 | 역할별 문서 | 담당 영역 상세 (아래 표) |
| 6 | `APPENDIX_TECHNICAL.md` | 알고리즘 구현 시 수학 참조 |

### 3.4 역할별 추천 읽기

| 역할 | 추가로 읽을 문서 |
|------|-----------------|
| 펌웨어 | `03_HARDWARE_DESIGN.md`, `04_DATA_CONTRACT.md`, `06_ALERT_RULES.md` |
| 백엔드 | `04_DATA_CONTRACT.md`, `06_ALERT_RULES.md`, `07_EXPERIMENT_PLAN.md` |
| 프론트엔드 | `10_UI_FLOW.md`, `05_DIGITAL_TWIN_SPEC.md` |
| 3D 트윈 | `05_DIGITAL_TWIN_SPEC.md`, `10_UI_FLOW.md`, `APPENDIX_TECHNICAL.md` (좌표 변환, IDW) |
| 하드웨어 | `03_HARDWARE_DESIGN.md`, `BOM.md`, `08_SAFETY_AND_LIMITATIONS.md` |

---

## 4. 개발 환경 설정

> `backend/`, `frontend/`, `firmware/` 디렉토리는 Issue #34에서 생성된다. 이 단계는 해당 이슈 완료 후 진행 가능하다. 디렉토리 생성 전에는 도구 설치만 먼저 진행한다.

### 4.1 공통 도구

#### Git 설치

```bash
# macOS (Homebrew)
brew install git

# Ubuntu/Debian
sudo apt install git

# Windows: https://git-scm.com/download/win
```

#### 저장소 클론

```bash
git clone https://github.com/Yaho03/26_HP015.git
cd 26_HP015
```

#### VS Code + 확장 프로그램

VS Code를 설치한 후, 역할에 따라 확장 프로그램을 추가한다:

| 확장 | 역할 | 비고 |
|------|------|------|
| PlatformIO IDE | 펌웨어 | ESP32 개발 환경 |
| Python | 백엔드 | syntax highlighting, IntelliSense |
| ESLint | 프론트엔드 | 코드 품질 |
| Prettier | 프론트엔드 | 코드 포맷팅 |
| Markdown All in One | 공통 | 문서 작성 |
| GitLens | 공통 | Git 히스토리 |

### 4.2 펌웨어 개발 환경

#### PlatformIO 설치

VS Code 확장으로 설치하는 것을 권장한다. PlatformIO IDE 확장을 설치하면 CLI도 함께 설치된다.

CLI만 필요한 경우:

```bash
pip install platformio
```

#### ESP32 USB 드라이버

ESP32 DevKitC V4의 USB-UART 칩에 따라 드라이버 설치가 필요하다:

| 칩셋 | 드라이버 링크 |
|------|-------------|
| CP2102 (Silicon Labs) | https://www.silabs.com/developers/usb-to-uart-bridge-vcp-drivers |
| CH340 (WCH) | https://wch-ic.com/downloads/CH341SER_EXE.html |

#### 포트 확인

```bash
# macOS
ls /dev/cu.SLAB_USBtoUART* /dev/cu.wchusbserial*

# Linux
ls /dev/ttyUSB*

# Windows (Device Manager에서 확인)
# COM3, COM4 등
```

#### 빌드 테스트

```bash
cd firmware
pio run -e sensor-node    # 빌드만
pio run -t upload -e sensor-node  # 업로드
```

### 4.3 백엔드 개발 환경

#### Python + venv

```bash
# Python 3.11+ 확인
python3 --version

cd backend
python3 -m venv .venv
source .venv/bin/activate    # macOS/Linux
# .venv\Scripts\activate     # Windows

pip install -r requirements.txt
```

#### Docker (TimescaleDB + Mosquitto)

```bash
# Docker 24+ 확인
docker --version

# 인프라 실행
cd docker
docker compose up -d

# 상태 확인
docker compose ps
# timescaledb  running
# mosquitto    running
```

#### .env 파일 설정

```bash
# .env.example을 복사하여 .env 생성
cp .env.example .env

# 값 확인 및 수정
# MQTT_HOST=localhost
# MQTT_PORT=1883
# MQTT_USERNAME=hp015
# MQTT_PASSWORD=...
# TIMESCALE_URL=postgresql://hp015:...@localhost:5432/hp015
```

#### 백엔드 실행

```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

브라우저에서 http://localhost:8000/docs 로 접속하여 Swagger UI 확인.

### 4.4 프론트엔드 개발 환경

#### Node.js 설치

```bash
# nvm 사용 권장 (Node 20+)
nvm install 20
nvm use 20
node --version   # v20.x.x 확인
```

#### 패키지 설치 및 실행

```bash
cd frontend
npm install
npm run dev
```

브라우저에서 http://localhost:5173 (Vite 기본 포트) 접속.

---

## 5. 하드웨어 없이 개발하기

하드웨어가 준비되지 않은 상태에서도 백엔드와 프론트엔드 개발이 가능하다. **simulation 데이터 주입** 방식을 사용한다.

### 5.1 source_mode 개념

모든 MQTT 메시지에는 `source_mode` 필드가 있다:
- `"live"`: 실제 센서에서 전송된 데이터
- `"simulation"`: software injection으로 생성한 가상 데이터

데이터 주입 도구(Issue #82)는 `source_mode: "simulation"`으로 메시지를 발행하여, 백엔드와 프론트엔드가 실제 센서 데이터와 동일하게 처리하도록 한다.

### 5.2 mosquitto_pub로 수동 테스트

MQTT 브로커가 실행 중일 때, 터미널에서 직접 테스트 메시지를 발행할 수 있다:

```bash
# CO2 경보 시뮬레이션 (sensor-01에서 2500ppm)
mosquitto_pub -h localhost -p 1883 -u hp015 -P <password> \
  -t "sensors/sensor-01/gas" \
  -m '{
    "schema_version": "1.1",
    "node_id": "sensor-01",
    "source_mode": "simulation",
    "boot_id": "01H5X8V9J7T2K3M4N5P6Q7R8S9",
    "sequence": 1,
    "sampled_at": "2026-07-17T10:00:00.000Z",
    "published_at": "2026-07-17T10:00:00.050Z",
    "payload": {
      "co2_ppm": 2500,
      "gas_resistance_ohm": 45000,
      "mq7": {"raw_adc": 512, "voltage_v": 0.83, "calibration_status": "uncalibrated"}
    }
  }'
```

### 5.3 대시보드에서 확인

메시지를 발행한 후 대시보드를 확인하면:
- Monitoring 화면: sensor-01 카드에 CO2 2500ppm 표시
- simulation 데이터는 시각적으로 구분 표시 (source_mode 라벨)
- 임계값 초과 시 경보 발령 → 경보 카드 색상 변경

---

## 6. 첫 이슈 실습

역할별로 추천하는 첫 이슈는 다음과 같다. 각 이슈는 반나절~1일 분량이다.

### 6.1 펌웨어 담당: Issue #39 (MH-Z19B CO2 센서 드라이버)

```bash
# 브랜치 생성
git checkout -b firmware/FR-101-mhz19b-co2

# 작업: firmware/src/sensors/mhz19b.cpp 작성
# - UART 통신으로 9-byte 데이터 프레임 읽기
# - CO2 ppm 추출
# - Serial 출력으로 값 확인

# 빌드 및 업로드
pio run -e sensor-node -t upload

# 시리얼 모니터로 확인
pio device monitor
```

### 6.2 백엔드 담당: Issue #50 (TimescaleDB 스키마)

```bash
# 브랜치 생성
git checkout -b backend/FR-103-timescaledb-schema

# 작업: backend/app/models/sensor_data.py 작성
# - sensor_data hypertable 생성 SQL
# - continuous aggregate (1분 평균) 생성
# - retention policy (30일)

# DB에 적용
psql -h localhost -U hp015 -d hp015 -f backend/migrations/001_init.sql
```

### 6.3 프론트엔드 담당: Issue #61 (대시보드 레이아웃)

```bash
# 브랜치 생성
git checkout -b frontend/FR-401-dashboard-layout

# 작업: frontend/src/ 구조 생성
# - App.tsx: 5개 화면 라우팅
# - components/Sidebar.tsx: 좌측 메뉴
# - store/dashboardStore.ts: Zustand store interface

# 실행 확인
npm run dev
```

### 6.4 PR 생성

```bash
# 변경사항 커밋
git add -A
git commit -m "feat(firmware): FR-101 implement MH-Z19B CO2 sensor driver

- UART 통신으로 9-byte 데이터 프레임 파싱
- CO2 ppm 값 추출
- Serial 출력으로 측정값 확인

Closes #39"

# 브랜치 푸시
git push origin firmware/FR-101-mhz19b-co2

# GitHub에서 PR 생성 (PR 템플릿 자동 적용)
```

---

## 7. 커뮤니케이션 & 워크플로우

### 7.1 브랜치 네이밍

상세는 `.github/CONTRIBUTING.md` 섹션 2 참조. 요약:

```
<component>/<FR-XXX 또는 설명>
```

예시: `firmware/FR-101-gas-collection`, `backend/FR-103-data-storage`

### 7.2 커밋 컨벤션

```
<type>(<scope>): <subject>

<body>
```

| Type | 설명 |
|------|------|
| `feat` | 새 기능 구현 (FR-XXX) |
| `fix` | 버그 수정 |
| `refactor` | 리팩토링 |
| `docs` | 문서 변경 |
| `chore` | 설정, 의존성 |
| `exp` | 실험 (EXP-X) |

### 7.3 이슈 의존성

각 이슈에는 "선행 이슈"와 "후속 이슈" 섹션이 있다. 선행 이슈가 완료되지 않으면 착수할 수 없다. 즉시 착수 가능한 이슈:

| 이슈 | 설명 |
|------|------|
| #34 | 프로젝트 디렉토리 구조 생성 |
| #35 | Docker Compose 설정 |
| #46 | 센서 노드 조립 (하드웨어) |
| #47 | 웨어러블 노드 조립 (하드웨어) |

### 7.4 용어 참조

문서에 모르는 용어가 나오면 `GLOSSARY.md`를 확인한다. 알고리즘 구현에 수학적 공식이나 계산 예시가 필요하면 `APPENDIX_TECHNICAL.md`를 참조한다.
