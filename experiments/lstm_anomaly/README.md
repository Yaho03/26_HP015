# LSTM Autoencoder 기반 이상징후 탐지 (연구용)

> **이 모델은 안전 경보가 아니다.**
> 위험가스 종류를 판정하지 않고, 법정 기준 초과를 예측하지 않으며,
> 기존 임계값 경보(`06_ALERT_RULES.md`)를 대체하거나 보조하지 않는다.
> 화면 표기는 항상 `AI 이상징후 · Research · 실제 안전 경보 아님` 이다.

정상 상태의 복합 센서 시계열만 학습한 LSTM Autoencoder 로 "평소와 다른 움직임" 을
탐지한다. 판정 근거는 입력 시계열과 모델 복원값의 차이(anomaly score) 하나뿐이다.

---

## 1. 왜 이렇게 설계했는가

### 정상만 학습하는 비지도 방식

이상 라벨이 있는 실측 데이터가 없다. 실제 유해가스를 쓸 수 없으므로
(`08_SAFETY_AND_LIMITATIONS.md` §6.1) 앞으로도 생기지 않는다. 정상만 학습하고
"정상으로 복원되지 않는 것" 을 이상으로 보는 방식이 이 제약에서 유일하게 정직하다.

### 값과 관측 마스크를 항상 함께 들고 다닌다

결측을 보간해 채우면 그 값이 실측인지 우리가 만든 직선인지 구분할 수 없다.
마스크 없이 학습하면 모델은 결측이 많은 채널에서 "보간 알고리즘" 을 배우고,
극단적으로는 **센서가 꺼진 상태를 가장 정상적인 상태로** 학습한다.
그래서 loss·점수·threshold 전 구간에서 관측된 지점만 센다.

### 판단할 수 없으면 '정상' 이 아니라 '판단 불가'

`insufficient_data`, `stale_data`, `feature_mismatch`, `model_not_ready` 는
`normal_pattern` 으로 변환되지 않는다. 밀폐공간에서 센서가 죽었는데 화면이
"정상" 으로 남는 것은 미검출보다 위험하다 — 2026-08-19 하드웨어 세션에서
실제로 겪은 일이다 (`HW_SESSION_HANDOFF_20260819.md` §12.6-A).

---

## 2. 실행

### 설치

ML 의존성은 백엔드와 분리한다. 백엔드 컨테이너는 MQTT 수신과 경보 판정을 하는
안전 필수 경로이고 학습 프레임워크를 한 번도 쓰지 않는다.

```bash
python3.12 -m venv experiments/lstm_anomaly/.venv
experiments/lstm_anomaly/.venv/bin/pip install -r experiments/lstm_anomaly/requirements-dev.txt
```

### 데이터 진단만 (§3)

학습 전에 반드시 먼저 본다. 어떤 채널이 살아 있고 무엇을 왜 뺐는지가 여기서 정해진다.

```bash
cd experiments/lstm_anomaly
.venv/bin/python -m src.diagnose --source ~/Downloads/mqtt_4nodes_test1.txt
```

### 학습 + 평가 + artifact

```bash
cd experiments/lstm_anomaly
.venv/bin/python -m src.train \
  --source ~/Downloads/mqtt_4nodes_test1.txt \
  --source ~/Downloads/mqtt_4nodes_test2.txt \
  --out artifacts/run-20260824
```

### 테스트

```bash
cd experiments/lstm_anomaly
.venv/bin/python -m pytest tests -q
```

---

## 3. 입력 형식

세 가지를 받아 모두 `(time, node_id, metric, value, source_mode)` 로 정규화한다.

| 형식 | 설명 |
|---|---|
| MQTT tap `.txt` | `<topic> <json>` 한 줄씩. UTF-16 로 떨어지는 경우가 많아 자동 판별한다. envelope 이 온전해 `source_mode` 를 볼 수 있는 유일한 형식 |
| CSV / CSV.gz | `sensor_data` 덤프. `source_mode` 컬럼이 없으면 **전체를 제외한다** |
| TimescaleDB | 가동 중인 DB 직접 조회 |

### 실측만 학습한다

`source_mode == 'live'` 인 행만 남긴다. `04_DATA_CONTRACT.md` §3.5 에 따라 시뮬레이션
주입도 실제 `node_id` 를 그대로 쓰므로 node_id 로는 구분할 수 없다. 이 필드가 유일한
판별자다. `NULL`/누락은 `live` 로 승격하지 않는다.

> DB 에 이 컬럼이 생긴 것은 마이그레이션 `012_sensor_data_source_mode.sql` 부터다.
> 그 이전에 쌓인 행은 출처를 소급할 수 없어 `NULL` 로 남아 있고, 따라서 학습에
> 쓰이지 않는다. 지금 DB 의 기존 18만 행이 전부 여기 해당한다.

---

## 4. Feature 선정은 설정이 아니라 진단이 한다

`configs/default.yaml` 의 `features.use` 는 기본이 빈 목록이다.
`data_quality.diagnose()` 가 판정한 목록을 그대로 쓴다. 손으로 적은 목록을 우선하면
센서가 죽어도 계속 그 채널을 학습하게 된다.

### 배제 규칙

| 규칙 | 근거 |
|---|---|
| 전 노드 100% null → 행 자체가 없음 | 로더가 `null` 로 행을 만들지 않는다. `0.0` 으로 채우면 "이 지표는 늘 0" 을 정상으로 학습한다 |
| 일부 노드에만 존재 | 4노드 공통 채널이 아니면 노드 일반화 평가를 할 수 없다 |
| 한 노드에서 최장 동일값이 표본의 20% 초과 | stuck-at 센서 사망. **절대 샘플 수가 아니라 비율**로 본다 — 1초 주기에서 4분 정체는 일시적 정체지만 전 구간 고정은 사망이다 |
| 변동계수 < 0.1% | 사실상 상수라 복원 오차에 기여하지 못한다 |
| 다른 채택 채널과 `max(|Pearson|, |Spearman|) ≥ 0.999` | 결정론적 변환 관계. Spearman 을 함께 보는 이유는 `Rs = RL·(Vcc−V)/V` 가 **비선형** 단조 변환이라 Pearson 만으로는 안 잡히기 때문 |
| `iaq_index` 는 `iaq_accuracy ≥ 2` 일 때만 | `08_SAFETY_AND_LIMITATIONS.md` §2.1. 통계로 판별할 수 없는 도메인 규칙 |

짧은 고정 구간은 feature 를 버리지 않고 전처리에서 **관측되지 않은 것으로 마스킹**하며,
제외한 규칙과 개수를 `metrics.json` 의 `exclusions` 에 남긴다 (§3 "임의로 삭제하지 말고
제외 규칙과 개수를 기록").

---

## 5. 전처리

- **10초 리샘플링.** 연속량은 버킷 평균, 상태/플래그성 값(`iaq_accuracy` 등)은 마지막 값.
  상태값을 평균하면 `0` 과 `2` 의 평균 `1` 처럼 **존재하지 않는 센서 상태**가 만들어진다.
- **보간 한도 20초.** 그보다 긴 공백은 채우지 않는다. 30초를 선형 보간으로 이으면
  모델은 그 구간에서 완벽히 매끄러운 직선을 보고 그것을 정상으로 배운다.
- **30초 이상 연속 단절을 품은 window 는 제외.** 한 스텝(10초) 결측은 정상 범위다.
  그것까지 버리면 남는 데이터가 없다.
- **관측 비율 70% 미만 window 는 제외.** 대부분이 보간값인 window 로 학습하면
  모델이 보간 알고리즘을 배운다.
- **scaler 는 train 에서만 fit.** 그리고 **관측된 값만으로** 통계를 낸다 —
  0 으로 채운 결측이 평균·표준편차에 섞이면 스케일 자체가 결측 패턴을 반영하고,
  같은 scaler 를 쓰는 추론 시점에서 분포가 어긋난다.

---

## 6. Window 와 분할

```
X.shape = [window_count, 60, feature_count]      # 10초 × 60 = 10분
```

두 가지를 절대 하지 않는다.

1. **window 가 노드 경계를 넘지 않는다.** 서로 다른 위치의 센서를 이어 붙인 10분은
   어떤 물리 현상도 아니다.
2. **window 가 split 경계를 넘지 않는다.** window 는 stride 1 로 겹쳐 만들어지므로,
   경계에서 자르기만 하면 train 의 마지막 window 와 validation 의 첫 window 가 최대
   59스텝을 공유한다. 그 공유분이 곧 leakage 다.

시간 기준 70/15/15 분할 + 경계마다 **한 window 길이(600초) purge gap**.
random shuffle 은 쓰지 않는다. 구간이 짧아 purge 를 넣지 못하면 조용히 넘어가지 않고
`STATUS: REJECTED_DATA_LEAKAGE_RISK` 로 끝낸다.

---

## 7. 모델

```
Input           [B, 60, F]
Encoder LSTM    hidden 32
Latent          16
Decoder LSTM    hidden 32   ← latent 를 60스텝으로 펼쳐서만 입력
Output Linear   F
Loss            masked MAE
```

디코더가 입력 시퀀스를 직접 보지 못하게 하는 것이 핵심이다. 보게 하면 autoencoder 가
아니라 항등 함수를 배우고, 복원 오차가 이상 여부와 무관해진다.

`num_layers=1` 에 dropout 을 걸지 않는다 (§5). PyTorch 도 그 조합에는 경고만 내고
아무 일도 하지 않는다.

---

## 8. 점수와 기준값

```
feature_error[f] = 최근 60초 가중 평균(|x[f] - x̂[f]|)   # 관측 지점만
anomaly_score    = mean(feature_error)                   # NaN 채널 제외
```

10분 전체를 균등 평균하지 않는다. 방금 시작된 이상은 9분간의 정상에 희석돼
threshold 를 못 넘고, 실시간 탐지에서 그 지연은 그대로 탐지 실패다.
최근 60초(6스텝)에 가중치 0.7 을 몰아준다 (§6.1).

**채널이 window 내내 미관측이면 오차는 `NaN` 이지 `0` 이 아니다.** `0` 은 "완벽하게
정상" 이라는 뜻이라, 꺼진 센서가 가장 정상적인 센서가 되어버린다.

`threshold = validation 정상 score 의 99분위수`. **test 를 쓰지 않는다.**
test 로 threshold 를 고르면 그 test 성능은 일반화 추정치가 아니라 fitting 결과다.

실시간 판정은 3회 연속 초과 시 `anomaly`, 3회 연속 하회 시 `normal_pattern` 복귀.
점수가 `NaN` 인 동안에는 카운터를 **증가시키지도 초기화하지도 않는다** — 데이터 없는
구간을 '정상 지속' 으로 세면 이상이 진행 중인데 상태가 복구되고, '이상 지속' 으로
세면 센서가 꺼진 것만으로 경보가 뜬다.

---

## 9. 평가

이상 데이터는 **held-out test 의 복사본에만** 주입한다. 주입기는 입력 배열을 제자리에서
고치지 않고 항상 새 배열을 반환한다 — test 원본이 오염되면 정상 구간 오경보율을
잴 기준 자체가 사라진다.

주입 유형 7종: `spike`, `drift`, `stuck_at`, `dropout`, `noise_burst`,
`multi_feature`, `cross_feature_break`. seed 로 재현 가능하고 유형·구간·대상 채널·크기를
전부 기록한다.

주입은 정규화 **이전**의 원 단위(Ω, °C, %)에서 한다. 정규화 뒤에 넣으면 magnitude 의
물리적 의미가 사라져 "몇 시그마" 라는 말밖에 못 하게 된다.

### baseline 비교 (§7.2)

LSTM 을 단독으로 내놓지 않는다. 세 baseline 모두 LSTM 과 **같은 인터페이스·같은 test
구간·같은 threshold 규칙**으로 잰다.

| baseline | 무엇을 보는가 | 한계 |
|---|---|---|
| z-score | 채널별 몇 시그마 | 채널 사이 관계를 모름 → `cross_feature_break` 원리상 불가 |
| rolling mean/std | window 내 국소 예측 잔차 | 과거만 본다(미래 누출 없음). 관계는 여전히 모름 |
| PCA 복원 오차 | LSTM 과 같은 발상, **시간 구조 없이** | 두 결과의 차이가 곧 "시간을 모델링해서 실제로 얻은 것" |

**PCA 를 못 이기면 LSTM 을 쓸 이유가 없다.** 그 경우
`STATUS: REJECTED_BASELINE_NOT_BEATEN` 을 남기고 끝낸다.

측정 지표: Precision / Recall / F1 / **정상 구간 오경보율** / 유형별 recall /
평균 탐지 지연 / 노드별 성능. 오경보율이 가장 중요하다 — recall 이 아무리 높아도
정상에서 계속 울리면 사람이 화면을 끈다.

평가 단위는 **window** 다. 주입 라벨이 window 단위로 붙고 실시간 서비스도 10초마다
window 하나를 판정하므로, point 단위로 재면 평가와 운용의 단위가 어긋나 수치를
옮겨 쓸 수 없다.

---

## 10. Artifact

```
artifacts/<run>/
├── model.pt                    학습된 가중치
├── scaler.json                 feature 순서 + mean/std
├── threshold.json              threshold, 분위수, validation 분포 통계
├── feature_manifest.json       실제 사용 feature와 순서 (추론 시 대조하는 단일 정본)
├── metrics.json                LSTM/baseline 전 지표 + 제외 기록
├── training_manifest.json      재현에 필요한 전부 (git commit, seed, 구간, 하이퍼파라미터)
└── data_quality_report.txt     §3 형식 진단 리포트
```

`feature_manifest.json` 이 단일 정본이다. 추론 시 입력 feature 이름과 **순서**를
이것과 대조해 다르면 `feature_mismatch` 를 낸다. feature 수를 코드에 박지 않는
이유가 이것이다 (§2.2).

`artifacts/` 는 `.gitignore` 대상이다. 모델 가중치와 원본 데이터를 저장소에 넣지 않는다.

---

## 11. 최종 상태 코드

| 코드 | 의미 |
|---|---|
| `READY_FOR_RESEARCH_DISPLAY` | **연구용 화면 표시** 가능. 현장 안전 사용 승인이 아니다 |
| `MODEL_NOT_TRAINED_DATA_PENDING` | 데이터 부족. 코드는 서 있고 성능 수치를 만들지 않았다 |
| `BLOCKED_DATA_INSUFFICIENT` | 유효 feature 2개 미만 등 학습 조건 미충족 |
| `REJECTED_BASELINE_NOT_BEATEN` | 단순 baseline 을 못 이겼다 |
| `REJECTED_DATA_LEAKAGE_RISK` | purge gap 미적용 등 leakage 위험 |
| `REJECTED_GENERALIZATION_FAILURE` | 노드별 성능 편차가 크다 |

---

## 12. 2026-08-24 실측 결과 — `BLOCKED_DATA_INSUFFICIENT`

4노드 · 2시간 15분 · 353,808행 (전부 `source_mode: live`) 로 실행한 결과다.

```
STATUS: BLOCKED_DATA_INSUFFICIENT
```

### 왜 멈췄는가

관측 기간 동안 **정상값의 기준선 자체가 흘렀다.** 추세 크기를 10분 window 내부
변동으로 나눈 값:

| feature | 드리프트 비율 |
|---|---:|
| `mq7_rs_ohm` | **25.8×** |
| `temperature_c` | 19.5× |
| `mq136_rs_ohm` | 16.8× |
| `mq2_rs_ohm` | 15.6× |
| `humidity_pct` | 14.6× |

노드 단위로 보면 `sensor-04 mq7_rs_ohm` 은 2.4시간 동안 +40.4% 이동했고 이는
window 내부 변동의 **43.6배**다. LSTM autoencoder 는 정상 패턴이 **반복되는 것**을
전제하는데, 기준선이 단조롭게 흐르면 반복할 패턴이 없다.

MQ 계열은 예열에만 수 시간, BME680 은 24시간 안정화가 필요하다
(`08_SAFETY_AND_LIMITATIONS.md` §5.1). 이 기록은 통째로 **워밍업 과도구간**일
가능성이 크고, §0.6 은 워밍업 값을 정상 패턴으로 학습하지 말라고 규정한다.

### 실제로 관찰된 증상

여기까지 오는 데 두 번의 오진을 거쳤다. 기록해 둔다.

1. **1차 (global scaler)** — LSTM F1 0.038, z-score F1 0.247. 모든 방법이 4~8σ spike 조차
   못 잡았다. 원인은 모델이 아니라 스케일링이었다. 노드 간 baseline 차이가 노드 내
   변동을 최대 8배 압도해(`mq136_rs_ohm` 노드 평균 5,083 ~ 40,470), global 표준화가
   각 노드의 정상 변동을 **0.05σ** 로 눌러버렸다. → 노드별 scaler 로 수정.

2. **2차 (노드별 scaler)** — LSTM F1 0.311. 개선됐지만 두 가지가 이상했다.
   - `train_loss 0.30` vs `val_loss 1.55` — 5배 격차. 시간순 분할이므로 val 구간의
     분포가 train 과 다르다는 뜻.
   - LSTM 과 z-score 의 혼동행렬이 **완전히 동일**(tp 26 / fp 43 / fn 72 / tn 186).
     autoencoder 가 노드 평균을 그대로 출력하도록 붕괴해 `|x−x̂| ≈ |x−mean|`,
     즉 z-score 와 같은 함수가 된 것이다.

   두 증상 모두 같은 원인을 가리켰고, 드리프트를 재보니 20~44배였다.

**이 상태에서도 숫자는 나온다.** 그러나 그 숫자가 재는 것은 탐지 성능이 아니라
"기준선이 얼마나 흘렀는가" 다. 표에 적히는 순간 아무도 그 차이를 알 수 없게 되므로
(§0.10) 성능 수치를 만들지 않고 멈춘다.

### 필요한 것

모델 조정이 아니라 **센서 안정화 후의 더 긴 관측**이다.

- MQ 3종 예열 완료 후(수 시간) 재수집
- 최소 24시간 — 드리프트가 정상 변동 대비 작아질 만큼
- 가능하면 MH-Z19B 복구 후 (CO₂ 는 안정적이고 물리적 해석이 명확한 채널이다)

### 파이프라인 자체는 동작한다

"무엇을 넣어도 거절하는 코드" 를 만든 것이 아님을 합성 데이터로 확인했다
(`tests/test_pipeline_e2e.py`). 정상 패턴이 반복되는 3시간 4노드 합성 데이터에서:

| 방법 | Precision | Recall | F1 | 오경보율 |
|---|---:|---:|---:|---:|
| LSTM AE | 0.954 | 0.632 | 0.760 | 0.013 |
| z-score | 0.861 | 0.227 | 0.359 | 0.016 |
| rolling | 0.918 | 0.344 | 0.500 | 0.013 |
| **PCA** | **1.000** | **0.841** | **0.913** | **0.000** |

`STATUS: REJECTED_BASELINE_NOT_BEATEN` — LSTM 이 PCA 를 못 이겼다. 이것도 그대로
보고한다. 다만 이 합성 데이터는 정상 패턴이 순수 정현파라 저차원 선형 구조에
가깝고, PCA 에 유리한 조건이다. 실측 데이터에서의 우열은 별개 문제이며 아직
답할 수 없다.

유형별 recall 을 보면 LSTM 은 `cross_feature_break`·`drift`·`multi_feature` 를
100% 잡고 `spike`(0.17)·`dropout`(0.04)에 약하다. 최근 60초 가중 방식이 지속성
있는 이상에 유리하고 순간 이벤트에 불리하다는 뜻으로, 설계 의도와 일치한다.

---

## 13. 알려진 한계

- **CO₂ 가 없다.** MH-Z19B 가 4노드 전부 `error` 라 `co2_ppm` 이 100% null 이다.
  프롬프트가 1순위로 제시한 feature 를 쓸 수 없다.
  (`HW_SESSION_HANDOFF_20260819.md` §12.3, §12.4)
- **MQ 는 ppm 이 아니라 원시 저항이다.** R0 미기입(`MQ*_R0_OHM=0.0`)으로
  `rs_r0_ratio` 가 100% null 이라 `*_rs_ohm` 을 쓴다. 이 값은 가스 농도가 아니고
  온습도 영향도 보정되지 않았다.
- **관측 구간이 짧다.** 2.4시간은 프로토타입 검증용이며 현장 일반화의 증거가 아니다.
  일간·주간 주기, 환기 패턴, 계절 변동을 전혀 담지 못한다.
- **노드 일반화를 제대로 못 쟀다.** 4노드 전부 같은 시각 같은 공간에 있었으므로
  "다른 방의 다른 노드" 에 대한 일반화는 이 데이터로 검증할 수 없다.
- **외부 벤치마크(SKAB / UCI) 미수행.** 프롬프트 §11 은 공개 데이터가 제공되거나
  다운로드가 허용된 경우에만 수행하도록 규정한다.
