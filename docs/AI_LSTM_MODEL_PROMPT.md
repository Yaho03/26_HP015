# HP015 LSTM 가스 농도 예측 모델 구현 요청

현재 `Yaho03/26_HP015` 프로젝트에 연구용 LSTM 가스 농도 예측 모델을 추가해줘.

이 작업은 MVP의 필수 기능이 아니라 `Research Track / MAY` 범위다. 따라서 모델이 검증되기 전에는 기존 안전 경보 엔진이나 정상/주의/경고/위험 판정을 절대로 변경하지 마라.

## 반드시 먼저 읽을 문서

- `docs/01_PRD.md`
- `docs/02_SYSTEM_ARCHITECTURE.md`
- `docs/04_DATA_CONTRACT.md`
- `docs/06_ALERT_RULES.md`
- `docs/07_EXPERIMENT_PLAN.md`
- `docs/08_SAFETY_AND_LIMITATIONS.md`
- `PRODUCT.md`
- `AGENTS.md`

특히 다음 문서 기준을 준수해라.

- `docs/06_ALERT_RULES.md` §8.3: 과거 60초 입력으로 5분 후 농도 예측
- `docs/01_PRD.md`: LSTM은 Research Track / MAY
- `docs/08_SAFETY_AND_LIMITATIONS.md`: 학습 데이터 부족, 센서 교정, 데이터 신뢰성 한계
- `frontend/src/utils/trend.ts`: 현재 구현은 LSTM이 아니라 선형 회귀/EWMA 추세 표시

## 핵심 안전 원칙

1. LSTM 예측값은 측정값이 아니다.
2. LSTM 예측값은 현재 안전 경보의 단독 근거로 사용하지 않는다.
3. 기존 임계값 경보, hysteresis, 지속 시간 조건, fail-safe 동작을 변경하지 않는다.
4. 예측 결과를 화면에 표시할 경우 반드시 `PREDICTED`, `예측값`, `Research` 등으로 명시한다.
5. 실제 센서 데이터가 충분하지 않으면 모델을 억지로 학습하지 말고 `데이터 부족` 상태로 종료한다.
6. 데이터가 부족한데 임의의 정상/위험 데이터를 만들어 학습하지 마라.
7. 실제 센서 측정값, 시뮬레이션 주입값, 예측값을 하나의 시계열로 혼합하지 마라.

## 작업 순서

### 1단계. 현재 구조와 데이터 흐름 조사

먼저 다음을 확인해라.

- TimescaleDB의 실제 센서 시계열 테이블과 컬럼
- `backend/app/repositories/sensor_data_repository.py`
- 센서 데이터 조회 API
- `frontend/src/services/api.ts`
- MQTT/WebSocket 데이터 구조
- 실제 측정값과 시뮬레이션 데이터의 구분 필드
- 현재 센서별 sampling interval과 결측 패턴
- 사용 가능한 Python 환경과 설치된 ML 라이브러리

조사 결과를 먼저 문서 또는 콘솔에 다음 형식으로 정리해라.

```text
대상 metric:
데이터 시작 시각:
데이터 종료 시각:
전체 샘플 수:
노드별 샘플 수:
관측된 sampling interval:
결측률:
simulation/live 비율:
현재 사용 가능한 ML framework:
```

### 2단계. 데이터 충분성 검사

LSTM 학습 전에 데이터 준비 상태를 검사해라.

검사 항목:

**가장 먼저 확인할 것 — 대상 metric에 값이 존재하는가.**

`co2_ppm`이 결측이면 나머지 검사는 의미가 없다. 관측 기간이 아무리 길어도
예측할 대상이 없다. 다음 두 가지를 먼저 본다.

- `data.co2_ppm`의 non-null 비율
- `quality.sensors.mhz19b`가 `valid`인 비율 (`error` / `warming_up`은 값이 없다는 뜻)

> **2026-08-24 실측 데이터 확인 결과 (레포 루트 `mqtt_4nodes_test1.txt` / `test2.txt`)**
>
> ```text
> gas 메시지        27,191건
> co2_ppm           27,191건 전부 null  (유효값 0건)
> mhz19b 상태       error 26,942 / warming_up 249  → valid 0건
> mq7/mq136/mq2     전부 uncalibrated
> 노드별 관측       6,092 ~ 7,409건 (1초 샘플 기준 약 101~123분)
> ```
>
> **MH-Z19B를 복구하기 전까지 이 작업은 시작할 수 없다.** 학습 데이터가
> 부족한 것이 아니라 존재하지 않는다. 복구 절차는
> `docs/HW_SESSION_HANDOFF_20260819.md` §12.3(sensor-01 기준점 틀어짐),
> §12.4(sensor-03·04 무응답 전수 조사)를 따른다.

- 최소 관측 기간 확인
- 노드별 샘플 수 확인
- 시간순 정렬 여부 확인
- 중복 timestamp 확인
- 결측 timestamp 확인
- 비정상 범위와 센서 오류값 확인
- live와 simulation 데이터 분리 가능 여부 확인
- 동일한 사고/주입 시나리오가 train과 test에 동시에 들어가는지 확인

권장 기준:

- 기본 대상: `co2_ppm`
- 입력 구간: 과거 60초
- 예측 구간: 현재 시점 이후 5분
- 최소 학습 가능한 연속 구간과 샘플 수는 실제 sampling interval을 기준으로 계산
- 1초 샘플이라고 가정하지 말고 실제 데이터에서 `dt`를 추정

### 2.1 상승 구간이 학습 데이터에 있는가

정상 구간만 학습한 예측기는 **"계속 평온할 것"만 예측한다.** 가스 급상승을 한 번도
본 적이 없기 때문이다. 그런 모델은 평상시에 잘 맞고 정작 필요한 순간에 아무것도
알려주지 못한다 — 이 기능의 존재 이유가 사라진다.

학습 데이터에 CO₂ 상승 구간이 포함되는지 확인하고, 없다면 그 한계를 보고에 명시해라.

> CO₂는 사람 호흡으로 실제 상승 데이터를 **안전하게** 만들 수 있다 (밀폐 공간 재실 실험).
> 유해가스 주입 없이 실제 상승을 확보할 수 있는 유일한 경우다.
> 단 `HW_SESSION_HANDOFF_20260819.md` §10 안전 수칙을 지킨다 — 2,000ppm 도달 시 즉시
> 중단·환기, 1,000ppm 도달 후 최대 15분, 최소 3인. **센서에 직접 숨을 불지 않는다**
> (§12.3에서 그렇게 NDIR 기준점을 망가뜨렸다).

데이터가 부족한 경우 다음처럼 중단해라.

```text
STATUS: BLOCKED_DATA_INSUFFICIENT
REASON: 학습 가능한 연속 시계열이 부족함
ACTION: 모델 학습을 수행하지 않음
```

### 3단계. 데이터 정제와 리샘플링

전처리 규칙을 코드로 고정하고 기록해라.

- 시간순 정렬
- 중복 timestamp 처리
- 실제 sampling interval을 기준으로 일정 간격 리샘플링
- 짧은 결측 구간만 제한적으로 보간
- 긴 결측 구간은 시퀀스에서 제외
- 센서 오류값과 명백한 범위 밖 값 처리
- 보간된 값과 실제 측정값을 구분할 수 있도록 metadata 유지
- scaling은 train split에만 fit
- validation/test에는 train에서 fit한 scaler만 적용

CO₂의 물리적 범위와 이상치 기준을 임의로 만들지 말고 기존 문서와 백엔드 threshold 설정을 확인해라.

### 4단계. 시간 기준 데이터 분할

시계열이므로 random shuffle split을 사용하지 마라.

기본 분할 순서:

```text
과거 구간 → train
그 다음 시간 구간 → validation
가장 최근 시간 구간 → test
```

권장 비율은 다음과 같지만 실제 데이터 양에 따라 조정하고 이유를 기록해라.

- train: 70%
- validation: 15%
- test: 15%

다음 데이터 누수를 금지한다.

- 같은 timestamp가 여러 split에 존재하는 경우
- 같은 sliding window가 split 경계를 걸쳐 중복되는 경우
- 동일한 시뮬레이션 시나리오가 train/test에 섞이는 경우
- test 데이터를 사용해 scaler, threshold, hyperparameter를 결정하는 경우

### 5단계. 베이스라인 구현

LSTM을 만들기 전에 반드시 다음 베이스라인을 구현해라.

1. Persistence baseline
   - 마지막 측정값이 미래에도 유지된다고 가정
2. 이동 평균 또는 EWMA baseline
3. 현재 코드의 선형 추세 외삽 결과

LSTM이 베이스라인보다 개선되지 않으면 모델을 운영 화면에 연결하지 마라.

베이스라인과 LSTM은 동일한 test 구간과 동일한 평가 지표로 비교해야 한다.

### 6단계. LSTM 모델 구현

최초 모델은 작고 재현 가능한 구조로 시작해라.

예시:

```text
Input: [batch, sequence_length, feature_count]
LSTM: 1~2 layers
Hidden size: 작은 값부터 시작
Dropout: validation 기준으로 결정
Output: horizon별 예측값 (60/120/180/240/300초)
Loss: MAE 또는 Huber loss 우선 검토
```

다음은 임의로 추가하지 마라.

- 복잡한 Transformer
- 다중 모델 앙상블
- GPU 의존 구조
- 과도한 hyperparameter search
- 데이터보다 큰 모델

### 6.1 출력 형태는 Direct multi-horizon으로 고정한다

**Single horizon(5분 후 한 점)을 선택하지 마라.** 프론트가 이 값으로 예측 곡선을
점선 스파크라인으로 그린다. 한 점만 주면 직선밖에 못 그리고 곡선의 형태 정보가
사라진다 — "완만히 오르는 중"과 "급격히 꺾이는 중"이 화면에서 같아 보인다.

기본 horizon: `60 / 120 / 180 / 240 / 300`초 (5점).
실제 sampling interval에 따라 간격을 조정할 수 있으나 **최소 3점 이상**을 낸다.

### 6.2 불확실성 구간(lower/upper)은 필수다

점추정만 내면 화면이 "4분 뒤 위험"이라고 단정하게 된다. 한 번 빗나가면 작업자가
이후 모든 예측을 무시하기 시작한다. **안전 시스템에서 가장 흔한 실패 모드다.**

9단계 중단 기준에 이미 "예측 불확실성을 설명할 수 없음"이 있다.
**구간을 산출할 수 없으면 화면에 연결하지 마라.**

산출 방법은 선택하되 근거를 기록해라.

- quantile loss (pinball) — 분위수를 직접 학습
- MC dropout — 추론 시 dropout을 켜고 표본 분산
- residual 분위수 — validation 잔차 분포에서 horizon별 분위수

> horizon이 멀수록 구간이 넓어지는 것이 정상이다. 300초 구간이 60초 구간과
> 비슷한 폭이면 불확실성을 제대로 추정하지 못한 것이다.

### 7단계. 학습 재현성과 산출물 관리

다음을 반드시 저장해라.

- random seed
- dataset snapshot 또는 query 조건
- 대상 node 목록
- 대상 metric
- sampling interval
- sequence length
- forecast horizon
- scaler
- model architecture
- hyperparameters
- train/validation/test 기간
- 학습 로그
- 최종 test metrics
- Git commit 또는 작업 시점

권장 구조:

```text
experiments/lstm/
├── README.md
├── configs/
├── data/              # 원본 대용량 데이터는 커밋하지 않음
├── notebooks/         # 선택 사항
├── src/
├── tests/
└── artifacts/         # 모델 파일과 scaler, metrics
```

대용량 센서 데이터와 모델 파일을 Git에 무단으로 추가하지 마라. 저장소 규칙과 `.gitignore`를 먼저 확인해라.

### 8단계. 평가

최소한 다음 지표를 측정해라.

- MAE
- RMSE
- MAPE는 CO₂ 값이 0에 가까울 때 왜곡되므로 사용 여부를 검토하고 이유를 기록
- persistence/EWMA/선형 추세 대비 개선율

안전 관련 참고 평가:

- 예측값이 임계값에 도달할 것으로 표시한 횟수
- 실제 test 구간에서 임계값 도달 여부
- false positive / false negative
- threshold crossing lead time
- 결측과 노이즈 상황에서의 성능

단, 이 평가는 연구용 참고 지표이며 LSTM 결과로 실제 경보를 발령하지 마라.

### 9단계. 결과 해석과 중단 기준

다음 중 하나라도 해당하면 운영 화면이나 경보 엔진에 연결하지 마라.

- LSTM이 persistence baseline보다 좋지 않음
- validation 성능은 좋은데 test 성능이 급격히 나빠짐
- 특정 노드 또는 시나리오에만 과적합
- train/test leakage 가능성이 해소되지 않음
- 학습 데이터가 simulation에만 편중됨
- 실제 센서 교정 상태가 불명확함
- 예측 불확실성을 설명할 수 없음
- 데이터량이 통계적으로 부족함

결과 보고에는 반드시 다음 상태 중 하나를 명시해라.

```text
STATUS: READY_FOR_RESEARCH_DISPLAY
STATUS: BLOCKED_DATA_INSUFFICIENT
STATUS: REJECTED_BASELINE_NOT_BEATEN
STATUS: REJECTED_DATA_LEAKAGE_RISK
STATUS: REJECTED_GENERALIZATION_FAILURE
```

### 10단계. 애플리케이션 연동은 마지막에만 수행

모델 평가가 끝나고 `READY_FOR_RESEARCH_DISPLAY`인 경우에만 연동을 제안해라.

연동 시 원칙:

- 기존 경보 엔진과 분리
- 별도 연구용 endpoint 또는 서비스로 구성
- 예측값과 실측값을 서로 다른 필드로 유지
- 응답 필드는 10.1 계약을 그대로 따른다 (임의 추가·생략 금지)
- 화면에 `예측값`과 `실측값`을 명확히 구분
- LSTM 오류나 timeout이 기존 센서 경보를 막지 않도록 격리
- 예측 실패 시 정상으로 표시하지 않고 `예측 불가`로 표시

### 10.1 응답 계약 (확정)

프론트엔드 메인 화면(Screen 1) 연동을 위해 확정된 계약이다. **임의로 바꾸지 마라.**

```json
{
  "type": "ai_forecast",
  "node_id": "sensor-01",
  "metric": "co2_ppm",
  "observed_at": "2026-08-24T12:00:00Z",
  "input_window_seconds": 60,
  "forecast_horizon_seconds": 300,
  "last_observed_value": 1230.0,
  "predictions": [
    { "offset_s": 60,  "value": 1310.2, "lower": 1250.0, "upper": 1372.5 },
    { "offset_s": 120, "value": 1402.8, "lower": 1300.1, "upper": 1510.4 },
    { "offset_s": 180, "value": 1495.0, "lower": 1340.7, "upper": 1662.3 },
    { "offset_s": 240, "value": 1588.1, "lower": 1372.4, "upper": 1820.9 },
    { "offset_s": 300, "value": 1680.4, "lower": 1400.2, "upper": 1975.6 }
  ],
  "model_version": "lstm-co2-v0.1.0",
  "trained_until": "2026-08-24T02:30:00Z",
  "update_interval_s": 10,
  "is_research_only": true,
  "prediction_status": "available",
  "unavailable_reason": null
}
```

| 필드 | 이유 |
|---|---|
| `predictions[]` | 예측 곡선. 6.1 참조 — 한 점이면 직선밖에 못 그린다 |
| `lower` / `upper` | 불확실성 구간. 6.2 참조 — **없으면 화면에 연결하지 않는다** |
| `trained_until` | 모델이 낡으면 화면에 표시해야 한다. 학습 데이터의 마지막 시각 |
| `update_interval_s` | 프론트가 리렌더 주기와 애니메이션을 설계하는 데 필요하다 |

**`prediction_status`가 `"unavailable"`이면** `predictions`를 **빈 배열**로 주고
`unavailable_reason`을 채운다: `insufficient_data` / `model_not_ready` /
`stale_input` / `feature_mismatch`.

프론트는 이 상태를 **"정상"이 아니라 "예측 불가"로 그린다.** 예측하지 못한 것을
"평온함"으로 표시하면 미검출보다 위험하다.

### 10.2 전달 경로는 WebSocket이다

`frontend/src/types/ws.ts`의 `AiAnomalyMessage`와 **같은 패턴으로 별도 메시지 타입**을
만든다. 기존 `AiAnomalyMessage`에 필드를 얹지 마라 — 이상탐지와 예측은 다른 판정이고,
한 타입에 섞으면 한쪽 처리 코드가 다른 쪽 메시지도 다루게 된다.

**`SnapshotMessage`에도 반드시 포함해라.** 이슈 #209와 같은 이유로, snapshot이 없으면
재연결/새로고침 후 예측이 영영 복원되지 않는다. `worker_exposures`,
`evacuation_routes`가 이미 같은 처리를 받고 있으므로 그 구현을 따른다.

### 10.3 백엔드가 하지 말아야 할 계산

**임계값 도달 시각(ETA)을 백엔드에서 계산하지 마라.**
프론트가 `GET /api/thresholds`로 받은 서버 임계값과 `utils/alerts.ts`로 직접 계산한다.
백엔드가 또 계산하면 임계값 정본이 둘로 갈라지고, PRD FR-204 MUST(임계값 하드코딩 금지)가
무너진다.

**예측 등급(`AlertLevel`)을 응답에 넣지 마라.** 값만 준다.
`frontend/src/types/index.ts`의 규칙을 그대로 따른다:

> 두 타입을 서로 변환하는 함수를 만들지 않는다 — 만들면 언젠가 누가 호출하고,
> 그 순간 연구용 참고 지표가 산업안전 경보 등급으로 둔갑한다.

### 10.4 프론트엔드 파일을 건드리지 마라

프론트는 LSTM 결과를 기다리지 않는다. `source: "lstm" | "trend"` 인터페이스로 먼저
구현하고, 지금은 전 지표를 `utils/trend.ts` 선형 외삽으로 채운다. LSTM이
`READY_FOR_RESEARCH_DISPLAY`를 내면 `co2_ppm` 카드만 `"lstm"`으로 바뀐다.
프론트 재작업은 없다.

**이 작업 세션은 위 계약만 지키면 되고 `frontend/` 아래 파일은 수정하지 않는다.**

## 기술 스택 규칙

- 현재 레포의 Python 환경과 문서를 먼저 확인해라.
- 이미 설치된 라이브러리를 우선 사용해라.
- PyTorch, TensorFlow, Keras 등 새로운 ML 프레임워크가 필요하면 설치 전에 사용자 허락을 받아라.
- 프론트엔드에 새 라이브러리를 추가하지 마라.
- 기존 React/Vite/Zustand/Three.js 구조와 안전 경보 로직을 변경하지 마라.
- 새 의존성 없이 가능한 분석/검증 코드는 먼저 표준 Python, NumPy, Pandas 등 현재 환경을 확인해 구현해라.

## 테스트 요구사항

다음 테스트를 작성하거나 추가해라.

- 시계열 정렬 테스트
- 중복 timestamp 처리 테스트
- 결측 구간 처리 테스트
- train-only scaler fit 테스트
- 시간 기준 split 테스트
- split 간 window leakage 테스트
- baseline 계산 테스트
- 입력 sequence shape 테스트
- 모델 출력 horizon shape 테스트
- 예측 실패 시 `prediction_status`가 정상으로 변하지 않는 테스트
- 기존 alert engine이 LSTM 도입 후에도 변하지 않는 회귀 테스트

## 최종 검증

가능한 범위에서 다음 명령을 실행해라.

```bash
git diff --check
backend/.venv/bin/python -m pytest backend/tests
```

LSTM 전용 테스트 또는 실험 코드가 추가되면 해당 명령도 실행해라.

```bash
backend/.venv/bin/python -m pytest experiments/lstm/tests
```

프론트엔드나 API를 변경한 경우에만 다음도 실행해라.

```bash
cd frontend
npm run build
npm run lint
npm run test
```

## 최종 보고 형식

최종 보고는 다음 순서로 작성해라.

1. 현재 데이터 준비 상태
2. 대상 metric과 node
3. 실제 sampling interval과 입력/예측 구간
4. 전처리 및 결측 처리 방법
5. 시간 기준 train/validation/test 분할 결과
6. baseline 결과
7. LSTM 구조와 학습 설정
8. test 성능 및 baseline 대비 비교
9. 데이터 누수와 과적합 점검 결과
10. 최종 상태 코드
11. 변경한 파일
12. 실행한 테스트와 결과
13. 안전 경보와 분리된 지점
14. 아직 운영 연동을 하지 않은 이유 또는 다음 단계
