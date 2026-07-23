# CONTRIBUTING — 26_HP015 개발 가이드

## 1. 개발 환경

### 1.1 필수 도구

| 도구 | 버전 | 용도 |
|------|------|------|
| Node.js | 20+ | 프론트엔드 (React 19) |
| Python | 3.11+ | 백엔드 (FastAPI) |
| PlatformIO Core | 최신 | 펌웨어 빌드 및 업로드 |
| Docker | 24+ | TimescaleDB, Mosquitto 로컬 실행 |
| Git | 2.40+ | 버전 관리 |

### 1.2 로컬 환경 구성

```bash
# 저장소 클론
git clone https://github.com/Yaho03/26_HP015.git
cd 26_HP015

# 인프라 (TimescaleDB + Mosquitto) — compose 파일은 docker/ 에 있다
docker compose -f docker/docker-compose.yml up -d

# 백엔드
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload

# 프론트엔드
cd frontend
npm install
npm run dev

# 펌웨어 (노드별)
cd firmware
pio run -e sensor-node    # 빌드만
pio run -t upload -e sensor-node  # 업로드
```

> 각 디렉토리는 아직 생성 전입니다. 구현 시 해당 이슈에서 생성합니다.

---

## 2. 브랜치 전략

### 2.1 브랜치 네이밍

```
main                         # 배포 가능 상태
├── firmware/FR-101-gas-collection
├── backend/FR-103-data-storage
├── frontend/FR-401-monitoring-screen
├── 3d-twin/FR-501-twin-base
├── hardware/uwb-anchor-mount
├── experiment/EXP-2-uwb-accuracy
├── infra/docker-compose
└── docs/update-alert-rules
```

**규칙**:
- 브랜치 접두어: 컴포넌트명 (`firmware/`, `backend/`, `frontend/`, `3d-twin/`, `hardware/`, `experiment/`, `infra/`, `docs/`)
- 브랜치 이름에 FR-XXX 또는 EXP-X 포함
- `main` 브랜치에 직접 push 금지

### 2.2 PR 흐름

```
feature branch → main
```

1. 이슈에서 브랜치 생성
2. 구현 및 자체 검증
3. PR 생성 (`.github/PULL_REQUEST_TEMPLATE.md` 사용)
4. 리뷰어 승인 후 merge

---

## 3. 커밋 컨벤션

### 3.1 커밋 메시지 형식

```
<type>(<scope>): <subject>

<body>
```

### 3.2 Type

| Type | 설명 |
|------|------|
| `feat` | 새로운 기능 (FR-XXX 구현) |
| `fix` | 버그 수정 |
| `refactor` | 리팩토링 (동작 변경 없음) |
| `docs` | 문서 변경 |
| `test` | 테스트 추가/수정 |
| `chore` | 빌드, 설정, 의존성 |
| `exp` | 실험 (EXP-X) |

### 3.3 Scope (권장)

`firmware`, `backend`, `frontend`, `3d-twin`, `hardware`, `schema`, `mqtt`, `alert`, `uwb`, `infra`, `docs`

### 3.4 예시

```
feat(firmware): FR-101 implement MQ-7 CO sensor reading via ADS1115

- ADS1115 16-bit ADC로 MQ-7 아날로그 출력 디지털 변환
- Rs/R0 ratio 계산 및 JSON envelope로 MQTT 전송
- calibration_status 필드 포함 (uncalibrated/calibrated)

Closes #12
```

---

## 4. JSON Schema 변경 규칙

### 4.1 추가 속성 금지 원칙

모든 schema object는 `additionalProperties: false`를 사용한다.

**개발 단계 정책**: 개발 기간(첫 3개월)에는 `additionalProperties: true`를 사용하여 펌웨어/백엔드/프론트엔드 병렬 개발 시 스키마 충돌을 완화한다. 최종 통합 테스트 달(10월)에 `false`로 전환하여 엄격 모드로 검증한다.

**예외** (동적 키-값 객체):
- `twin-delta.schema.json`의 `changes` — 변경된 필드명이 동적
- `twin-snapshot.schema.json`의 `latest_values`, `active_alerts` — 노드 ID, alert_key가 동적

### 4.2 버전 관리

```
schema_version: "1.1"
```

- 필드 추가 시 minor 버전 bump (`1.1` → `1.2`)
- 필드 제거/타입 변경 시 major 버전 bump (`1.1` → `2.0`)
- `docs/04_DATA_CONTRACT.md`의 버전 정책 섹션 참조

### 4.3 검증 명령

```bash
# JSON 유효성 검사
python3 -c "import json; json.load(open('schemas/XXX.schema.json')); print('OK')"

# 전체 스키마 일괄 검사
for f in schemas/*.schema.json; do
  python3 -c "import json; json.load(open('$f'))" && echo "$f: OK" || echo "$f: FAIL"
done
```

---

## 5. 안전 중심 개발 원칙

### 5.1 Safety-Critical 변경 시 필수 확인사항

경보 임계값, Hysteresis, 진동 패턴, 낙상 감지 알고리즘, 좌표 변환 등 작업자 안전에 직접 영향을 미치는 코드 변경 시:

1. `safety-critical` 라벨 부착
2. PR 본문에 안전 영향 분석 작성
3. `docs/06_ALERT_RULES.md`와 코드 구현이 일치하는지 확인
4. 임계값 하드코딩 금지 (DB 또는 설정 파일에서 관리)

### 5.2 IDW 제약

IDW 공간 보간은 시각화 전용이다. 경보 판정에 IDW 추정값을 사용하지 않는다. (ADR-005)

### 5.3 좌표 변환

Physical 좌표계 (Z-up)와 Three.js 좌표계 (Y-up) 간 변환:

```
three_x = physical_x
three_y = physical_z
three_z = -physical_y
```

---

## 6. 이슈 관리

### 6.1 라벨 체계

| 카테고리 | 라벨 | 용도 |
|----------|------|------|
| **Component** | `firmware`, `backend`, `frontend`, `3d-twin`, `hardware`, `infra` | 구현 영역 |
| **Priority** | `P0-critical`, `P1-high`, `P2-medium`, `P3-low` | 우선순위 |
| **Type** | `enhancement`, `bug`, `task`, `experiment`, `refactor`, `documentation` | 작업 유형 |
| **Domain** | `safety-critical`, `mqtt`, `uwb` | 도메인 특화 |

> GitHub 기본 라벨(`enhancement`, `bug`, `documentation` 등) 외에 프로젝트 전용 커스텀 라벨을 사용한다. 커스텀 라벨 목록은 GitHub 저장소 Labels 페이지에서 확인한다.

### 6.2 Milestone

| Milestone | 기간 | 주요 산출물 |
|-----------|------|------------|
| M1 | 2026.07 | 하드웨어 조립, MQTT 전송 검증 |
| M2 | 2026.08 | 백엔드·DB, 대시보드 기본 화면 |
| M3 | 2026.09 | UWB 연동, 3D 디지털 트윈 초안 |
| M4 | 2026.10 | 전체 통합 시연, 실험 평가 |

### 6.3 이슈 템플릿

| 템플릿 | 용도 |
|--------|------|
| Feature (FR-XXX) | PRD 기능 요구사항 구현 |
| Bug | 버그 리포트 |
| Task | 비기능 작업 (설정, 리팩토링) |
| Experiment (EXP-X) | 실험 검증 |

---

## 7. 문서 구조

> 상세한 문서 맵은 `README.md` 및 `docs/00_PROJECT_OVERVIEW.md` 섹션 9 참조.

| 문서 | 용도 |
|------|------|
| `docs/01_PRD.md` | 요구사항 정의 (단일 진실 공급원) |
| `docs/02_SYSTEM_ARCHITECTURE.md` | 시스템 아키텍처 |
| `docs/03_HARDWARE_DESIGN.md` | 하드웨어 설계 |
| `docs/04_DATA_CONTRACT.md` | MQTT 데이터 계약 |
| `docs/05_DIGITAL_TWIN_SPEC.md` | 디지털 트윈 사양 |
| `docs/06_ALERT_RULES.md` | 경보 판정 규칙 |
| `docs/07_EXPERIMENT_PLAN.md` | 실험 계획 |
| `docs/08_SAFETY_AND_LIMITATIONS.md` | 안전 및 제한 사항 |
| `docs/09_DEMO_SCENARIOS.md` | 시연 시나리오 |
| `docs/10_UI_FLOW.md` | 대시보드 UI/UX 사양 |
