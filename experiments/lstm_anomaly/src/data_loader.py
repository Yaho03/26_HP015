"""실측 센서 시계열을 하나의 long-format 프레임으로 모은다.

입력이 세 갈래인 이유:
- **MQTT tap 로그(.txt)** — 브로커에서 직접 뜬 원본. envelope 이 통째로 남아 있어
  source_mode·quality 까지 볼 수 있는 유일한 형식이다. 실측 검증 세션의 산출물.
- **CSV/CSV.gz** — DB 덤프. 이미 sensor_data 스키마로 펼쳐진 상태.
- **TimescaleDB** — 가동 중인 DB 직접 조회.

셋 다 (time, node_id, metric, value, source_mode) 로 정규화한다. 이후 단계는
어디서 왔는지 알 필요가 없다.

가장 중요한 규칙: **source_mode 가 'live' 인 행만 남긴다.**
04_DATA_CONTRACT 3.5 에 따라 주입 데이터도 실제 node_id 를 그대로 쓰므로,
node_id 로는 실측과 주입을 구분할 수 없다. 이 필드가 유일한 판별자다.
출처를 모르는 행(NULL/필드 없음)은 live 로 승격하지 않고 버린다 — 주입값 하나가
정상 패턴으로 섞이면 모델이 배우는 것은 센서가 아니라 시나리오 스크립트다.
"""
from __future__ import annotations

import gzip
import json
import logging
from pathlib import Path
from typing import Iterable, Iterator, List, Sequence, Union

import pandas as pd

logger = logging.getLogger(__name__)

LONG_COLUMNS = ("time", "node_id", "metric", "value", "source_mode")

LIVE = "live"

# tap 로그에서 시계열 feature 를 담는 토픽. status(배터리/RSSI)와 connection(LWT)은
# 센서 측정값이 아니므로 제외한다.
_TELEMETRY_SUFFIXES = ("gas", "env", "vital", "imu")

# tap 로그는 Windows 쪽 도구에서 UTF-16 으로 떨어진다. 순서가 중요하다 —
# utf-8 로 UTF-16 파일을 읽으면 예외 없이 NUL 섞인 쓰레기 문자열이 나온다.
_ENCODINGS = ("utf-16", "utf-16-le", "utf-8-sig", "utf-8")


def _decode(path: Path) -> str:
    raw = path.read_bytes()
    for enc in _ENCODINGS:
        try:
            text = raw.decode(enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
        # 인코딩이 맞으면 JSON 중괄호가 온전히 보인다. UTF-16 을 UTF-8 로 읽으면
        # 바이트 사이 NUL 때문에 '{' 가 거의 안 잡힌다.
        if "{" in text and "\x00" not in text[:4096]:
            return text
    raise ValueError(f"{path}: 알려진 인코딩으로 디코딩하지 못했습니다")


def _iter_tap_messages(path: Path) -> Iterator[dict]:
    """'<topic> <json>' 한 줄씩. 깨진 줄은 세어서 로그로만 남기고 넘어간다."""
    skipped = 0
    for line in _decode(path).splitlines():
        line = line.strip()
        if not line:
            continue
        brace = line.find(" {")
        if brace < 0:
            skipped += 1
            continue
        topic = line[:brace]
        if topic.rsplit("/", 1)[-1] not in _TELEMETRY_SUFFIXES:
            continue
        try:
            envelope = json.loads(line[brace + 1:])
        except json.JSONDecodeError:
            skipped += 1
            continue
        if isinstance(envelope, dict):
            yield envelope
        else:
            skipped += 1
    if skipped:
        logger.warning("%s: 해석하지 못한 줄 %d개를 건너뛰었습니다", path.name, skipped)


def _tap_to_rows(path: Path) -> List[tuple]:
    rows: List[tuple] = []
    seen_ids: set = set()
    for env in _iter_tap_messages(path):
        node_id = env.get("node_id")
        sampled_at = env.get("sampled_at")
        data = env.get("data")
        if not node_id or not sampled_at or not isinstance(data, dict):
            continue

        # QoS 1 재전송이 tap 에 두 번 잡힐 수 있다. 백엔드의 processed_messages 와
        # 같은 규칙(message_id 단위)으로 여기서도 한 번만 센다.
        message_id = env.get("message_id")
        if message_id is not None:
            if message_id in seen_ids:
                continue
            seen_ids.add(message_id)

        source_mode = env.get("source_mode")
        for metric, value in data.items():
            # None(센서 오류/미교정)은 행을 만들지 않는다. 0.0 으로 채우면
            # 모델이 "이 지표는 늘 0" 을 정상 패턴으로 학습한다.
            if value is None or isinstance(value, bool):
                continue
            if not isinstance(value, (int, float)):
                continue
            rows.append((sampled_at, node_id, metric, float(value), source_mode))
    return rows


def _read_tabular(path: Path) -> pd.DataFrame:
    opener = gzip.open if path.name.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as handle:  # type: ignore[operator]
        return pd.read_csv(handle)


def _tabular_to_frame(path: Path) -> pd.DataFrame:
    frame = _read_tabular(path)
    missing = {"time", "node_id", "metric", "value"} - set(frame.columns)
    if missing:
        raise ValueError(f"{path}: 필수 컬럼 누락 {sorted(missing)}")
    if "source_mode" not in frame.columns:
        # 012 마이그레이션 이전 덤프. 출처가 기록되지 않았으므로 되살릴 수 없다.
        # live 로 치면 데모 주입값이 학습셋에 통째로 들어간다.
        logger.warning(
            "%s: source_mode 컬럼이 없어 전체를 제외합니다 "
            "(012 이전 덤프 — 실측/주입 구분 불가)", path.name,
        )
        frame["source_mode"] = None
    return frame[list(LONG_COLUMNS)]


def load_sources(
    sources: Sequence[Union[str, Path]],
    *,
    require_source_mode: str = LIVE,
) -> pd.DataFrame:
    """여러 입력을 하나의 long-format 프레임으로 합친다.

    require_source_mode 를 None 으로 주면 출처 필터를 끈다. 진단 목적으로만 쓰고
    학습에는 쓰지 않는다.
    """
    frames: List[pd.DataFrame] = []
    for source in sources:
        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(path)
        if path.suffix == ".txt":
            frames.append(pd.DataFrame(_tap_to_rows(path), columns=list(LONG_COLUMNS)))
        else:
            frames.append(_tabular_to_frame(path))

    if not frames:
        return pd.DataFrame(columns=list(LONG_COLUMNS))

    df = pd.concat(frames, ignore_index=True)
    if df.empty:
        return df.astype({"value": "float64"})

    df["time"] = pd.to_datetime(df["time"], utc=True, format="ISO8601")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["time", "value"])

    if require_source_mode is not None:
        df = df[df["source_mode"] == require_source_mode]

    return (
        df.sort_values(["node_id", "metric", "time"], kind="stable")
        .reset_index(drop=True)
        .loc[:, list(LONG_COLUMNS)]
    )


def load_from_timescale(
    dsn: str,
    *,
    start: str,
    end: str,
    require_source_mode: str = LIVE,
) -> pd.DataFrame:
    """가동 중인 TimescaleDB 에서 직접 읽는다.

    psycopg 를 여기서만 import 하는 이유: DB 를 쓰지 않는 CSV/tap 경로가 드라이버
    설치 여부에 묶이면 안 되기 때문이다.
    """
    import psycopg

    sql = """
        SELECT time, node_id, metric, value, source_mode
        FROM sensor_data
        WHERE time BETWEEN %(start)s AND %(end)s
    """
    params = {"start": start, "end": end}
    if require_source_mode is not None:
        sql += " AND source_mode = %(mode)s"
        params["mode"] = require_source_mode
    sql += " ORDER BY node_id, metric, time"

    with psycopg.connect(dsn) as conn:
        frame = pd.read_sql(sql, conn, params=params)
    frame["time"] = pd.to_datetime(frame["time"], utc=True)
    return frame.loc[:, list(LONG_COLUMNS)]


def to_wide(df: pd.DataFrame, node_id: str, features: Iterable[str]) -> pd.DataFrame:
    """한 노드의 long 프레임을 time 인덱스 x feature 열 형태로 편다.

    같은 (time, metric) 이 여러 번 나오면 마지막 값을 쓴다 — 재전송으로 같은
    타임스탬프가 중복될 수 있고, 그때 평균을 내면 존재하지 않는 값이 만들어진다.
    """
    features = list(features)
    node_df = df[df["node_id"] == node_id]
    wide = (
        node_df.pivot_table(
            index="time", columns="metric", values="value", aggfunc="last"
        )
        .sort_index()
    )
    for feature in features:
        if feature not in wide.columns:
            wide[feature] = pd.NA
    return wide.loc[:, features].astype("float64")
