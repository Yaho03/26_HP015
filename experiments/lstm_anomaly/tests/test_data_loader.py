"""로더는 어떤 입력이 오든 같은 long-format 프레임을 내놓아야 한다.

핵심 계약:
- 컬럼은 (time, node_id, metric, value, source_mode) 고정
- source_mode 가 'live' 가 아닌 행은 기본적으로 제외한다 (§0.1, §4.2)
- null 값은 행 자체를 만들지 않는다 (co2_ppm 처럼 100% null 인 필드가 0 으로
  둔갑하면 모델이 "CO2 는 항상 0" 을 정상 패턴으로 배운다)
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path

import pandas as pd
import pytest

from src.data_loader import LONG_COLUMNS, load_sources


def _msg(node="sensor-01", ts="2026-08-24T02:00:00.000Z", mode="live", **data) -> dict:
    return {
        "schema_version": "1.1",
        "message_id": f"01M0{node}{ts}",
        "node_id": node,
        "sampled_at": ts,
        "source_mode": mode,
        "quality": {"message_status": "complete", "time_synced": True, "sensors": {}},
        "data": data,
    }


def _write_tap(path: Path, msgs: list[dict], encoding: str = "utf-16") -> Path:
    lines = [f"sensors/{m['node_id']}/gas {json.dumps(m)}" for m in msgs]
    path.write_text("\n".join(lines), encoding=encoding)
    return path


def test_tap_utf16_is_decoded(tmp_path):
    """실측 tap 로그는 UTF-16 으로 떨어진다. UTF-8 로 읽으면 통째로 깨진다."""
    p = _write_tap(tmp_path / "tap.txt", [_msg(temperature_c=24.5)])
    df = load_sources([p])
    assert list(df.columns) == list(LONG_COLUMNS)
    assert len(df) == 1
    assert df.iloc[0]["metric"] == "temperature_c"
    assert df.iloc[0]["value"] == 24.5


def test_tap_utf8_also_works(tmp_path):
    p = _write_tap(tmp_path / "tap8.txt", [_msg(temperature_c=21.0)], encoding="utf-8")
    df = load_sources([p])
    assert df.iloc[0]["value"] == 21.0


def test_simulation_rows_are_dropped(tmp_path):
    p = _write_tap(tmp_path / "mixed.txt", [
        _msg(node="sensor-01", mode="live", temperature_c=24.0),
        _msg(node="sensor-01", mode="simulation", temperature_c=99.0),
    ])
    df = load_sources([p])
    assert list(df["value"]) == [24.0]
    assert set(df["source_mode"]) == {"live"}


def test_missing_source_mode_is_dropped(tmp_path):
    """출처 불명은 live 로 가정하지 않는다."""
    m = _msg(temperature_c=24.0)
    del m["source_mode"]
    p = _write_tap(tmp_path / "nomode.txt", [m])
    assert load_sources([p]).empty


def test_null_values_do_not_become_rows(tmp_path):
    """co2_ppm: null 이 0.0 행으로 저장되면 모델이 상수 0 을 정상으로 배운다."""
    p = _write_tap(tmp_path / "nulls.txt", [_msg(co2_ppm=None, temperature_c=24.0)])
    df = load_sources([p])
    assert set(df["metric"]) == {"temperature_c"}


def test_string_values_are_skipped(tmp_path):
    p = _write_tap(tmp_path / "str.txt", [
        _msg(mq7_calibration_status="uncalibrated", temperature_c=24.0),
    ])
    assert set(load_sources([p])["metric"]) == {"temperature_c"}


def test_non_telemetry_topics_ignored(tmp_path):
    """status / connection 토픽은 시계열 feature 가 아니다."""
    p = tmp_path / "mix.txt"
    gas = _msg(temperature_c=24.0)
    p.write_text(
        f"sensors/sensor-01/gas {json.dumps(gas)}\n"
        f"sensors/sensor-01/status {json.dumps(_msg(battery_pct=90))}\n",
        encoding="utf-16",
    )
    df = load_sources([p])
    assert set(df["metric"]) == {"temperature_c"}


def test_duplicate_message_ids_are_dropped(tmp_path):
    """QoS1 재전송으로 같은 message_id 가 두 번 잡힐 수 있다."""
    m = _msg(temperature_c=24.0)
    p = _write_tap(tmp_path / "dup.txt", [m, dict(m)])
    assert len(load_sources([p])) == 1


def test_csv_gz_source(tmp_path):
    """DB 덤프 CSV 도 같은 계약으로 들어와야 한다."""
    p = tmp_path / "d.csv.gz"
    frame = pd.DataFrame({
        "time": ["2026-08-24T02:00:00Z", "2026-08-24T02:00:01Z"],
        "node_id": ["sensor-01", "sensor-01"],
        "metric": ["temperature_c", "temperature_c"],
        "value": [24.0, 24.1],
        "source_mode": ["live", "simulation"],
    })
    with gzip.open(p, "wt", encoding="utf-8") as f:
        frame.to_csv(f, index=False)
    df = load_sources([p])
    assert list(df["value"]) == [24.0]


def test_csv_without_source_mode_column_is_rejected(tmp_path):
    """012 이전 덤프는 출처를 알 수 없다. 조용히 live 로 치면 안 된다."""
    p = tmp_path / "old.csv"
    pd.DataFrame({
        "time": ["2026-08-24T02:00:00Z"], "node_id": ["sensor-01"],
        "metric": ["temperature_c"], "value": [24.0],
    }).to_csv(p, index=False)
    assert load_sources([p]).empty


def test_multiple_sources_are_concatenated_and_sorted(tmp_path):
    a = _write_tap(tmp_path / "a.txt", [_msg(ts="2026-08-24T02:00:05.000Z", temperature_c=2.0)])
    b = _write_tap(tmp_path / "b.txt", [_msg(ts="2026-08-24T02:00:00.000Z", temperature_c=1.0)])
    df = load_sources([a, b])
    assert list(df["value"]) == [1.0, 2.0]


def test_time_column_is_utc_datetime(tmp_path):
    p = _write_tap(tmp_path / "t.txt", [_msg(temperature_c=24.0)])
    df = load_sources([p])
    assert pd.api.types.is_datetime64_any_dtype(df["time"])
    assert df["time"].dt.tz is not None


def test_unparseable_lines_do_not_abort(tmp_path):
    p = tmp_path / "junk.txt"
    p.write_text(
        "garbage line without json\n"
        f"sensors/sensor-01/gas {json.dumps(_msg(temperature_c=24.0))}\n",
        encoding="utf-16",
    )
    assert len(load_sources([p])) == 1
