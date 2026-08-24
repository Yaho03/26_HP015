"""데이터 진단만 실행한다 (§3).

학습 전에 반드시 먼저 돌린다. 어떤 채널이 살아 있고 무엇을 왜 뺐는지가 여기서
정해지며, 그 결과가 그대로 feature manifest 가 된다.

  .venv/bin/python -m src.diagnose --source <tap.txt|dump.csv.gz> [--source ...]
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from src.data_loader import load_sources
from src.data_quality import diagnose


def main() -> int:
    parser = argparse.ArgumentParser(description="센서 시계열 품질 진단")
    parser.add_argument("--source", action="append", required=True)
    parser.add_argument("--json", help="진단 결과를 JSON 으로도 저장할 경로")
    parser.add_argument("--all-source-modes", action="store_true",
                        help="출처 필터를 끈다. 진단 목적으로만 쓰고 학습에는 쓰지 않는다")
    args = parser.parse_args()

    df = load_sources(
        [Path(s) for s in args.source],
        require_source_mode=None if args.all_source_modes else "live",
    )
    report = diagnose(df)
    print(report.render())

    if args.json:
        Path(args.json).write_text(json.dumps({
            "status": report.status,
            "nodes": report.nodes,
            "features_valid": report.features_valid,
            "features_rejected": [asdict(v) for v in report.features_rejected],
            "start_at": str(report.start_at),
            "end_at": str(report.end_at),
            "sampling_interval_median_s": report.sampling_interval_median_s,
            "valid_ratio_by_feature": report.valid_ratio_by_feature,
            "longest_gap_by_feature_s": report.longest_gap_by_feature_s,
            "constant_runs": report.constant_runs,
            "live_simulation_split": report.live_simulation_split,
            "duplicate_timestamps": report.duplicate_timestamps,
            "notes": report.notes,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    # 학습 가능 여부를 종료 코드로도 알린다 — CI 나 스크립트가 쓸 수 있게.
    return 0 if report.status == "DATA_READY" else 1


if __name__ == "__main__":
    sys.exit(main())
