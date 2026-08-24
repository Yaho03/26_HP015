# HP015 정상 패턴 학습 기반 LSTM Autoencoder 이상징후 탐지 구현 프롬프트

아래 요청을 `/Users/choihwanseok/26_HP015` 프로젝트에서 순서대로 수행해줘.

이 작업의 목표는 **정상 상태의 복합 센서 시계열만 학습한 LSTM Autoencoder가 평소와 다른 변화, 드리프트, 고정값, 결측 및 복합 센서 관계 이상을 탐지하는 연구용 AI 기능**을 구현하는 것이다.

이 모델은 위험가스 종류를 판정하거나 미래의 법정 기준 초과를 보장하는 모델이 아니다. 기존 실측 임계값 경보를 대체하지 않으며, 결과는 반드시 `AI 이상징후`, `Research`, `참고용`으로 표시한다.

---

## 0. 작업 원칙

다음 원칙을 전체 작업에서 지켜라.

1. 정상 데이터만 모델 학습에 사용한다.
2. 인위적으로 만든 이상 데이터는 평가와 시연에만 사용하고 학습에는 사용하지 않는다.
3. 실측값, 시뮬레이션값, AI 복원값을 구분한다.
4. 실제로 유효한 센서 항목만 모델 입력으로 사용한다.
5. 4개 항목만 유효하면 4채널 모델을 만들고 6종이라고 주장하지 않는다.
6. `null`, 오류값, 워밍업 값, 장시간 고정값을 정상 패턴으로 학습하지 않는다.
7. 기존 `alert_engine`, 임계값, hysteresis, 지속 조건, MQTT 경보 발행 및 웨어러블 진동 로직을 변경하지 않는다.
8. AI 오류, 모델 파일 누락 또는 데이터 부족이 기존 센서 수집과 안전 경보를 막아서는 안 된다.
9. AI가 판단할 수 없으면 `정상`이 아니라 `데이터 부족`, `모델 미준비` 또는 `예측 불가`를 반환한다.
10. 실제 센서 성능으로 검증하지 않은 결과를 현장 안전 성능으로 표현하지 않는다.

---

## 1. 반드시 먼저 읽을 파일

구현 전에 다음 파일을 읽고 현재 구조와 규칙을 정리해라.

- `AGENTS.md`
- `docs/01_PRD.md`
- `docs/02_SYSTEM_ARCHITECTURE.md`
- `docs/04_DATA_CONTRACT.md`
- `docs/06_ALERT_RULES.md`
- `docs/07_EXPERIMENT_PLAN.md`
- `docs/08_SAFETY_AND_LIMITATIONS.md`
- `docs/HW_SESSION_HANDOFF_20260819.md`
- `schemas/sensor-gas.schema.json`
- `schemas/sensor-env.schema.json`
- `backend/migrations/001_init.sql`
- `backend/app/services/ingest.py`
- `backend/app/repositories/sensor_data_repository.py`
- `backend/app/services/ws_manager.py`
- `backend/app/main.py`
- `frontend/src/hooks/useWebSocket.ts`
- `frontend/src/store/dashboardStore.ts`
- `frontend/src/types/ws.ts`
- `frontend/src/screens/ChartScreen.tsx`
- `frontend/src/components/SensorCard.tsx`

읽은 뒤 아래 내용을 먼저 보고해라.

```text
현재 sensor_data 구조:
실제 저장되는 metric:
live/simulation 구분 보존 여부:
교정 상태와 quality 보존 여부:
실제 sampling interval:
사용 가능한 ML 라이브러리:
현재 유효 데이터 파일 또는 DB 존재 여부:
기존 안전 경보와 AI 기능을 분리할 지점:
```

확인되지 않은 내용을 가정하지 마라.

---

## 2. 이번 구현의 정확한 AI 문제 정의

### 2.1 모델 종류

- Multivariate LSTM Autoencoder
- 학습 방식: 정상 데이터 기반 비지도 이상 탐지
- 입력: 최근 10분간의 유효한 복합 센서 시계열
- 리샘플링 간격: 기본 10초
- 기본 sequence length: 60
- 출력: 입력 시계열의 정상 패턴 복원값
- 이상 판단: 실제값과 복원값의 차이로 계산한 anomaly score

### 2.2 우선 입력 후보

다음 순서로 실제 유효성을 확인해 입력 feature를 결정해라.

```text
co2_ppm
co_rs_r0_ratio
h2s_rs_r0_ratio
mq2_rs_r0_ratio
temperature_c
humidity_pct
```

보조 후보:

```text
gas_resistance_ohm
iaq_index        # iaq_accuracy >= 2일 때만 검토
pressure_hpa
```

규칙:

- MQ 계열이 교정되지 않았으면 `estimated_ppm`을 사용하지 않는다.
- 교정 전 MQ 센서는 원시 ADC보다 우선적으로 `rs_r0_ratio`의 유효성을 확인한다.
- `rs_r0_ratio`가 계산되지 않으면 유효한 원시값을 사용할 수 있지만 feature manifest에 정확한 이름을 기록한다.
- O2는 웨어러블 이동 센서이므로 1차 고정형 노드 모델에 임의로 합치지 않는다.
- feature 수를 코드에 6으로 하드코딩하지 말고 artifact의 manifest에서 읽는다.

### 2.3 모델이 탐지하려는 이상

- 순간 급등 또는 급락
- 완만한 센서 드리프트
- 특정 값으로 고정되는 stuck-at 오류
- 데이터 결측 또는 짧은 dropout
- 노이즈 급증
- 여러 센서 사이의 평소 관계와 다른 변화
- 특정 노드만 비정상적으로 움직이는 상황

이상 점수만으로 `가스 누출`, `CO 위험`, `H2S 위험`을 단정하지 마라.

---

## 3. 1단계 — 정상 실측 데이터 진단

DB, CSV 또는 Parquet 중 실제 제공된 입력을 지원해라. 데이터가 아직 없으면 학습을 위조하지 말고 데이터 로더, 진단 코드 및 작은 테스트 fixture까지만 구현한다.

진단 항목:

- 데이터 시작/종료 시각
- node별 관측 기간
- metric별 행 수
- 실제 sampling interval의 중앙값과 분포
- `null`, NaN, 무한값
- 0 고정값
- 동일값 장시간 반복
- 비정상적인 급등/급락
- 중복 timestamp
- 결측 구간 길이
- node offline 구간
- calibration 및 sensor quality
- live/simulation 비율
- 워밍업으로 제외해야 하는 구간

최소 진단 결과 형식:

```text
STATUS: DATA_READY | DATA_PARTIAL | DATA_UNAVAILABLE
NODES:
FEATURES_VALID:
FEATURES_REJECTED:
START_AT:
END_AT:
SAMPLING_INTERVAL_MEDIAN:
VALID_RATIO_BY_FEATURE:
LONGEST_GAP_BY_FEATURE:
CONSTANT_RUNS:
LIVE_SIMULATION_SPLIT:
NOTES:
```

정상 데이터로 볼 수 없는 구간을 임의로 삭제하지 말고 제외 규칙과 개수를 기록해라.

현재 데이터가 없거나 유효 feature가 2개 미만이면 모델 학습 상태를 다음과 같이 남긴다.

```text
STATUS: MODEL_NOT_TRAINED_DATA_PENDING
```

이 경우에도 데이터 준비 코드, 테스트용 정상 fixture, 이상 주입기 및 문서는 구현할 수 있다. 다만 실제 모델 성능 수치를 만들어내지 마라.

---

## 4. 2단계 — 학습 데이터셋 생성

권장 구조:

```text
experiments/lstm_anomaly/
├── README.md
├── requirements.txt
├── configs/
│   └── default.yaml
├── src/
│   ├── data_loader.py
│   ├── data_quality.py
│   ├── preprocessing.py
│   ├── windowing.py
│   ├── anomaly_injection.py
│   ├── model.py
│   ├── train.py
│   ├── evaluate.py
│   └── export_onnx.py
├── tests/
└── artifacts/           # 대용량 artifact는 Git에 커밋하지 않음
```

### 4.1 전처리

- node와 timestamp 기준 정렬
- 실제 sampling interval을 확인한 뒤 기본 10초로 리샘플링
- 리샘플링 값은 metric 특성에 맞는 평균 또는 마지막 유효값 사용
- 짧은 결측만 제한적으로 보간
- 기본 보간 한도는 20초
- 30초 이상 결측이 있는 window는 제외하거나 `insufficient_data`로 처리
- 보간 여부와 결측 mask를 보존
- scaler는 train 데이터에만 fit
- validation/test에는 train scaler만 적용
- node별 offset 차이가 크면 node별 scaler와 global fallback을 검토하고 선택 이유를 기록

### 4.2 Window 생성

기본 형태:

```text
X.shape = [window_count, 60, feature_count]
```

- 하나의 window가 서로 다른 node를 섞지 않게 한다.
- 하나의 window가 split 경계를 넘지 않게 한다.
- 결측 mask를 추가 입력으로 쓸 경우 값 feature와 mask feature를 구분해 manifest에 기록한다.
- source가 simulation인 데이터는 정상 실측 학습셋에 포함하지 않는다.

### 4.3 시간 기준 분할

random shuffle split을 금지한다.

```text
과거 구간       → train
그 다음 구간    → validation
가장 최근 구간  → test
```

기본 비율은 70/15/15로 하되, split 사이에 최소 한 입력 window 길이만큼 purge gap을 둔다. 데이터가 부족하면 비율을 조정하고 이유를 기록한다.

4개 노드 데이터가 있으면 다음 두 평가를 구분한다.

1. 시간 일반화: 모든 node의 과거로 학습하고 최근 구간 테스트
2. node 일반화: 3개 node로 학습하고 남은 1개 node 테스트

3시간 데이터는 프로토타입 검증용일 뿐 현장 일반화 증거가 아님을 명시한다.

---

## 5. 3단계 — LSTM Autoencoder 구현

최초 모델은 작고 재현 가능하게 만든다.

권장 시작 구조:

```text
Input: [batch, 60, feature_count]
Encoder LSTM: hidden size 32
Latent representation: 16~32
Decoder LSTM: hidden size 32
Output Linear: feature_count
Output shape: [batch, 60, feature_count]
Loss: masked MAE 또는 Huber loss
```

규칙:

- 1개 LSTM layer일 때 의미 없는 dropout을 설정하지 않는다.
- 작은 데이터에 큰 모델을 쓰지 않는다.
- Transformer, 복잡한 ensemble, 대규모 hyperparameter search를 추가하지 않는다.
- seed를 고정한다.
- early stopping은 validation loss만 사용한다.
- test 데이터로 threshold나 hyperparameter를 결정하지 않는다.
- 관측되지 않은 값과 장시간 보간값이 loss를 지배하지 않도록 mask loss를 적용한다.

PyTorch를 학습 프레임워크로 우선 사용하고, 서비스 연동이 필요하면 ONNX로 내보내는 방식을 사용한다. 현재 환경에 PyTorch가 없으면 몰래 설치하지 말고 별도 `requirements.txt`에 명시한다. 기존 백엔드 requirements에 무거운 학습 의존성을 바로 추가하지 않는다.

---

## 6. 4단계 — 이상 점수와 기준값 설정

### 6.1 복원 오차

각 feature에 대해 정규화된 실제값과 복원값의 절대 오차를 계산한다.

```text
feature_error[f] = mean(abs(x[f] - reconstructed_x[f]))
```

현재 이상을 빠르게 반영하기 위해 전체 10분을 동일 가중치로 평균하지 말고, 기본적으로 window의 최근 60초에 가중치를 높이거나 최근 60초 오차를 사용한다. 선택 방식을 config와 README에 기록한다.

전체 점수:

```text
anomaly_score = weighted_mean(feature_error)
```

feature별 오차 기여도를 계산해 `top_contributors`를 반환한다.

### 6.2 Threshold

정상 validation 데이터의 anomaly score 분포만 사용한다.

기본값:

```text
threshold = validation normal score의 99th percentile
```

다음 값을 artifact에 저장한다.

- threshold
- threshold quantile
- validation score 통계
- feature별 error 통계
- train/validation 기간

실시간 판정은 기본 3회 연속 초과 후 `anomaly`로 전환하고, threshold 아래로 연속 3회 내려오면 `normal_pattern`으로 복귀한다. 이 상태는 기존 안전 경보 등급과 완전히 별개다.

---

## 7. 5단계 — 평가용 이상 데이터 주입

이상 데이터는 **held-out 정상 test 데이터 복사본**에만 주입한다. 학습 데이터에는 넣지 않는다.

필수 주입 유형:

1. `spike`: 순간 급등/급락
2. `drift`: 일정 시간 동안 서서히 이동
3. `stuck_at`: 특정 값으로 고정
4. `dropout`: 연속 결측
5. `noise_burst`: 일정 구간 노이즈 증가
6. `multi_feature`: 두 개 이상 feature 동시 변화
7. `cross_feature_break`: 평소 같이 움직이던 feature 관계 깨짐

주입기는 seed를 받아 재현 가능해야 하며 다음 metadata를 남긴다.

```text
anomaly_type
start_at
end_at
target_features
magnitude
seed
```

실제 측정 원본을 수정하지 말고 파생 테스트 데이터로만 생성한다.

### 7.1 평가 지표

최소 다음을 측정한다.

- Precision
- Recall
- F1-score
- 정상 test 구간 false positive rate
- anomaly type별 recall
- 평균 detection delay
- node별 성능
- feature 수 변화에 따른 성능

Window 단위와 point 단위 평가 중 선택한 방식을 설명하고 실제 라벨 범위와 맞춰라.

### 7.2 비교 baseline

LSTM Autoencoder만 단독 제시하지 말고 다음과 비교한다.

1. feature별 z-score
2. rolling mean/std 기반 rule
3. 가능하면 PCA reconstruction error
4. LSTM Autoencoder

LSTM이 단순 baseline보다 좋지 않으면 결과를 숨기지 말고 다음 상태를 사용한다.

```text
STATUS: REJECTED_BASELINE_NOT_BEATEN
```

---

## 8. 6단계 — 모델 artifact와 재현성

다음을 저장한다.

```text
model.onnx 또는 model.pt
scaler.json
threshold.json
feature_manifest.json
metrics.json
training_manifest.json
```

`training_manifest.json` 필수 항목:

- model version
- Git commit
- random seed
- 사용 node
- 사용 feature
- 제외 feature와 이유
- 데이터 시작/종료 시각
- train/validation/test 구간
- resampling interval
- window length
- 결측 처리 규칙
- scaler 종류
- model architecture
- hyperparameters
- threshold 설정법
- live/simulation 구성

대용량 원본 데이터와 모델 artifact를 Git에 자동으로 커밋하지 않는다. `.gitignore`를 확인하고 필요한 규칙만 최소 변경한다.

---

## 9. 7단계 — 백엔드 실시간 탐지 연동

모델이 평가를 통과했거나 연구용 시연이 명시적으로 허용된 경우에만 애플리케이션에 연결한다.

권장 파일:

```text
backend/app/services/ai_anomaly_service.py
backend/app/repositories/ai_anomaly_repository.py
backend/app/routers/ai_anomalies.py
backend/app/models/ai_anomaly.py
backend/migrations/008_ai_anomaly_results.sql
```

### 9.1 서비스 동작

1. 서버 시작 시 artifact와 manifest 확인
2. 모델이 없으면 서비스만 `model_not_ready` 상태로 두고 서버는 정상 시작
3. 10초마다 node별 최근 10분 데이터 조회
4. 학습 때와 동일한 feature, 순서, resampling, scaler 적용
5. 유효 데이터 비율 검사
6. LSTM 복원 실행
7. anomaly score와 feature contribution 계산
8. 지속 조건 적용
9. 결과 저장
10. WebSocket broadcast

CPU 추론이 FastAPI event loop를 막지 않도록 별도 thread 실행 또는 적절한 비동기 경계를 사용한다.

### 9.2 데이터 부족 처리

다음 경우 모델을 실행하지 않는다.

- 필요한 window 미충족
- 최근 데이터가 30초 이상 stale
- 필수 feature 누락
- calibration 또는 quality 상태가 허용 기준 미달
- artifact feature manifest와 입력 feature 불일치

응답 상태:

```text
model_not_ready
insufficient_data
stale_data
feature_mismatch
normal_pattern
anomaly_candidate
anomaly
```

`insufficient_data`, `stale_data`, `feature_mismatch`를 정상으로 변환하지 않는다.

### 9.3 WebSocket 메시지

```json
{
  "type": "ai_anomaly",
  "node_id": "sensor-01",
  "evaluated_at": "2026-08-24T12:00:00Z",
  "status": "anomaly",
  "score": 1.42,
  "threshold": 0.85,
  "consecutive_exceedances": 3,
  "top_contributors": [
    { "metric": "co2_ppm", "error": 0.62 },
    { "metric": "humidity_pct", "error": 0.31 }
  ],
  "model_version": "lstm-ae-v0.1.0",
  "is_research_only": true,
  "source_mode": "live"
}
```

### 9.4 안전 분리

- `ai_anomaly_service`에서 `alert_service`, `alert_publisher` 또는 웨어러블 진동 publisher를 호출하지 않는다.
- AI 상태를 기존 `AlertLevel`로 변환하지 않는다.
- AI DB 테이블을 기존 `alert_events`와 분리한다.
- AI 서비스 예외가 ingest callback으로 전파되지 않게 한다.

---

## 10. 8단계 — 프론트엔드 표시

최소 변경으로 다음을 추가한다.

```text
frontend/src/types/ws.ts
frontend/src/types/index.ts
frontend/src/store/dashboardStore.ts
frontend/src/hooks/useWebSocket.ts
frontend/src/components/SensorCard.tsx
frontend/src/screens/ChartScreen.tsx
```

### 10.1 Sensor Card

표시 항목:

```text
AI 상태       정상 패턴 | 이상 후보 | 이상징후 | 데이터 부족
이상 점수     1.42 / 기준 0.85
주요 기여     CO2, 습도
모델          lstm-ae-v0.1.0
```

### 10.2 Chart

- 이상 점수와 threshold 표시
- 이상 구간 음영
- 가능하면 실제 센서값과 모델 복원값을 구분해 표시
- `AI 이상징후 · Research · 실제 안전 경보 아님` 문구 표시
- `LIVE`와 `SIM` source를 구분

### 10.3 접근성 및 의미 분리

- 색상만으로 상태를 전달하지 않는다.
- 기존 L1/L2/L3 색상과 다른 표현을 사용한다.
- AI 이상을 `위험`, `대피`, `누출 확정`으로 표현하지 않는다.
- 데이터가 없으면 `정상` 대신 `데이터 부족`으로 표시한다.
- AI 이상으로 toast, critical modal 또는 wearable vibration을 발생시키지 않는다.

---

## 11. 9단계 — UCI와 SKAB 외부 벤치마크

공개 데이터 파일이 제공되거나 다운로드가 허용된 경우에만 수행한다.

### SKAB

- LSTM Autoencoder 이상 탐지 파이프라인의 외부 검증에 사용
- SKAB 자체 anomaly/changepoint label 사용
- HP015 산업안전 임계값을 SKAB에 적용하지 않음

### UCI Gas Sensor Array Drift Dataset

- 센서 drift 대응 또는 batch 일반화 실험에 사용
- HP015 feature와 직접 병합하지 않음
- CO2/O2/CO/H2S 법정 기준 라벨을 적용하지 않음

외부 벤치마크 결과와 HP015 결과를 별도 표로 작성한다.

```text
External benchmark result
HP015 normal-data result
HP015 injected-anomaly result
```

---

## 12. 테스트 요구사항

최소 다음 테스트를 작성한다.

### 데이터/모델

- node별 시간 정렬
- 10초 리샘플링
- 중복 timestamp 처리
- 짧은 결측 보간
- 긴 결측 window 제외
- train-only scaler fit
- split 간 window leakage 방지
- simulation 데이터가 normal train에 포함되지 않음
- 동적 feature count 지원
- LSTM 입출력 shape 동일
- mask loss 동작
- anomaly injection 재현성
- threshold가 validation 데이터로만 결정됨
- feature contribution 합계 및 정렬

### 백엔드

- 모델 파일 누락 시 서버 기동 유지
- 데이터 부족 시 `insufficient_data`
- stale 데이터가 normal로 표시되지 않음
- feature mismatch 처리
- 3회 지속 조건
- AI 결과 저장 및 WebSocket payload
- AI 예외가 센서 ingest와 기존 alert에 영향 없음
- 기존 alert engine 회귀 테스트 통과

### 프론트엔드

- `ai_anomaly` 메시지 파싱
- node별 AI 상태 분리
- 데이터 부족 표시
- 기존 alert state와 AI state가 섞이지 않음

---

## 13. 성공 기준과 상태 코드

다음 조건을 만족하면 연구용 표시가 가능하다.

- 정상 데이터에서 false positive rate를 측정함
- 주입 이상 데이터에서 Precision/Recall/F1을 측정함
- baseline과 동일한 test 구간으로 비교함
- train/test leakage가 없음
- 실제 사용 feature와 모델 manifest가 일치함
- 데이터 부족과 모델 오류가 fail-safe로 표시됨
- 기존 안전 경보와 코드 및 UI 상태가 분리됨

최종 상태 중 하나를 반드시 선택한다.

```text
STATUS: READY_FOR_RESEARCH_DISPLAY
STATUS: MODEL_NOT_TRAINED_DATA_PENDING
STATUS: BLOCKED_DATA_INSUFFICIENT
STATUS: REJECTED_BASELINE_NOT_BEATEN
STATUS: REJECTED_DATA_LEAKAGE_RISK
STATUS: REJECTED_GENERALIZATION_FAILURE
```

`READY_FOR_RESEARCH_DISPLAY`는 현장 안전 사용 승인이 아니라 연구용 화면 표시 가능 상태를 의미한다.

---

## 14. 검증 명령

실제 환경을 확인해 존재하는 명령만 실행하고 결과를 보고한다.

```bash
git diff --check
backend/.venv/bin/python -m pytest backend/tests
backend/.venv/bin/python -m pytest experiments/lstm_anomaly/tests
```

프론트엔드를 변경한 경우:

```bash
cd frontend
npm run build
npm run lint
npm run test
```

ML 의존성이 아직 설치되지 않았다면 실패를 숨기지 말고 설치 방법과 미실행 테스트를 명시한다.

---

## 15. 작업 순서 요약

다음 순서를 바꾸지 마라.

1. 현재 DB와 센서 데이터 구조 조사
2. 정상 실측 데이터 품질 진단
3. 실제 유효 feature 확정
4. 10초 리샘플링과 10분 window 생성
5. 시간 기준 train/validation/test 분할
6. 단순 baseline 구현
7. LSTM Autoencoder 학습
8. validation 정상 오차로 threshold 설정
9. held-out test에 이상 데이터 주입
10. Precision/Recall/F1 및 오경보율 평가
11. artifact와 manifest 저장
12. 백엔드 실시간 탐지 서비스 연결
13. WebSocket과 대시보드 표시
14. 기존 경보와 분리 검증
15. SKAB/UCI 외부 벤치마크는 별도 수행
16. 최종 상태 코드와 한계 보고

---

## 16. 최종 보고 형식

최종 답변은 다음 순서로 작성해라.

1. 구현 결과 요약
2. 실제 사용한 node와 feature
3. 제외한 feature와 이유
4. 데이터 기간과 품질
5. 전처리 및 window 구성
6. train/validation/test 분할
7. baseline 결과
8. LSTM Autoencoder 구조
9. threshold 설정 방법
10. 이상 주입 평가 결과
11. 정상 구간 오경보율
12. 백엔드 연동 결과
13. 프론트엔드 표시 결과
14. 기존 안전 경보와 분리된 지점
15. 변경한 파일
16. 실행한 테스트와 결과
17. 최종 상태 코드
18. 남은 한계와 다음 단계

과장하지 말고 실측, 시뮬레이션, 주입 이상 및 외부 벤치마크 결과를 명확히 구분해라.
