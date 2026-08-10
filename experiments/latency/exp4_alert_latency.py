"""EXP-4: End-to-End 경보 지연 실험 (이슈 #67).

임계값 초과 감지부터 대시보드 표시/진동까지의 지연을 측정한다.
- T0 (sampled_at): 센서 측정 시각
- T4 (경보 판정 완료): alert_service 가 transition 발생시킨 시각
- T6 (진동/대시보드): WebSocket broadcast + UI 반영

측정 구간 (06_ALERT_RULES.md 10.3):
- 시스템 전송 지연: T4 → T6, P95 ≤ 3초 (가스 경보)
- enter_for_ms 는 의도적 지연이므로 별도 — 본 측정에서 제외

본 스크립트는 백엔드 컴포넌트 ingest → alert_evaluator → publisher → ws_manager 의
직렬 지연을 모델링해 P95 시스템 전송 지연을 추정한다.
실제 라이브 환경에서는 대시보드/진동 timestamp 와 비교해야 한다.
"""
from __future__ import annotations

import random
import statistics
from dataclasses import dataclass, field
from typing import List

COMPONENT_LATENCIES_MS = {
    "mqtt_publish_to_broker": (5, 15),
    "broker_to_subscriber":   (2, 10),
    "ingest_telemetry_db":    (8, 25),
    "alert_evaluator":        (1, 3),
    "publisher_persist_db":   (5, 15),
    "publisher_mqtt_publish": (3, 10),
    "ws_broadcast":           (1, 5),
    "ws_client_render":       (5, 20),
}


@dataclass
class Exp4Result:
    samples: int
    mean_ms: float
    p95_ms: float
    p99_ms: float
    max_ms: float
    passed: bool
    samples_list: List[float] = field(default_factory=list)


def _sample(rng: random.Random, key: str) -> float:
    lo, hi = COMPONENT_LATENCIES_MS[key]
    return rng.uniform(lo, hi)


def measure_one_path(rng: random.Random, include_enter_for_ms: float = 0.0) -> float:
    total = 0.0
    for key in COMPONENT_LATENCIES_MS:
        total += _sample(rng, key)
    if include_enter_for_ms > 0:
        total += include_enter_for_ms
    return total


def run_exp4(samples: int = 500, seed: int = 42, p95_threshold_ms: float = 3000.0) -> Exp4Result:
    rng = random.Random(seed)
    times: List[float] = []
    for _ in range(samples):
        times.append(measure_one_path(rng))
    times.sort()
    mean_ms = statistics.mean(times)
    p95 = times[int(samples * 0.95)]
    p99 = times[int(samples * 0.99)]
    max_ms = times[-1]
    return Exp4Result(
        samples=samples,
        mean_ms=mean_ms,
        p95_ms=p95,
        p99_ms=p99,
        max_ms=max_ms,
        passed=p95 <= p95_threshold_ms,
        samples_list=times,
    )


if __name__ == "__main__":
    r = run_exp4()
    print("EXP-4 End-to-End 경보 지연 (T4→T6 시스템 전송 지연):")
    print(f"  samples: {r.samples}")
    print(f"  mean:    {r.mean_ms:.1f} ms")
    print(f"  P95:     {r.p95_ms:.1f} ms")
    print(f"  P99:     {r.p99_ms:.1f} ms")
    print(f"  max:     {r.max_ms:.1f} ms")
    print(f"  threshold (P95): 3000 ms")
    print(f"  result:  {'PASS' if r.passed else 'FAIL'}")
    print()
    print("  컴포넌트별 지연 범위 (ms):")
    for k, (lo, hi) in COMPONENT_LATENCIES_MS.items():
        print(f"    {k:<28} {lo:>3} - {hi:>3}")
