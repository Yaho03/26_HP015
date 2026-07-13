# 26_HP015 — 스마트해운물류
## IoT 센서 시계열 분석 및 3D 디지털 트윈 기반 조선소 밀폐공간 모니터링 시스템

---

## 프로젝트 개요

조선소 밀폐공간 내 유해 가스 농도 및 작업자 상태를 실시간으로 모니터링하는 IoT 시스템.
Full-Spec 센서 노드 4개와 작업자 웨어러블 노드 1개로 구성되며 MQTT를 통해 데이터를 전송한다.

---

## 문서 구조

| 문서 | 내용 |
|------|------|
| [docs/00_PROJECT_OVERVIEW.md](./docs/00_PROJECT_OVERVIEW.md) | 프로젝트 개요 — 대상 사용자, 시스템 구성, 기술 스택, 마일스톤 |
| [docs/01_PRD.md](./docs/01_PRD.md) | 제품 요구사항 정의서 — 기능 요구사항(FR-ID), 임계값, 성공 기준 |
| [docs/02_SYSTEM_ARCHITECTURE.md](./docs/02_SYSTEM_ARCHITECTURE.md) | 시스템 아키텍처 — 구성도, 데이터 흐름, 좌표계, 기술 스택 |
| [docs/03_HARDWARE_DESIGN.md](./docs/03_HARDWARE_DESIGN.md) | 하드웨어 설계서 — 회로, 핀맵, 분압, 전원, 교정 절차 |
| [docs/BOM.md](./docs/BOM.md) | 구매 부품 목록 (BOM) — 구간별 구매 계획, 단가, 링크 |
| [docs/04_DATA_CONTRACT.md](./docs/04_DATA_CONTRACT.md) | MQTT 데이터 계약서 — 토픽, Envelope, Payload Schema, QoS |
| [docs/05_DIGITAL_TWIN_SPEC.md](./docs/05_DIGITAL_TWIN_SPEC.md) | 디지털 트윈 사양서 — Twin 객체 모델, 좌표계, 동기화 규칙 |
| [docs/06_ALERT_RULES.md](./docs/06_ALERT_RULES.md) | 경보 판정 규칙서 — 임계값, Hysteresis, 3단계 알고리즘 |
| [docs/07_EXPERIMENT_PLAN.md](./docs/07_EXPERIMENT_PLAN.md) | 실험 계획서 — 6개 실험, 합격 기준(P95), Ground Truth |
| [docs/08_SAFETY_AND_LIMITATIONS.md](./docs/08_SAFETY_AND_LIMITATIONS.md) | 안전 및 제한 사항 — 면책, 센서 신뢰성, IDW 한계 |
| [docs/09_DEMO_SCENARIOS.md](./docs/09_DEMO_SCENARIOS.md) | 시연 시나리오 — 6개 시나리오, 데이터 주입 방식 |
| [docs/adr/](./docs/adr/) | 아키텍처 결정 기록 (ADR-001 ~ ADR-005) |
| [schemas/](./schemas/) | JSON Schema (sensor-gas, sensor-env, sensor-status, wearable-location, wearable-imu, wearable-vital, node-connection, alert-event, twin-delta, twin-snapshot) |

---

## 하드웨어 구성 요약

| 기기 | 수량 | 메인보드 | 주요 기능 |
|------|------|---------|----------|
| 센서 노드 (Full-Spec) | 4 | ESP32 DevKitC V4 | CO₂/CO/H₂S/가스저항/온습도 + UWB Anchor (전 노드 동일 풀스펙) |
| 웨어러블 노드 | 1 | ESP32 DevKitC V4 | O₂/낙상 감지 + UWB Tag + 진동 알림 |

> UWB 위치 측위: 센서 노드 4개(앵커) + 웨어러블 1개(태그), DS-TWR 방식
> 전체 구매 목록은 [BOM.md](./docs/BOM.md), 하드웨어 설계는 [03_HARDWARE_DESIGN.md](./docs/03_HARDWARE_DESIGN.md) 참조

---

## 기술 스택

| 계층 | 기술 |
|------|------|
| 펌웨어 | Arduino Framework (ESP32), PlatformIO |
| 통신 | MQTT (Mosquitto), UWB DS-TWR (DWM1000) |
| 백엔드 | FastAPI (Python) |
| DB | TimescaleDB |
| 실시간 | WebSocket |
| 프론트엔드 | React 19 + TypeScript |
| 3D | React Three Fiber + Three.js |
| 상태 관리 | Zustand |
| 차트 | Recharts |

---

## 마일스톤

| 시점 | 산출물 |
|------|--------|
| 2026.07 | 하드웨어 조립 완료, 센서 노드 MQTT 전송 검증 |
| 2026.08 | 백엔드 서버·DB 구축, 대시보드 기본 화면 |
| 2026.09 | UWB 위치 추적 연동, 3D 디지털 트윈 초안 |
| 2026.10 | 전체 통합 시연 (시뮬레이션 모형 기준) |
