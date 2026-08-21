# EXPOSURE DOSE SPEC — 작업자 누적 노출량 사양서

| 항목 | 내용 |
|------|------|
| 문서명 | 작업자 누적 유해가스 노출량 사양서 |
| 버전 | v0.1 |
| 상태 | 초안 (구현 전 검토 필요) |
| 최종 수정일 | 2026-08-21 |
| 관련 요구사항 | FR-701 ~ FR-707 |
| 관련 ADR | ADR-008 (최근접 노드 실측값 사용), ADR-005 (IDW 시각화 전용) |

---

## 1. 개요

기존 경보는 **순간값**만 본다. CO₂가 1,200ppm이면 `level1_caution`이고, 900ppm으로 내려가면 정상이다. 그런데 산업위생에서 유해가스 위험은 순간 농도만이 아니라 **농도 × 시간**으로 결정된다. 1,200ppm에서 6시간 일한 작업자와 방금 들어온 작업자는 같은 상태가 아니지만, 현재 시스템은 둘을 구분하지 못한다.

이 기능은 작업자별로 **누적 노출량(dose)**을 적산하고, 노출 기준 대비 소진율을 대시보드에 표시한다.

```
순간 농도 C(t)  →  ∫ C dt  →  누적 노출량 (ppm·min)  →  기준 대비 소진율 (%)
```

### 1.1 면책 (필수)

> 본 기능이 산출하는 노출량은 **개인 시료채취(personal sampling)를 통한 법정 작업환경측정을 대체하지 않는다.** 고정 센서 노드의 측정값을 작업자 위치에 대입한 추정값이며, 아래 §7의 오차 요인을 포함한다. 노출 기준값은 참고 문헌 기반이며 특정 국가의 법정 기준을 보증하지 않는다. 최종 작업 중지 판단은 현장 관리자에게 있다.

이 문구는 `08_SAFETY_AND_LIMITATIONS.md`에 병합하고, 대시보드 노출량 패널 하단에 축약형으로 상시 표시한다.

---

## 2. 핵심 개념과 변수명

구현 전에 이름을 고정한다. 백엔드 필드명, DB 컬럼명, WebSocket 페이로드 키, 프론트 타입명이 모두 아래 표를 따른다.

### 2.1 노출량 관련

| 변수명 | 타입 | 단위 | 설명 |
|--------|------|------|------|
| `dose_ppm_min` | number\|null | ppm·min | 현재 노출 윈도우의 누적 노출량. 적산값 |
| `dose_limit_ppm_min` | number | ppm·min | 8시간 기준 허용 누적량 = `twa_limit_ppm × 480` |
| `dose_fraction` | number\|null | 0~n | `dose_ppm_min / dose_limit_ppm_min`. 1.0 = 기준 소진. 대시보드 게이지의 입력 |
| `dose_worst_case_ppm_min` | number\|null | ppm·min | 전 노드 최댓값 기준 누적. **표시 전용, 경보 미사용** (ADR-008) |
| `twa_8h_ppm` | number\|null | ppm | 윈도우 시작 이후 시간가중평균 = `dose_ppm_min / elapsed_min` |
| `twa_15min_ppm` | number\|null | ppm | 최근 15분 이동 시간가중평균. STEL 비교용 |
| `stel_exceeded` | boolean | — | `twa_15min_ppm > stel_limit_ppm` 여부 |
| `peak_ppm` | number\|null | ppm | 윈도우 내 최고 순간 농도 |
| `peak_at` | string\|null | ISO8601 | 최고 농도 관측 시각 |

### 2.2 노출 윈도우 / 출처

| 변수명 | 타입 | 설명 |
|--------|------|------|
| `window_start` | string | 노출 적산 시작 시각 (ISO8601 UTC) |
| `window_source` | enum | `assignment` \| `manual_reset` \| `shift_rollover` |
| `elapsed_s` | integer | 윈도우 경과 시간(초). 데이터 공백 포함 |
| `accumulated_s` | integer | 실제로 적산에 반영된 시간(초). `elapsed_s - data_gap_s` |
| `data_gap_s` | integer | 측정 공백 누적(초). 이 값이 크면 dose를 신뢰할 수 없다 |
| `exposure_source` | enum | `wearable_direct` \| `nearest_node` \| `unavailable` (ADR-008) |
| `source_node_id` | string\|null | 농도를 가져온 센서 노드 (`nearest_node`일 때) |
| `source_distance_m` | number\|null | 작업자와 해당 노드의 2D 거리 |
| `trust_level` | enum | `high` \| `medium` \| `low`. §4.4 규칙으로 산출 |

### 2.3 식별자

| 변수명 | 설명 |
|--------|------|
| `worker_id` | `workers.id` (BIGINT). 사람 단위 — 노드가 아니다 |
| `node_id` | `wearable-01` 형식. 윈도우 시점의 배정 노드 |
| `metric` | `co2_ppm` \| `co_ppm` \| `h2s_ppm` \| `o2_pct`. **`sensor_data.metric`과 동일한 문자열을 쓴다** |
| `exposure_id` | ULID. 노출 윈도우 1건의 고유 ID |

> `metric` 이름을 새로 만들지 않는다. 기존 `sensor_data` 테이블이 쓰는 값과 어긋나면 조인이 깨진다.

### 2.4 O₂ 전용 변수

O₂는 "축적"되는 물질이 아니다. 산소 **결핍 상태에 노출된 시간**을 누적한다.

| 변수명 | 타입 | 단위 | 설명 |
|--------|------|------|------|
| `o2_deficient_s` | integer | 초 | O₂ < 19.5% 상태 누적 시간 |
| `o2_severe_s` | integer | 초 | O₂ < 16.0% 상태 누적 시간 |
| `o2_min_pct` | number\|null | % | 윈도우 내 최저 산소 농도 |
| `o2_enriched_s` | integer | 초 | O₂ > 23.5% 상태 누적 시간 (화재 위험) |

---

## 3. 노출 기준값

### 3.1 기준 선택 — 고용노동부 고시 (결정)

노출 기준값의 출처는 **고용노동부 「화학물질 및 물리적 인자의 노출기준」 고시**로 한다.

선택 이유는 세 가지다.

| 이유 | 설명 |
|------|------|
| **법적 정합성** | 본 시스템의 적용 대상은 국내 조선소다. 국내 사업장의 노출기준은 산업안전보건법에 근거한 위 고시가 규율한다. 국내 현장에 국제 권고치를 적용하면 시스템이 제시하는 수치와 사업장이 실제로 준수해야 하는 수치가 어긋난다 |
| **보고서 근거 제시** | 심사·보고 단계에서 "이 숫자는 어디서 왔는가"에 대한 답이 법령 고시 조문이 된다. ACGIH TLV는 민간 전문가단체의 **권고** 기준이라 국내에서 법적 강제력을 갖지 않으므로, 같은 질문에 "국제 관행"이라고밖에 답할 수 없다 |
| **현장 수용성** | 안전관리자가 이미 사용하는 기준과 대시보드 수치가 일치해야 경보가 신뢰를 얻는다. 기준이 두 벌이면 현장은 낮은 쪽을 오경보로 취급하게 된다 |

> ACGIH TLV는 **비교 참고용**으로만 문서에 병기할 수 있다. `exposure_limits` 테이블에 넣지 않는다. 기준을 두 벌 운용하면 경보 판정이 어느 쪽을 따르는지 불분명해진다.

이 결정은 `08_SAFETY_AND_LIMITATIONS.md`와 최종 보고서의 "기준 선정 근거" 항목에 동일한 내용으로 반영한다.

### 3.2 값 (고시 원문 대조 전 — 확정값 아님)

> **경고**: 아래 표의 숫자는 고시 원문과 아직 대조하지 않았다. **이 상태로 구현에 들어가지 않는다.** P0-A(고시 원문 대조)를 먼저 끝내고 `verified` 열을 모두 `Y`로 만든 뒤에 시드한다. 근거 없는 숫자를 안전 기준으로 쓰지 않는다는 원칙(§3.3)이 이 표에도 그대로 적용된다.

| metric | `twa_limit_ppm` (8h) | `dose_limit_ppm_min` | `stel_limit_ppm` (15min) | verified | MVP 상태 |
|--------|---------------------:|---------------------:|-------------------------:|:--------:|-----------|
| `co2_ppm` | (고시값) | `twa × 480` | (고시값) | **N** | **활성** |
| `co_ppm` | (고시값) | `twa × 480` | (고시값) | **N** | 미교정 → `null` |
| `h2s_ppm` | (고시값) | `twa × 480` | (고시값) | **N** | 미교정 → `null` |
| `o2_pct` | — | — | — | — | 시간 누적 방식 (§2.4) |

`dose_limit_ppm_min`은 독립적으로 정하는 값이 아니라 `twa_limit_ppm × 480분`으로 파생된다. 고시에서 TWA와 STEL만 확인하면 된다.

> O₂는 노출기준 고시의 대상 물질이 아니다. 산소농도 기준은 산업안전보건기준에 관한 규칙의 **적정공기**(산소 18% 이상 23.5% 미만) 정의를 따르며, 이는 이미 `06_ALERT_RULES.md` §4.2에 반영되어 있다. 노출량이 아니라 **시간 누적**으로 다루는 이유가 여기 있다 — 고시에 O₂의 TWA가 존재하지 않는다.

### 3.3 운용 규칙

- **MUST**: 위 값은 코드에 하드코딩하지 않는다. `thresholds` 테이블과 같은 방식으로 DB에서 관리하고 관리자가 수정할 수 있어야 한다 (FR-201과 동일 원칙).
- **MUST**: 각 행은 출처를 `reference` 컬럼에 보관한다. 고시명·조항·개정일을 포함한 문자열이어야 하며, 빈 문자열이나 "ACGIH" 같은 단어 하나는 허용하지 않는다.
- **MUST**: 고시 원문 대조가 끝나지 않은 metric은 시드하지 않는다. 시드되지 않은 metric은 `status: "unavailable"`, `reason: "limit_unverified"`로 내려간다.
- MQ-7·MQ-136이 미교정인 동안 CO·H₂S는 `dose_ppm_min: null`, `status: "unavailable"`로 내려간다. 파이프라인은 동작하되 값이 없다 (`06_ALERT_RULES.md` §4.3과 동일 정책).

---

## 4. 적산 알고리즘

### 4.1 기본식 (사다리꼴 적분)

농도 샘플이 도착할 때마다 적산한다. 고정 주기 tick이 아니라 **이벤트 구동**이다.

```
Δt        = min(sampled_at - last_sample_at, gap_max_s)
C_avg     = (C_prev + C_now) / 2
dose     += C_avg × (Δt / 60)          # ppm·min
```

### 4.2 데이터 공백 처리 (`gap_max_s`)

노드가 오프라인이거나 UWB가 끊기면 샘플이 안 온다. 이때 두 가지 위험한 선택지가 있다.

| 선택 | 결과 |
|------|------|
| 공백을 0으로 간주 | 노출량 **과소평가**. 안전 시스템에서 최악 |
| 마지막 값을 무한히 유지 | 하루 끊기면 dose가 천문학적으로 뜀. 경보 신뢰도 붕괴 |

- **MUST**: 마지막 값을 유지하되 **최대 `gap_max_s`(기본 60초)까지만** 적산한다. 그 이상은 적산하지 않고 `data_gap_s`에 누적한다.
- **MUST**: `data_gap_s / elapsed_s > 0.2`이면 `trust_level: "low"`로 내리고 대시보드에 "측정 공백 N분" 배지를 표시한다.
- **MUST**: 공백 구간은 dose를 **과소평가하는 방향**임을 UI 툴팁에 명시한다.

### 4.3 노출 윈도우 시작·종료

`worker_assignments` 테이블을 그대로 재사용한다. 새 "교대(shift)" 개념을 만들지 않는다.

| 이벤트 | 동작 |
|--------|------|
| `worker_assignments` INSERT (배정) | 새 노출 윈도우 시작. `window_start = assigned_at`, `window_source = "assignment"` |
| `worker_assignments` UPDATE (`released_at` 설정) | 윈도우 종료. 최종값을 `exposure_shift_log`로 확정 |
| 수동 리셋 API 호출 | 현재 윈도우 확정 후 새 윈도우. `window_source = "manual_reset"` |
| `window_start + 12h` 경과 | 자동 롤오버. `window_source = "shift_rollover"` |

> 배정 이력이 이미 "언제부터 언제까지 누가 어느 노드를 착용했는가"를 담고 있다. 노출 윈도우는 그것과 정확히 같은 구간이다.

### 4.4 신뢰도(`trust_level`) 판정

```
low     : data_gap_s / elapsed_s > 0.2
        | source_distance_m > exposure.max_trust_distance_m (기본 3.0m)
        | exposure_source == "unavailable" 구간이 윈도우의 20% 초과
medium  : source_distance_m > 1.5m
high    : 그 외 (exposure_source == "wearable_direct" 는 항상 high)
```

### 4.5 영속성 (재시작 안전)

- **MUST**: `dose_ppm_min`을 메모리에만 두지 않는다. 백엔드 재시작 시 0으로 리셋되면 8시간 누적이 사라진다.
- **MUST**: 최소 `exposure.flush_interval_s`(기본 10초)마다 `exposure_state` 테이블에 flush한다.
- **MUST**: 기동 시 `exposure_state`에서 활성 윈도우를 복구한다. 다운타임 구간은 `data_gap_s`로 기록한다.
- **SHOULD**: flush는 적산과 분리된 백그라운드 태스크로 둔다 (`retention.py` 패턴).

---

## 5. 경보 연동

### 5.1 노출량 경보 등급

기존 3단계 체계에 그대로 얹는다. `06_ALERT_RULES.md`의 등급 문자열을 재사용한다.

| 등급 | 조건 | `enter_for_ms` | 해제 |
|------|------|----------------|------|
| `level1_caution` | `dose_fraction ≥ 0.5` | 0 (즉시) | **없음 — §5.2** |
| `level2_warning` | `dose_fraction ≥ 0.8` | 0 (즉시) | 없음 |
| `level3_critical` | `dose_fraction ≥ 1.0` \| `stel_exceeded` | 0 (즉시) | 없음 |

### 5.2 노출량 경보는 자동 해제되지 않는다 (중요)

가스 농도 경보는 값이 내려가면 해제된다(Hysteresis). **노출량은 다르다. 누적값은 줄어들지 않는다.** 몸에 들어간 가스가 저절로 사라지지 않으므로 `dose_fraction`은 단조 증가한다.

- **MUST**: 노출량 경보는 Hysteresis를 적용하지 않는다. `exit_threshold` 개념 자체가 없다.
- **MUST**: 해제는 **노출 윈도우 종료(작업자 퇴장 또는 수동 리셋)로만** 이루어진다.
- **MUST**: 수동 리셋은 `supervisor` 이상 권한이며 `audit_log`에 기록한다 (FR-605). 사유(`reason`) 입력을 필수로 받는다.

> 이 규칙을 놓치면 기존 경보 엔진의 de-escalation 로직이 노출량 경보를 임의로 내려버린다. `alert_type`으로 분기해야 한다.

### 5.3 alert_key / alert_type 규약

기존 `alerts/state/{node_id}/{alert_key}` 토픽 구조를 따른다.

| 항목 | 값 |
|------|-----|
| `alert_type` | `exposure_dose` |
| `alert_key` | `exposure_co2` / `exposure_co` / `exposure_h2s` / `o2_deficiency_time` |
| `source_node_id` | 웨어러블 노드 ID (`wearable-01`) — 가스를 잰 센서 노드가 아니다 |
| `metric` | `co2_ppm` 등 |
| `trigger_value` | `dose_ppm_min` |
| `threshold` | `dose_limit_ppm_min` |

- **MUST**: `source_node_id`는 **웨어러블**이다. 노출은 사람에게 귀속되지 발생 노드에 귀속되지 않는다. 이걸 센서 노드로 잘못 넣으면 대시보드에서 센서 카드가 빨갛게 뜬다.
- **MUST**: 경보 메시지에 작업자 이름을 포함한다 (`workers.name`, FR-306 재사용).

### 5.4 O₂ 시간 누적 경보

| 등급 | 조건 |
|------|------|
| `level1_caution` | `o2_deficient_s ≥ 300` (5분) |
| `level2_warning` | `o2_deficient_s ≥ 900` (15분) |
| `level3_critical` | `o2_severe_s ≥ 60` (1분) |

> 기존 O₂ 순간값 경보(`o2_low` / `o2_high`)와 **독립적으로** 동작한다. 서로 대체하지 않는다.

---

## 6. 인터페이스 계약

### 6.1 WebSocket 메시지 (신규 타입)

`frontend/src/types/ws.ts`의 `WSMessageType`에 `worker_exposure`를 추가한다.

```json
{
  "type": "worker_exposure",
  "worker_id": 7,
  "worker_name": "김철수",
  "node_id": "wearable-01",
  "exposure_id": "01J6X3R8K7VQ2NTP5Z9MA4HWBC",
  "window_start": "2026-08-21T01:00:00.000Z",
  "elapsed_s": 7200,
  "accumulated_s": 7080,
  "data_gap_s": 120,
  "trust_level": "medium",
  "timestamp": "2026-08-21T03:00:00.000Z",
  "metrics": {
    "co2_ppm": {
      "status": "active",
      "exposure_source": "nearest_node",
      "source_node_id": "sensor-02",
      "source_distance_m": 1.8,
      "dose_ppm_min": 96000.0,
      "dose_limit_ppm_min": 2400000.0,
      "dose_fraction": 0.04,
      "dose_worst_case_ppm_min": 104400.0,
      "twa_8h_ppm": 813.6,
      "twa_15min_ppm": 902.0,
      "stel_limit_ppm": 30000.0,
      "stel_exceeded": false,
      "peak_ppm": 1310.0,
      "peak_at": "2026-08-21T02:14:08.220Z",
      "alert_level": "normal"
    },
    "co_ppm":  { "status": "unavailable", "reason": "uncalibrated" },
    "h2s_ppm": { "status": "unavailable", "reason": "uncalibrated" },
    "o2_pct": {
      "status": "active",
      "exposure_source": "wearable_direct",
      "source_node_id": null,
      "source_distance_m": null,
      "o2_deficient_s": 0,
      "o2_severe_s": 0,
      "o2_enriched_s": 0,
      "o2_min_pct": 20.4,
      "alert_level": "normal"
    }
  }
}
```

- 발행 주기: **5초** 스로틀 (센서 샘플마다 보내지 않는다 — dose는 초 단위로 급변하지 않는다)
- 경보 등급 변화 시에는 스로틀을 무시하고 즉시 발행한다
- JSON Schema: `schemas/worker-exposure.schema.json`

### 6.2 REST API

| 메서드 | 경로 | 권한 | 설명 |
|--------|------|------|------|
| GET | `/api/exposure/current` | viewer+ | 활성 윈도우 전체 (대시보드 초기 로드) |
| GET | `/api/exposure/current/{node_id}` | viewer+ | 노드 1개 |
| GET | `/api/exposure/history` | viewer+ | `worker_id`, `from`, `to` 쿼리. 확정된 과거 윈도우 |
| POST | `/api/exposure/reset` | supervisor+ | 수동 리셋. body: `{node_id, reason}`. CSRF + 감사 로그 필수 |
| GET | `/api/exposure/limits` | viewer+ | 노출 기준값 조회 |
| PUT | `/api/exposure/limits/{metric}` | admin | 기준값 수정. 감사 로그 필수 |

> 전 엔드포인트는 `enforce_authentication` 게이트 아래에 있다 (AUTH-3). 신규 경로를 `PUBLIC_PATHS`에 넣지 않는다.

### 6.3 DB 스키마 (`008_exposure.sql`)

```sql
-- 노출 기준값 (thresholds 테이블과 같은 철학: 코드가 아니라 DB가 소스)
CREATE TABLE IF NOT EXISTS exposure_limits (
    metric              TEXT PRIMARY KEY,
    twa_limit_ppm       DOUBLE PRECISION,
    dose_limit_ppm_min  DOUBLE PRECISION,
    stel_limit_ppm      DOUBLE PRECISION,
    reference           TEXT NOT NULL,      -- 출처 문헌. 빈 문자열 금지
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 활성 노출 윈도우 상태 (재시작 복구용, §4.5)
CREATE TABLE IF NOT EXISTS exposure_state (
    exposure_id     TEXT PRIMARY KEY,
    worker_id       BIGINT NOT NULL REFERENCES workers (id) ON DELETE CASCADE,
    node_id         TEXT NOT NULL,
    metric          TEXT NOT NULL,
    window_start    TIMESTAMPTZ NOT NULL,
    window_source   TEXT NOT NULL,
    dose_ppm_min    DOUBLE PRECISION NOT NULL DEFAULT 0,
    dose_worst_case_ppm_min DOUBLE PRECISION NOT NULL DEFAULT 0,
    o2_deficient_s  INTEGER NOT NULL DEFAULT 0,
    o2_severe_s     INTEGER NOT NULL DEFAULT 0,
    o2_enriched_s   INTEGER NOT NULL DEFAULT 0,
    peak_ppm        DOUBLE PRECISION,
    peak_at         TIMESTAMPTZ,
    o2_min_pct      DOUBLE PRECISION,
    last_value      DOUBLE PRECISION,
    last_sample_at  TIMESTAMPTZ,
    data_gap_s      INTEGER NOT NULL DEFAULT 0,
    closed_at       TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 한 (worker, node, metric) 조합에 활성 윈도우는 하나뿐이다.
-- worker_assignments의 uq_worker_assignments_active_node와 같은 이유로 DB 제약이다.
CREATE UNIQUE INDEX IF NOT EXISTS uq_exposure_state_active
    ON exposure_state (worker_id, node_id, metric)
    WHERE closed_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_exposure_state_worker
    ON exposure_state (worker_id, window_start DESC);

-- 확정된 과거 윈도우 (사고 조사용, 영구 보관 — retention 없음)
CREATE TABLE IF NOT EXISTS exposure_shift_log (
    exposure_id     TEXT PRIMARY KEY,
    worker_id       BIGINT NOT NULL,
    worker_name     TEXT NOT NULL,     -- 비정규화: 계정/작업자 삭제 후에도 추적 가능
    node_id         TEXT NOT NULL,
    metric          TEXT NOT NULL,
    window_start    TIMESTAMPTZ NOT NULL,
    window_end      TIMESTAMPTZ NOT NULL,
    dose_ppm_min    DOUBLE PRECISION,
    dose_fraction   DOUBLE PRECISION,
    twa_8h_ppm      DOUBLE PRECISION,
    peak_ppm        DOUBLE PRECISION,
    o2_deficient_s  INTEGER,
    data_gap_s      INTEGER NOT NULL DEFAULT 0,
    trust_level     TEXT NOT NULL,
    max_alert_level TEXT NOT NULL
);
```

### 6.4 프론트엔드

| 항목 | 내용 |
|------|------|
| Store | `dashboardStore`에 `worker_exposure: Record<NodeId, ExposureState>` 추가 |
| 컴포넌트 | `ExposureGauge.tsx` — `dose_fraction` 원형 게이지. 0.5/0.8/1.0에 눈금 |
| 배치 | **웨어러블 카드 영역** 하단에 요약(소진율 %), 상세는 신규 `ExposureScreen.tsx` |

> **컴포넌트명 주의**: 대시보드 UI가 리팩터링 중이라 파일명이 유동적이다. 본 문서는 특정 파일명이 아니라 **역할**로 배치를 지정한다. 해당 브랜치(`frontend/FR-401-monitoring-console-redesign`)에서 `WearableCard.tsx`는 `WearableStrip.tsx`로 재구성되었다. 구현 시점의 실제 컴포넌트를 확인하고 붙인다.
| 신뢰도 표시 | `trust_level != "high"`면 게이지에 빗금 오버레이 + 사유 툴팁 |
| 미교정 표시 | `status: "unavailable"`인 metric은 회색 처리 + "교정 필요". 0%로 표시하지 않는다 |

> **MUST**: `dose_fraction`이 `null`인 것과 `0`인 것을 화면에서 구분한다. 미교정 센서를 "노출 0%"로 보여주면 안전하다고 오해한다.

---

## 7. 알려진 한계 (문서·화면에 명시)

| # | 한계 | 영향 |
|---|------|------|
| 1 | 작업자 위치 농도는 최근접 고정 노드 실측값 대입이다 (ADR-008) | 노드 사이 중간 위치에서 오차. 정량화 안 됨 |
| 2 | CO·H₂S는 MQ 센서 미교정으로 산출 불가 | MVP 기간 내내 `null` |
| 3 | UWB 위치가 끊기면 최근접 노드를 정할 수 없다 | 적산 중단 → `data_gap_s` 증가 |
| 4 | 개인 호흡영역(breathing zone) 측정이 아니다 | 법정 작업환경측정 대체 불가 |
| 5 | 노출 기준값은 참고 문헌 기반 | 특정 국가 법정 기준 보증 없음 |
| 6 | 마스크·호흡보호구 착용 여부를 반영하지 않는다 | 보호구 착용 시 실제 노출은 더 낮다 → **과대평가** 방향 |
| 7 | 흡수·배출 생리 모델이 없다. 단순 시간적분이다 | 체내 축적량이 아니라 **환경 노출량**이다. 용어를 혼동하지 말 것 |

> #7은 UI 문구에 직결된다. "몸에 축적된 양"이 아니라 **"누적 노출량"**으로 표기한다. 전자는 생리학적 주장이고 이 시스템은 그걸 측정하지 않는다.

---

## 8. 기능 요구사항 (PRD 편입용)

`01_PRD.md`에 **기능 6: 작업자 누적 노출량 관리**로 추가한다.

| ID | 강도 | 요구사항 |
|----|------|----------|
| FR-701 | MUST | 작업자별 누적 노출량을 §4.1 사다리꼴 적분으로 적산한다 |
| FR-702 | MUST | 노출 농도는 최근접 센서 노드 실측값을 사용한다. IDW 보간값을 사용하지 않는다 (ADR-005, ADR-008) |
| FR-703 | MUST | `dose_fraction` 0.5 / 0.8 / 1.0에서 3단계 경보를 발령한다. 자동 해제하지 않는다 (§5.2) |
| FR-704 | MUST | 누적값은 DB에 영속화하며 백엔드 재시작 후 복구된다 (§4.5) |
| FR-705 | MUST | 측정 공백은 최대 `gap_max_s`까지만 적산하고 `data_gap_s`로 기록·표시한다 |
| FR-706 | MUST | 노출 윈도우는 `worker_assignments` 구간과 일치한다. 수동 리셋은 supervisor+ 권한이며 감사 로그를 남긴다 |
| FR-707 | SHOULD | O₂ 결핍 노출 시간(`o2_deficient_s`)을 별도 누적하고 §5.4 기준으로 경보한다 |
| FR-708 | MAY | 교대 종료 시 작업자별 노출 리포트를 CSV로 내보낸다 |

### 실험 연결 (`07_EXPERIMENT_PLAN.md` 편입용)

| Test ID | 내용 | 합격 기준 |
|---------|------|-----------|
| EXP-7 | 알려진 농도 프로파일을 주입해 적산 정확도 검증 | 해석적 계산값 대비 오차 ≤ 2% |
| EXP-7.1 | 적산 중 백엔드 강제 재시작 | 복구 후 dose 연속성 유지, 손실 ≤ `flush_interval_s` 분량 |
| EXP-7.2 | 노드 오프라인 5분 구간 주입 | `data_gap_s` 정확히 기록, dose 폭주 없음 |

---

## 9. 미결 사항

| ID | 항목 | 상태 |
|----|------|------|
| OQ-E1 | 노출 기준값 출처 | **해결** — 고용노동부 고시로 확정 (§3.1). 단 원문 대조(P0-A)가 남아 있다 |
| OQ-E2 | 작업자가 밀폐공간 밖으로 나갔을 때(측위 이탈) 적산을 멈출 것인가 계속할 것인가 | 미해결 |
| OQ-E3 | `dose_worst_case`를 화면에 항상 노출할 것인가, 신뢰도 낮을 때만 노출할 것인가 | 미해결 |
