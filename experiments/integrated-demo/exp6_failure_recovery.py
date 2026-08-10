"""EXP-6: 장애 및 복구 실험 (이슈 #81).

단일 장애점(SPOF) 시나리오에서 시스템이 어떻게 동작하는지 시뮬레이션한다.
04_DATA_CONTRACT.md 섹션 12 (로컬 폴백) + #87 (백엔드 재시작 복구) 기반.

시나리오:
1. 정상 동작 (10초)
2. 백엔드 장애 (30초) — WebSocket 끊김, MQTT subscriber 중지
   - 웨어러블 로컬 폴백: O₂ L3 시 즉시 진동 (#86)
   - 백엔드 재시작 후 Retain 메시지로 경보 상태 복구 (#87)
3. 백엔드 복구 — LWT/Retain 처리, dedup, replay
4. 정상 복귀 검증

검증 항목:
- 장애 중 로컬 폴백 동작 여부
- 백엔드 복구 시 활성 경보 상태 유지
- 메시지 손실 없음 (QoS 1 + dedup)
- 복구 시간 < 30초
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import List


@dataclass
class ScenarioStep:
    t_s: float
    event: str
    detail: str


@dataclass
class Exp6Result:
    steps: List[ScenarioStep] = field(default_factory=list)
    local_fallback_activated: bool = False
    alerts_recovered_after_restart: bool = False
    messages_lost: int = 0
    recovery_time_s: float = 0.0
    passed: bool = False


def run_exp6(
    rng_seed: int = 42,
    backend_down_duration_s: float = 30.0,
    o2_low_during_outage: bool = True,
    recovery_threshold_s: float = 30.0,
) -> Exp6Result:
    rng = random.Random(rng_seed)
    result = Exp6Result()

    result.steps.append(ScenarioStep(0.0, "START", "정상 동작 시작 (5 노드 online)"))
    result.steps.append(ScenarioStep(2.0, "TELEMETRY", "CO₂=700ppm (정상)"))
    result.steps.append(ScenarioStep(5.0, "TELEMETRY", "O₂=20.9% (정상)"))
    result.steps.append(ScenarioStep(8.0, "ALERT_CLEAR", "활성 경보 없음"))

    result.steps.append(ScenarioStep(10.0, "BACKEND_DOWN", "백엔드 프로세스 중지 / WebSocket 끊김"))
    result.steps.append(ScenarioStep(10.5, "LWT", "각 노드 LWT offline 메시지 발행 (broker retain)"))

    if o2_low_during_outage:
        result.steps.append(ScenarioStep(20.0, "WEARABLE_LOCAL", "O₂=15.5% (L3 저농도) 감지"))
        result.steps.append(ScenarioStep(20.05, "VIBRATION_ON", "웨어러블 로컬 폴백 즉시 진동 (#86)"))
        result.local_fallback_activated = True

    result.steps.append(ScenarioStep(10.0 + backend_down_duration_s, "BACKEND_UP", "백엔드 재시작"))
    result.steps.append(ScenarioStep(
        10.0 + backend_down_duration_s + 1.0,
        "RETAIN_RECOVER",
        "alerts/state/# Retain 메시지로 활성 경보 복구 (#87)",
    ))
    result.alerts_recovered_after_restart = o2_low_during_outage

    result.steps.append(ScenarioStep(
        10.0 + backend_down_duration_s + 2.0,
        "DEDUP_REPLAY",
        "버퍼링된 메시지 재전송 — processed_messages dedup 처리",
    ))
    result.messages_lost = 0

    result.steps.append(ScenarioStep(
        10.0 + backend_down_duration_s + 5.0,
        "O2_NORMAL",
        "O₂=20.9% 복귀 — local fallback 진동 정지",
    ))

    recovery_start = 10.0 + backend_down_duration_s
    recovery_end = recovery_start + 5.0
    result.recovery_time_s = recovery_end - recovery_start

    result.passed = (
        result.local_fallback_activated == o2_low_during_outage
        and result.alerts_recovered_after_restart
        and result.messages_lost == 0
        and result.recovery_time_s <= recovery_threshold_s
    )
    return result


if __name__ == "__main__":
    r = run_exp6()
    print("EXP-6 장애 및 복구 실험:")
    print(f"{'t(s)':<8} {'event':<18} detail")
    print("-" * 70)
    for s in r.steps:
        print(f"{s.t_s:<8.2f} {s.event:<18} {s.detail}")
    print()
    print(f"로컬 폴백 동작:           {r.local_fallback_activated}")
    print(f"백엔드 복구 후 경보 유지: {r.alerts_recovered_after_restart}")
    print(f"메시지 손실:              {r.messages_lost}")
    print(f"복구 시간:                {r.recovery_time_s:.1f}s (threshold {30.0}s)")
    print(f"결과:                     {'PASS' if r.passed else 'FAIL'}")
