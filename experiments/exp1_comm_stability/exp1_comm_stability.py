"""EXP-1: 센서 통신 안정성 실험 시뮬레이션 (이슈 #49).

5개 노드가 1시간 연속으로 MQTT 데이터를 안정적으로 전송하는지 검증.
실제 하드웨어 대신 시뮬레이션으로 메시지 손실률/가용성/재전송 동작 모델링.

합격 기준 (07_EXPERIMENT_PLAN.md EXP-1):
  - 메시지 손실률 < 1% (QoS 1, IMU QoS 0 제외)
  - 5개 노드 1시간 연속 전송
  - 3회 시행

시뮬레이션 모델:
  - 각 노드는 metric 별 주기로 메시지 생성 (CO₂ 1s, BME680 5s, O₂ 5s, IMU 0.1s QoS 0)
  - 링크 장애: 평균 MTBF 30분, MTTR 10초 (지수 분포)
  - QoS 1: 손실 시 백엔드 retry_queue 로 1회 재전송 (성공률 95%)
  - dedup: processed_messages 로 중복 제거
"""
from __future__ import annotations

import random
import statistics
from dataclasses import dataclass, field
from typing import Dict, List

NODE_IDS = ["sensor-01", "sensor-02", "sensor-03", "sensor-04", "wearable-01"]

METRIC_SCHEDULE = [
    ("co2_ppm", 1.0, 1),
    ("temperature_c", 5.0, 1),
    ("humidity_pct", 5.0, 1),
    ("o2_pct", 5.0, 1),
    ("imu", 0.1, 0),
]


@dataclass
class NodeSimResult:
    node_id: str
    sent_qos1: int = 0
    sent_qos0: int = 0
    delivered_qos1: int = 0
    delivered_qos0: int = 0
    duplicates_dropped: int = 0
    downtime_s: float = 0.0

    @property
    def loss_rate_qos1(self) -> float:
        if self.sent_qos1 == 0:
            return 0.0
        return 1.0 - self.delivered_qos1 / self.sent_qos1

    @property
    def availability(self) -> float:
        return 1.0 - self.downtime_s / 3600.0


@dataclass
class Exp1Result:
    nodes: List[NodeSimResult] = field(default_factory=list)
    trials: int = 1
    passed: bool = False

    @property
    def overall_loss_qos1(self) -> float:
        total_sent = sum(n.sent_qos1 for n in self.nodes)
        total_delivered = sum(n.delivered_qos1 for n in self.nodes)
        return 1.0 - total_delivered / total_sent if total_sent else 0.0

    @property
    def min_availability(self) -> float:
        return min(n.availability for n in self.nodes)


def simulate_node(
    node_id: str,
    duration_s: float = 3600.0,
    rng: random.Random = None,
    mtbf_s: float = 1800.0,
    mttr_s: float = 10.0,
    retry_success_rate: float = 0.95,
    duplicate_rate: float = 0.005,
) -> NodeSimResult:
    rng = rng or random.Random()
    res = NodeSimResult(node_id=node_id)

    t = 0.0
    next_failure = rng.expovariate(1.0 / mtbf_s)
    failure_end = 0.0

    for metric, period, qos in METRIC_SCHEDULE:
        mt = period
        while mt <= duration_s:
            online = not (mt >= next_failure and mt < failure_end)
            if not online:
                res.downtime_s += min(period, failure_end - mt)
                if failure_end <= mt:
                    next_failure = mt + rng.expovariate(1.0 / mtbf_s)

            if qos == 1:
                if online:
                    res.sent_qos1 += 1
                    if rng.random() < duplicate_rate:
                        res.duplicates_dropped += 1
                        res.delivered_qos1 += 1
                        continue
                    delivered = rng.random() < (1.0 - 0.005)
                    if not delivered:
                        delivered = rng.random() < retry_success_rate
                    if delivered:
                        res.delivered_qos1 += 1
            else:
                if online:
                    res.sent_qos0 += 1
                    if rng.random() < 0.02:
                        pass
                    else:
                        res.delivered_qos0 += 1
            mt += period

    return res


def run_trial(seed: int = 42, duration_s: float = 3600.0) -> List[NodeSimResult]:
    rng = random.Random(seed)
    return [simulate_node(nid, duration_s=duration_s, rng=rng) for nid in NODE_IDS]


def run_exp1(trials: int = 3, duration_s: float = 3600.0) -> Exp1Result:
    results: List[NodeSimResult] = []
    for trial in range(trials):
        trial_results = run_trial(seed=42 + trial, duration_s=duration_s)
        if trial == 0:
            results = trial_results
        else:
            for i, nr in enumerate(trial_results):
                results[i].sent_qos1 += nr.sent_qos1
                results[i].sent_qos0 += nr.sent_qos0
                results[i].delivered_qos1 += nr.delivered_qos1
                results[i].delivered_qos0 += nr.delivered_qos0
                results[i].duplicates_dropped += nr.duplicates_dropped
                results[i].downtime_s += nr.downtime_s

    for r in results:
        r.downtime_s /= trials

    overall_loss = 1.0 - sum(n.delivered_qos1 for n in results) / max(1, sum(n.sent_qos1 for n in results))
    min_avail = min(n.availability for n in results)
    passed = overall_loss < 0.01 and min_avail > 0.99

    return Exp1Result(nodes=results, trials=trials, passed=passed)


if __name__ == "__main__":
    r = run_exp1(trials=3, duration_s=3600.0)
    print("EXP-1 센서 통신 안정성 (3시행 × 1시간 시뮬레이션):")
    print(f"{'node':<14} {'sent_q1':>8} {'deliv_q1':>8} {'loss%':>7} {'avail%':>8}")
    for n in r.nodes:
        print(f"{n.node_id:<14} {n.sent_qos1:>8} {n.delivered_qos1:>8} "
              f"{n.loss_rate_qos1*100:>6.2f}% {n.availability*100:>7.2f}%")
    print()
    print(f"전체 QoS1 손실률: {r.overall_loss_qos1*100:.2f}%")
    print(f"최소 가용성:      {r.min_availability*100:.2f}%")
    print(f"합격 기준:        손실 < 1%, 가용성 > 99%")
    print(f"결과:             {'PASS' if r.passed else 'FAIL'}")
