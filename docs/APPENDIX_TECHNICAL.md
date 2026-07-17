# APPENDIX TECHNICAL — 기술 부록 (수식, 알고리즘, 계산 예시)

| 항목 | 내용 |
|------|------|
| 문서명 | 기술 부록 |
| 버전 | v1.0 |
| 상태 | 확정 |
| 최종 수정일 | 2026-07-17 |

---

## 1. UWB DS-TWR 거리 측정 원리

### 1.1 메시지 교환 시퀀스

DS-TWR (Double-Sided Two-Way Ranging)는 Tag와 Anchor 간 3회 메시지 교환으로 거리를 측정한다.

```
Tag                                  Anchor
 |                                     |
 |------- Poll (시각: poll_tx) ------->|
 |                                     |
 |<------ Response (시각: resp_rx) ----|
 |                                     |
 |------- Final (시각: final_tx) ----->|
 |                                     |
```

각 시점에서 측정되는 타임스탬프:

| 기호 | 측정 주체 | 의미 |
|------|-----------|------|
| `poll_tx` | Tag | Poll 메시지 송신 시각 |
| `poll_rx` | Anchor | Poll 메시지 수신 시각 |
| `resp_tx` | Anchor | Response 메시지 송신 시각 |
| `resp_rx` | Tag | Response 메시지 수신 시각 |
| `final_tx` | Tag | Final 메시지 송신 시각 |
| `final_rx` | Anchor | Final 메시지 수신 시각 |

### 1.2 거리 계산 공식

왕복 시간들을 계산:

```
Ra = resp_rx - poll_tx     (Tag에서 측정한 Poll→Response 왕복 시간)
Rb = final_rx - resp_tx    (Anchor에서 측정한 Response→Final 왕복 시간)
Da = final_tx - resp_rx    (Tag의 응답 대기 시간)
Db = resp_tx - poll_rx     (Anchor의 응답 대기 시간)
```

비행 시간(ToF, Time of Flight):

```
ToF = (Ra * Rb - Da * Db) / (Ra + Rb + Da + Db)
```

거리:

```
거리 = ToF * c

여기서 c = 299,702,547 m/s (빛의 속도, 공기 중 근사값)
```

> 공식이 복잡해 보이지만, Tag와 Anchor 각각의 클럭 오차를 상쇄하여 정밀도를 높이는 것이 목적이다.

### 1.3 계산 예시

Tag와 Anchor가 1m 떨어져 있는 경우 (ToF = 1 / 299702547 = 3.337 ns):

실제 DWM1000 메시지 교환에서 측정되는 값들은 매우 짧은 시간이므로, 여기서는 이해를 돕기 위해 단순화한 값을 사용한다.

```
Ra = 200 ns  (Tag에서 Poll 송신 후 Response 수신까지)
Rb = 200 ns  (Anchor에서 Response 송신 후 Final 수신까지)
Da = 100 ns  (Tag 응답 대기)
Db = 100 ns  (Anchor 응답 대기)

ToF = (200 * 200 - 100 * 100) / (200 + 200 + 100 + 100)
    = (40000 - 10000) / 600
    = 30000 / 600
    = 50 ns

거리 = 50e-9 * 299702547 = 14.99 m
```

> 실제 구현에서는 antenna delay 보정 후 측정값이 실제 거리와 일치하도록 조정한다. 위 예시는 공식 적용 방법을 보여주기 위한 것이다.

### 1.4 Antenna Delay 보정

안테나 내부의 신호 처리 지연으로 인해 측정된 ToF가 실제 ToF보다 크게 측정된다. 이를 보정하려면:

1. **알려진 거리에서 측정**: Tag와 Anchor를 정확히 2m 떨어뜨려 배치
2. **측정값 확인**: DWM1000에서 측정된 거리가 예: 2.35m로 나옴
3. **Antenna delay 계산**: 오차 = 2.35 - 2.0 = 0.35m. 이를 ns로 변환: 0.35 / 299702547 = 1.17 ns
4. **펌웨어에 반영**: `dwt_setrxantennadelay()` 및 `dwt_settxantennadelay()`로 보정값 설정

> 각 DWM1000 모듈마다 편차가 있으므로, 개별 모듈마다 보정이 필요하다.

---

## 2. 2D Least Squares 위치 계산

### 2.1 문제 정의

4개 앵커의 좌표 `(x_i, y_i)`와 Tag로부터의 거리 `d_i`가 주어졌을 때, Tag의 위치 `(x, y)`를 구한다.

### 2.2 수식 도출

거리 방정식:

```
d_i^2 = (x - x_i)^2 + (y - y_i)^2    (i = 0, 1, 2, 3)
```

전개:

```
d_i^2 = x^2 - 2*x*x_i + x_i^2 + y^2 - 2*y*y_i + y_i^2
```

기준 앵커(anchor 0)의 식을 나머지에서 뺀다 (x^2, y^2 항 소거):

```
d_0^2 - d_j^2 = -2*x*x_0 + x_0^2 + 2*x*x_j - x_j^2
                 -2*y*y_0 + y_0^2 + 2*y*y_j - y_j^2

정리하면:

2*(x_j - x_0)*x + 2*(y_j - y_0)*y = d_0^2 - d_j^2 + x_j^2 - x_0^2 + y_j^2 - y_0^2
```

j = 1, 2, 3에 대해 3개의 선형 방정식이 생성된다.

행렬 형태: `A * p = b`

```
A = | 2*(x1-x0)   2*(y1-y0) |
    | 2*(x2-x0)   2*(y2-y0) |
    | 2*(x3-x0)   2*(y3-y0) |

b = | d0^2 - d1^2 + x1^2 - x0^2 + y1^2 - y0^2 |
    | d0^2 - d2^2 + x2^2 - x0^2 + y2^2 - y0^2 |
    | d0^2 - d3^2 + x3^2 - x0^2 + y3^2 - y0^2 |

p = | x |
    | y |
```

방정식이 3개, 미지수가 2개이므로 **최소제곱법(Least Squares)** 으로 해를 구한다:

```
p = (A^T * A)^-1 * A^T * b
```

### 2.3 계산 예시

앵커 배치 (2m x 1.5m 직사각형):

| 앵커 | x (m) | y (m) |
|------|-------|-------|
| Anchor 0 | 0.0 | 0.0 |
| Anchor 1 | 2.0 | 0.0 |
| Anchor 2 | 2.0 | 1.5 |
| Anchor 3 | 0.0 | 1.5 |

Tag의 실제 위치: (1.0, 0.75) — 중심점

각 앵커까지의 거리:

```
d0 = sqrt((1.0-0.0)^2 + (0.75-0.0)^2) = sqrt(1 + 0.5625) = sqrt(1.5625) = 1.25 m
d1 = sqrt((1.0-2.0)^2 + (0.75-0.0)^2) = sqrt(1 + 0.5625) = 1.25 m
d2 = sqrt((1.0-2.0)^2 + (0.75-1.5)^2) = sqrt(1 + 0.5625) = 1.25 m
d3 = sqrt((1.0-0.0)^2 + (0.75-1.5)^2) = sqrt(1 + 0.5625) = 1.25 m
```

행렬 A, b 구성 (x0=0, y0=0이므로 단순화):

```
A = | 2*(2-0)   2*(0-0) |   | 4  0 |
    | 2*(2-0)   2*(1.5-0)| = | 4  3 |
    | 2*(0-0)   2*(1.5-0)|   | 0  3 |

b = | 1.5625 - 1.5625 + 4 - 0 + 0 - 0 |   | 4.0 |
    | 1.5625 - 1.5625 + 4 - 0 + 2.25 - 0 | = | 6.25|
    | 1.5625 - 1.5625 + 0 - 0 + 2.25 - 0 |   | 2.25|
```

정규 방정식 풀이:

```
A^T * A = | 4  4  0 |   | 4  0 |   | 32  12 |
          | 0  3  3 | x | 4  3 | = | 12  18 |
                      | 0  3 |

(A^T * A)^-1 = 1/(32*18 - 12*12) * | 18  -12 |
                                    | -12  32 |
                 = 1/432 * | 18  -12 |
                           | -12  32 |

A^T * b = | 4  4  0 |   | 4.0  |   | 4*4 + 4*6.25      |   | 41.0 |
          | 0  3  3 | x | 6.25 | = | 3*6.25 + 3*2.25   | = | 25.5 |
                      | 2.25 |

p = (A^T * A)^-1 * A^T * b
  = 1/432 * | 18  -12 |   | 41.0 |
            | -12  32 | x | 25.5 |

  = 1/432 * | 18*41 - 12*25.5 |
            | -12*41 + 32*25.5|

  = 1/432 * | 738 - 306  |
            | -492 + 816 |

  = 1/432 * | 432  |
            | 324  |

  = | 1.0  |
    | 0.75 |
```

결과: (x, y) = (1.0, 0.75) — 실제 위치와 정확히 일치.

### 2.4 Python 구현

```python
import numpy as np

def least_squares_position(anchors, distances):
    """
    anchors: [(x0,y0), (x1,y1), (x2,y2), (x3,y3)]
    distances: [d0, d1, d2, d3]
    returns: (x, y)
    """
    x0, y0 = anchors[0]
    A = []
    b = []
    for j in range(1, len(anchors)):
        xj, yj = anchors[j]
        A.append([2*(xj - x0), 2*(yj - y0)])
        b.append(distances[0]**2 - distances[j]**2
                 + xj**2 - x0**2 + yj**2 - y0**2)

    A = np.array(A)
    b = np.array(b)

    # (A^T A)^-1 A^T b (최소제곱해)
    result = np.linalg.lstsq(A, b, rcond=None)[0]
    return result[0], result[1]

# 사용 예시
anchors = [(0, 0), (2, 0), (2, 1.5), (0, 1.5)]
distances = [1.25, 1.25, 1.25, 1.25]
x, y = least_squares_position(anchors, distances)
print(f"Tag 위치: ({x:.2f}, {y:.2f})")
# 출력: Tag 위치: (1.00, 0.75)
```

---

## 3. Hysteresis 상태 머신

### 3.1 개념

임계값 부근에서 측정값이 미세하게 변동할 때 경보가 반복적으로 발생/해제되는 현상(flickering)을 방지하기 위해, 경보 발생 임계값과 해제 임계값을 다르게 설정한다.

### 3.2 상태 전이도

```
              enter_threshold 초과
    Normal ─────────────────────────► Pending_Enter
      ▲                                   │
      │                             enter_for_ms 경과
      │                                   │
      │                                   ▼
      │                               Active (경보 발령)
      │                                   │
      │             exit_threshold 미만   │
      │             exit_for_ms 경과      │
      └───────────────────────────────────┘
```

**취소 조건**:
- Pending_Enter 상태에서 측정값이 enter_threshold 미만으로 떨어지면 → 타이머 취소, Normal 복귀
- Active 상태에서 exit 타이머 도중 측정값이 exit_threshold 초과로 회복하면 → 타이머 취소, Active 유지

### 3.3 계산 예시 (CO2 Level 2)

파라미터:
- `enter_threshold`: 2000 ppm
- `enter_for_ms`: 3000 (3초)
- `exit_threshold`: 1800 ppm (Hysteresis gap = 200 ppm)
- `exit_for_ms`: 5000 (5초)

**시나리오 1: 정상 경보 발생 → 해제**

```
t=0s:   CO2=2100 ppm (> enter_threshold 2000) → Pending_Enter 타이머 시작
t=1s:   CO2=2050 ppm (> 2000) → 타이머 계속
t=2s:   CO2=2200 ppm (> 2000) → 타이머 계속
t=3s:   enter_for_ms(3000ms) 경과, CO2 계속 > 2000 → Active (Level 2 경보 발령)
        → alerts/events 발행, alerts/state retain 갱신
        → 웨어러블 진동: 1초 x 3회 반복

t=10s:  CO2=1750 ppm (< exit_threshold 1800) → Pending_Exit 타이머 시작
t=11s:  CO2=1700 ppm (< 1800) → 타이머 계속
t=15s:  exit_for_ms(5000ms) 경과, CO2 계속 < 1800 → Normal (경보 해제)
        → alerts/events 발행 (status: resolved)
```

**시나리오 2: 타이머 취소 (오탐 방지)**

```
t=0s:   CO2=2100 ppm → Pending_Enter 시작
t=1s:   CO2=1950 ppm (< enter_threshold 2000) → 타이머 취소, Normal 유지
        (3초 미만으로 지속되지 않았으므로 경보 발령 안 함)
```

### 3.4 De-escalation 규칙

경보 해제 시 한 단계씩만 하향한다.

```
현재: Level 3 (위험)
    → exit 조건 충족 → Level 2 (경고) 로 하향
    → (Normal로 직접 가지 않음)

현재: Level 2 (경고)
    → exit 조건 충족 → Level 1 (주의) 로 하향

현재: Level 1 (주의)
    → exit 조건 충족 → Normal
```

이유: Level 3에서 갑자기 Normal이 되면 작업자가 "이제 안전한가?" 혼란을 겪을 수 있다. 단계적 하향으로 잔여 위험 가능성을 상기시킨다.

---

## 4. EWMA (Exponentially Weighted Moving Average)

### 4.1 공식

```
EWMA_t = alpha * x_t + (1 - alpha) * EWMA_{t-1}
EWMA_0 = x_0   (초기값 = 첫 측정값)
```

- `x_t`: 시각 t의 측정값
- `EWMA_t`: 시각 t의 EWMA 값
- `alpha`: 평활화 계수 (0 < alpha <= 1)

### 4.2 alpha 선택 가이드

| alpha | 효과 | 적용 상황 |
|-------|------|-----------|
| 0.1 | 강한 평활화, 노이즈 제거 우수 | 노이즈가 많은 센서, 반응 속도 느림 |
| 0.2 | 보통 평활화 | 일반적 권장 시작값 |
| 0.3 | 보통 | 본 프로젝트 추천값 (추세 분석용) |
| 0.5 | 약한 평활화, 빠른 반응 | 노이즈가 적은 센서 |
| 1.0 | 평활화 없음 (원시값과 동일) | 평활화 비활성 |

### 4.3 계산 예시

측정값: `[100, 105, 300, 110, 108]` (300은 spike), `alpha = 0.3`

```
EWMA_0 = 100   (초기값)

EWMA_1 = 0.3 * 105 + 0.7 * 100
       = 31.5 + 70
       = 101.5

EWMA_2 = 0.3 * 300 + 0.7 * 101.5
       = 90 + 71.05
       = 161.05   (스파이크 300이 161로 완화됨)

EWMA_3 = 0.3 * 110 + 0.7 * 161.05
       = 33 + 112.74
       = 145.74

EWMA_4 = 0.3 * 108 + 0.7 * 145.74
       = 32.4 + 102.02
       = 134.42
```

비교: 원시값 `[100, 105, 300, 110, 108]` vs EWMA `[100, 101.5, 161.05, 145.74, 134.42]`

스파이크(300)가 EWMA에서는 161으로 크게 완화되었지만, 영향은 잔존한다. alpha가 작을수록 잔존 효과가 오래 지속된다.

### 4.4 Python 구현

```python
class EWMAFilter:
    def __init__(self, alpha=0.3):
        self.alpha = alpha
        self.value = None

    def update(self, x):
        if self.value is None:
            self.value = x
        else:
            self.value = self.alpha * x + (1 - self.alpha) * self.value
        return self.value

# 사용 예시
ewma = EWMAFilter(alpha=0.3)
measurements = [100, 105, 300, 110, 108]
for m in measurements:
    filtered = ewma.update(m)
    print(f"측정: {m}, EWMA: {filtered:.2f}")
```

출력:
```
측정: 100, EWMA: 100.00
측정: 105, EWMA: 101.50
측정: 300, EWMA: 161.05
측정: 110, EWMA: 145.74
측정: 108, EWMA: 134.42
```

---

## 5. 좌표 변환 (Physical Z-up ↔ Three.js Y-up)

### 5.1 왜 변환이 필요한가?

| 좌표계 | 위쪽 축 | 사용처 |
|--------|---------|--------|
| Physical (Z-up) | Z | UWB 측정, CAD 모델링, 건축/토목 표준 |
| Three.js / OpenGL (Y-up) | Y | 웹 3D 렌더링 표준 |

UWB에서 측정한 물리 좌표를 Three.js에서 렌더링하려면 변환이 필요하다.

### 5.2 변환 공식

```
three_x =  physical_x    (X축은 동일)
three_y =  physical_z    (Z가 Y로 이동)
three_z = -physical_y    (Y가 -Z로, 오른손 좌표계 유지)
```

직관적 이해:
- Physical에서 X(앞), Y(옆), Z(위)
- Three.js에서 X(앞, 동일), Y(위), Z(옆, 방향 반대)
- Y와 Z가 서로 자리를 바꾸고, 옆축이 반전됨

### 5.3 계산 예시

센서 노드가 Physical 좌표 (1.0, 2.0, 0.0)에 설치된 경우:
- physical_x = 1.0 (앞쪽 1m)
- physical_y = 2.0 (오른쪽 2m)
- physical_z = 0.0 (바닥)

```
three_x = 1.0
three_y = 0.0   (= physical_z, 바닥)
three_z = -2.0  (= -physical_y, 오른쪽 2m → 뒤쪽 -2m)
```

3D 공간에서 이 노드는: 앞쪽 1m, 바닥, 뒤쪽으로 2m 위치에 렌더링된다.

### 5.4 JavaScript (TypeScript) 구현

```typescript
interface Position3D {
  x: number;
  y: number;
  z: number;
}

/** Physical 좌표계 (Z-up) → Three.js 좌표계 (Y-up) */
function physicalToThree(pos: Position3D): Position3D {
  return {
    x: pos.x,
    y: pos.z,
    z: -pos.y,
  };
}

/** Three.js 좌표계 (Y-up) → Physical 좌표계 (Z-up) */
function threeToPhysical(pos: Position3D): Position3D {
  return {
    x: pos.x,
    y: -pos.z,
    z: pos.y,
  };
}

// 사용 예시: UWB 위치를 3D 마커에 적용
const uwbPosition: Position3D = { x: 1.0, y: 2.0, z: 0.0 };
const threePosition = physicalToThree(uwbPosition);
// → { x: 1.0, y: 0.0, z: -2.0 }

meshRef.current.position.set(
  threePosition.x,
  threePosition.y,
  threePosition.z
);
```

---

## 6. 낙상 감지 알고리즘

### 6.1 개요

MPU-6050 가속도 데이터로 낙상(fall)을 감지하는 2단계 알고리즘. 단순한 임계값 검사가 아닌 "충격 후 정지" 패턴을 확인하여 오탐을 줄인다.

### 6.2 합성 가속도 벡터

3축 가속도 데이터로부터 중력 방향과 무관한 전체 가속도 크기를 계산:

```
|a| = sqrt(ax^2 + ay^2 + az^2)
```

상태별 |a| 값:

| 상태 | |a| 값 | 이유 |
|------|--------|------|
| 정지 (서 있음) | ~1.0 g | 중력만 작용 |
| 걷기 | 1.0~1.5 g | 가감속 |
| 낙하 중 | ~0 g | 자유낙하 (무중력) |
| 충격 (땅에 떨어짐) | 2.5g 이상 | 순간 큰 가속도 |
| 낙상 후 정지 | ~1.0 g 이하 | 움직임 없음 |

### 6.3 감지 로직

```
1단계 (충격 감지): |a| >= 2.5g 순간이 있었는가?
    → Yes: 잠재적 낙상, 2단계로
    → No: 정상 상태

2단계 (정지 확인): 충격 후 1초 이상 |a| < 1.2g (정적 범위)로 유지되는가?
    → Yes: 낙상 확정 → Level 3 경보 발령
    → No: 단순한 충격 (점프 등), 정상 복귀
```

> |a| < 1.2g가 정적으로 간주되는 이유: 완전한 정지(1.0g)에 약간의 미동이 있을 수 있으므로 여유를 둔다.

### 6.4 Python 의사코드

```python
import math

FALL_THRESHOLD_G = 2.5     # 충격 감지 임계값
STATIC_THRESHOLD_G = 1.2   # 정적 상태 임계값
STATIC_DURATION_MS = 1000  # 정지 지속 시간 (1초)

def compute_magnitude(ax, ay, az):
    """합성 가속도 벡터 계산 (g 단위)"""
    return math.sqrt(ax**2 + ay**2 + az**2)

def check_fall(accel_buffer, sample_rate_hz=50):
    """
    accel_buffer: 최근 2초 이상의 (ax, ay, az) 시계열 데이터
    sample_rate_hz: 샘플링 주기 (기본 50Hz)
    returns: True if fall detected
    """
    magnitudes = [compute_magnitude(ax, ay, az)
                  for ax, ay, az in accel_buffer]

    # 1단계: 2.5g 초과 순간 탐색
    impact_idx = None
    for i, m in enumerate(magnitudes):
        if m >= FALL_THRESHOLD_G:
            impact_idx = i
            break

    if impact_idx is None:
        return False  # 충격 없음

    # 2단계: 충격 이후 정지 확인
    samples_needed = int(sample_rate_hz * STATIC_DURATION_MS / 1000)
    post_impact = magnitudes[impact_idx + 1:]

    if len(post_impact) < samples_needed:
        return False  # 데이터 부족, 판정 보류

    static_period = post_impact[:samples_needed]
    is_static = all(m < STATIC_THRESHOLD_G for m in static_period)

    return is_static  # True = 낙상 확정

# 사용 예시 (50Hz 샘플링)
# accel_buffer에 최근 100개 샘플 (2초분)이 있다고 가정
# if check_fall(accel_buffer):
#     publish_fall_alert()  # Level 3 경보
```

### 6.5 ESP32 Arduino 구현 포인트

```cpp
// MPU-6050 데이터 읽기 (간략화)
float ax = (accelX_raw / 16384.0);  // ±2g 범위 기준
float ay = (accelY_raw / 16384.0);
float az = (accelZ_raw / 16384.0);

float magnitude = sqrt(ax*ax + ay*ay + az*az);

//ring buffer에 magnitude 저장 (최근 2초 = 100샘플 @ 50Hz)
// 주기적으로 check_fall() 호출
```

---

## 7. IDW (Inverse Distance Weighting) 보간

### 7.1 개념

4개 센서 노드의 가스 농도 측정값으로, 센서 간 공간의 농도 분포를 추정한다. 가까운 센서일수록 더 큰 영향을 미친다.

### 7.2 공식

```
w_hat(x) = sum_i(w_i * c_i) / sum_i(w_i)

w_i = 1 / d_i^p

c_i: 센서 i의 측정값 (농도)
d_i: 추정 위치 x에서 센서 i까지의 거리
p: 가중치 감쇠 지수 (본 프로젝트에서 p = 2)
```

p값에 따른 가중치 변화:

| p | 특성 |
|---|------|
| 1 | 거리에 선형 반비례, 넓은 영향 |
| 2 | 거리 제곱에 반비례 (권장), 중간 영향 |
| 3+ | 가까운 센서만 영향, 국소적 |

### 7.3 계산 예시

센서 배치 및 측정값:

| 센서 | x (m) | y (m) | 농도 (ppm) |
|------|-------|-------|-----------|
| Sensor 0 | 0.0 | 0.0 | 100 |
| Sensor 1 | 2.0 | 0.0 | 300 |
| Sensor 2 | 2.0 | 1.5 | 200 |
| Sensor 3 | 0.0 | 1.5 | 150 |

**사례 1: 중심점 (1.0, 0.75) 추정** (모든 센서와 등거리)

```
d0 = sqrt(1 + 0.5625) = 1.25
d1 = sqrt(1 + 0.5625) = 1.25
d2 = sqrt(1 + 0.5625) = 1.25
d3 = sqrt(1 + 0.5625) = 1.25

모든 거리가 같으므로 단순 평균:
w_hat = (100 + 300 + 200 + 150) / 4 = 187.5 ppm
```

**사례 2: Sensor 0 근처 (0.5, 0.3) 추정**

```
d0 = sqrt(0.25 + 0.09) = sqrt(0.34)  = 0.583
d1 = sqrt(2.25 + 0.09) = sqrt(2.34)  = 1.530
d2 = sqrt(2.25 + 1.44) = sqrt(3.69)  = 1.921
d3 = sqrt(0.25 + 1.44) = sqrt(1.69)  = 1.300

가중치 (p=2):
w0 = 1 / 0.583^2 = 1 / 0.340 = 2.944
w1 = 1 / 1.530^2 = 1 / 2.341 = 0.427
w2 = 1 / 1.921^2 = 1 / 3.690 = 0.271
w3 = 1 / 1.300^2 = 1 / 1.690 = 0.592

분자 = 2.944*100 + 0.427*300 + 0.271*200 + 0.592*150
     = 294.4 + 128.1 + 54.2 + 88.8
     = 565.5

분모 = 2.944 + 0.427 + 0.271 + 0.592
     = 4.234

w_hat = 565.5 / 4.234 = 133.6 ppm
```

Sensor 0 (100 ppm)에 가장 가까우므로 추정값 133.6은 100에 가깝게 나온다.

### 7.4 TypeScript 구현 (프론트엔드)

```typescript
interface Sensor {
  x: number;
  y: number;
  value: number;
}

function idw_interpolate(
  sensors: Sensor[],
  targetX: number,
  targetY: number,
  p: number = 2
): number {
  let numerator = 0;
  let denominator = 0;

  for (const s of sensors) {
    const dx = targetX - s.x;
    const dy = targetY - s.y;
    const distance = Math.sqrt(dx * dx + dy * dy);

    if (distance === 0) return s.value; // 센서 위치와 정확히 일치

    const weight = 1 / Math.pow(distance, p);
    numerator += weight * s.value;
    denominator += weight;
  }

  return numerator / denominator;
}

// 사용 예시
const sensors: Sensor[] = [
  { x: 0.0, y: 0.0, value: 100 },
  { x: 2.0, y: 0.0, value: 300 },
  { x: 2.0, y: 1.5, value: 200 },
  { x: 0.0, y: 1.5, value: 150 },
];

const value1 = idw_interpolate(sensors, 1.0, 0.75);  // 187.5
const value2 = idw_interpolate(sensors, 0.5, 0.3);   // 133.6
```

### 7.5 주의사항

- IDW 추정값은 경보 판정에 사용하지 않는다 (ADR-005). 시각화(히트맵 색상) 전용.
- 4개 센서는 같은 높이에 설치되므로 2D 평면 보간만 수행한다.
- 2개 이상의 센서가 오프라인 시 히트맵을 비활성화한다 (`05_DIGITAL_TWIN_SPEC.md` 섹션 7.3 참조).
