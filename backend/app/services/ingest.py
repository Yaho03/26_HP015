import json
import logging
from datetime import datetime
from typing import Any, List, Tuple

import asyncpg

from app.db import get_pool
from app.observability import metrics

logger = logging.getLogger(__name__)

# data 필드 중 sensor_data(숫자 metric)에 저장하지 않는 필드 (열거형/문자열 상태값)
_SKIP_FIELDS = {
    "co_calibration_status",
    "h2s_calibration_status",
    "mq2_calibration_status",
    "coordinate_system",
    "method",
}

_alert_callback = None
_location_callback = None
_reading_callback = None
_status_callback = None


def set_alert_callback(callback) -> None:
    """경보 판정 콜백 주입. ingest_telemetry 가 각 metric 저장 후 호출한다.
    백엔드 startup(mqtt_subscriber.start)에서 alert_service 로부터 주입한다 (#54)."""
    global _alert_callback
    _alert_callback = callback


def set_reading_callback(callback) -> None:
    """정상 센서 측정값 브로드캐스트 콜백 주입. ingest_telemetry 가 각 metric 저장 후
    호출한다. sensor_broadcast.init() 에서 등록한다 (#106) — 경보가 없어도
    대시보드가 실시간 값을 받아야 하므로 alert_callback과는 별개로 항상 호출된다."""
    global _reading_callback
    _reading_callback = callback


def set_status_callback(callback) -> None:
    """node_status 브로드캐스트 콜백 주입. ingest_status 가 저장 후 호출한다.
    sensor_broadcast.init() 에서 등록한다 (#106)."""
    global _status_callback
    _status_callback = callback


def set_location_callback(callback) -> None:
    """위치 필터링 콜백 주입. ingest_telemetry 가 location metric(x_m/y_m/z_m) 을
    만나면 호출한다 (#70). location_service.init() 에서 등록한다."""
    global _location_callback
    _location_callback = callback


class DuplicateMessage(Exception):
    """이미 처리한 message_id (FR-101 dedup). 재시도 대상 아님 — 정상 스킵."""


class InvalidMessage(Exception):
    """복구 불가능한 메시지 (JSON 파싱 실패, 필수 필드 누락/타입 오류 등).
    재시도해도 절대 성공하지 못하므로 retry queue에 넣지 않고 즉시 drop한다."""


def _parse_envelope(payload: bytes) -> dict:
    """JSON 파싱 + 최상위 값이 object인지 확인. `123`, `null`, `[...]`처럼
    문법상 유효한 JSON이지만 object가 아니면 이후 _require()의 `in` 연산에서
    TypeError가 새어나가므로 여기서 미리 InvalidMessage로 차단한다."""
    try:
        envelope = json.loads(payload)
    except json.JSONDecodeError as e:
        raise InvalidMessage(f"invalid JSON: {e}") from e
    if not isinstance(envelope, dict):
        raise InvalidMessage(
            f"envelope must be a JSON object, got {type(envelope).__name__}: {envelope!r}"
        )
    return envelope


def _require(obj: dict, *keys: str) -> List[Any]:
    """dict에서 필수 키들을 꺼낸다. 하나라도 없으면 InvalidMessage."""
    values = []
    for key in keys:
        if key not in obj:
            raise InvalidMessage(f"missing required field: {key}")
        values.append(obj[key])
    return values


def _parse_ts(value: Any) -> datetime:
    """ISO8601 'Z' 접미사를 asyncpg가 받는 datetime으로 변환 (asyncpg는 문자열을 암묵 변환하지 않음).
    value가 문자열이 아니면(.replace 호출 시 AttributeError) InvalidMessage로 먼저 걸러낸다."""
    if not isinstance(value, str):
        raise InvalidMessage(
            f"timestamp must be a string, got {type(value).__name__}: {value!r}"
        )
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as e:
        raise InvalidMessage(f"invalid timestamp: {value!r} ({e})") from e


def _expect_int(value: Any, field_name: str) -> int:
    """정수 필드 타입 검증. bool은 int의 서브클래스라 명시적으로 제외."""
    if isinstance(value, bool):
        raise InvalidMessage(f"field '{field_name}' must be an integer, got bool")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    raise InvalidMessage(
        f"field '{field_name}' must be an integer, got {type(value).__name__}: {value!r}"
    )


def _expect_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise InvalidMessage(
            f"field '{field_name}' must be a string, got {type(value).__name__}: {value!r}"
        )
    return value


def _expect_str_list(value: Any, field_name: str) -> list:
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        raise InvalidMessage(f"field '{field_name}' must be a list of strings, got {value!r}")
    return value


def _extract_metrics(data: dict) -> List[Tuple[str, float]]:
    """data 객체에서 숫자 metric만 추출. 문자열(calibration_status 등)은 스킵, boolean은 0/1 변환."""
    metrics: List[Tuple[str, float]] = []
    for key, value in data.items():
        if key in _SKIP_FIELDS:
            continue
        if isinstance(value, bool):
            metrics.append((key, 1.0 if value else 0.0))
        elif isinstance(value, (int, float)):
            metrics.append((key, float(value)))
        # None 또는 그 외 문자열은 저장하지 않음
    return metrics


async def _mark_processed(conn: asyncpg.Connection, message_id: str, node_id: str) -> bool:
    """processed_messages 1차 방어선. 새로 기록되면 True, 이미 있으면 False(중복)."""
    row = await conn.fetchrow(
        """
        INSERT INTO processed_messages (message_id, node_id)
        VALUES ($1, $2)
        ON CONFLICT (message_id) DO NOTHING
        RETURNING message_id
        """,
        message_id,
        node_id,
    )
    return row is not None


async def ingest_telemetry(payload: bytes) -> None:
    """sensors/*/gas, sensors/*/env, wearable/*/location, wearable/*/imu, wearable/*/vital 공통 처리."""
    envelope = _parse_envelope(payload)
    message_id, node_id, sampled_at_raw, data = _require(
        envelope, "message_id", "node_id", "sampled_at", "data"
    )
    message_id = _expect_str(message_id, "message_id")
    node_id = _expect_str(node_id, "node_id")
    if not isinstance(data, dict):
        raise InvalidMessage("'data' field is not an object")
    sampled_at = _parse_ts(sampled_at_raw)

    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            is_new = await _mark_processed(conn, message_id, node_id)
            if not is_new:
                raise DuplicateMessage(message_id)

            extracted = _extract_metrics(data)
            if extracted:
                await conn.executemany(
                    """
                    INSERT INTO sensor_data (time, node_id, metric, value, message_id)
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT DO NOTHING
                    """,
                    [
                        (sampled_at, node_id, metric, value, message_id)
                        for metric, value in extracted
                    ],
                )

            for metric, value in extracted:
                if _alert_callback is not None:
                    try:
                        await _alert_callback(node_id, metric, value, sampled_at)
                    except Exception:
                        logger.exception(
                            "alert evaluation failed (node=%s metric=%s value=%s)",
                            node_id, metric, value,
                        )
                if _reading_callback is not None:
                    try:
                        await _reading_callback(node_id, metric, value, sampled_at)
                    except Exception:
                        logger.exception(
                            "reading broadcast failed (node=%s metric=%s value=%s)",
                            node_id, metric, value,
                        )
                metrics.increment("messages_processed")

    if _location_callback is not None and isinstance(data, dict):
        if "x_m" in data and "y_m" in data and "z_m" in data:
            try:
                await _location_callback(
                    node_id,
                    float(data["x_m"]),
                    float(data["y_m"]),
                    float(data["z_m"]),
                    sampled_at,
                )
            except Exception:
                logger.exception(
                    "location callback failed (node=%s)", node_id,
                )


async def ingest_status(payload: bytes) -> None:
    """sensors/*/status 처리 — node_status 에 upsert.

    데이터 계약 7.2절("sampled_at 기준으로 정렬 처리")에 따라, 이미 저장된 값보다
    오래된(sampled_at이 더 과거인) 메시지는 무시한다 — 재전송/재시도로 뒤늦게 도착한
    메시지가 더 최신 값을 덮어쓰는 것을 방지한다.
    """
    envelope = _parse_envelope(payload)
    message_id, node_id, sampled_at_raw, data = _require(
        envelope, "message_id", "node_id", "sampled_at", "data"
    )
    message_id = _expect_str(message_id, "message_id")
    node_id = _expect_str(node_id, "node_id")
    if not isinstance(data, dict):
        raise InvalidMessage("'data' field is not an object")
    sampled_at = _parse_ts(sampled_at_raw)
    (
        battery_pct,
        wifi_rssi_dbm,
        uptime_s,
        free_heap_bytes,
        sensors_online,
        sensors_error,
    ) = _require(
        data,
        "battery_pct",
        "wifi_rssi_dbm",
        "uptime_s",
        "free_heap_bytes",
        "sensors_online",
        "sensors_error",
    )
    # DB insert 전에 타입 검증 — asyncpg.DataError(영구 실패)가 재시도 큐로
    # 새는 것을 방지하고 InvalidMessage로 미리 차단한다.
    battery_pct = _expect_int(battery_pct, "battery_pct")
    wifi_rssi_dbm = _expect_int(wifi_rssi_dbm, "wifi_rssi_dbm")
    uptime_s = _expect_int(uptime_s, "uptime_s")
    free_heap_bytes = _expect_int(free_heap_bytes, "free_heap_bytes")
    sensors_online = _expect_str_list(sensors_online, "sensors_online")
    sensors_error = _expect_str_list(sensors_error, "sensors_error")

    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            is_new = await _mark_processed(conn, message_id, node_id)
            if not is_new:
                raise DuplicateMessage(message_id)

            await conn.execute(
                """
                INSERT INTO node_status (node_id, battery_pct, wifi_rssi_dbm, uptime_s,
                                          free_heap_bytes, sensors_online, sensors_error,
                                          updated_at, backend_received_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, now())
                ON CONFLICT (node_id) DO UPDATE SET
                    battery_pct          = EXCLUDED.battery_pct,
                    wifi_rssi_dbm        = EXCLUDED.wifi_rssi_dbm,
                    uptime_s             = EXCLUDED.uptime_s,
                    free_heap_bytes      = EXCLUDED.free_heap_bytes,
                    sensors_online       = EXCLUDED.sensors_online,
                    sensors_error        = EXCLUDED.sensors_error,
                    updated_at           = EXCLUDED.updated_at,
                    backend_received_at  = now()
                WHERE node_status.updated_at < EXCLUDED.updated_at
                """,
                node_id,
                battery_pct,
                wifi_rssi_dbm,
                uptime_s,
                free_heap_bytes,
                sensors_online,
                sensors_error,
                sampled_at,
            )

    if _status_callback is not None:
        try:
            await _status_callback(
                node_id,
                {
                    "battery_pct": battery_pct,
                    "wifi_rssi_dbm": wifi_rssi_dbm,
                    "sensors_online": sensors_online,
                    "sensors_error": sensors_error,
                },
                sampled_at,
            )
        except Exception:
            logger.exception("status broadcast failed (node=%s)", node_id)


async def ingest_connection(payload: bytes) -> None:
    """nodes/*/connection (LWT) 처리. 이 페이로드엔 message_id가 없어 dedup 대상이 아니다
    (최신 상태로 upsert만 하면 되므로 중복 수신되어도 안전). 능동적 30초 타임아웃 감지는 #52.

    connection_updated_at 기준으로도 오래된 메시지의 덮어쓰기를 방지한다
    (node_status.updated_at과는 별도 컬럼이므로 독립적으로 가드).

    reason 은 옵셔널 (#96). MQTT LWT offline 메시지가 reason 없이 발행되는 경우가
    있어, 이를 InvalidMessage 로 drop 하면 safety-critical disconnect 이벤트가
    유실된다. 누락/빈 값 시 "unknown" 으로 정규화.
    """
    envelope = _parse_envelope(payload)
    node_id, status, timestamp_raw = _require(envelope, "node_id", "status", "timestamp")
    node_id = _expect_str(node_id, "node_id")
    status = _expect_str(status, "status")
    ts = _parse_ts(timestamp_raw)

    reason_raw = envelope.get("reason")
    reason = _expect_str(reason_raw, "reason") if reason_raw is not None else ""
    reason = reason.strip() or "unknown"

    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO node_status (node_id, connection_status, connection_reason,
                                      connection_updated_at, updated_at, backend_received_at)
            VALUES ($1, $2, $3, $4, '1970-01-01T00:00:00Z', now())
            ON CONFLICT (node_id) DO UPDATE SET
                connection_status     = EXCLUDED.connection_status,
                connection_reason     = EXCLUDED.connection_reason,
                connection_updated_at = EXCLUDED.connection_updated_at,
                backend_received_at   = now()
            WHERE node_status.connection_updated_at IS NULL
               OR node_status.connection_updated_at < EXCLUDED.connection_updated_at
            """,
            node_id,
            status,
            reason,
            ts,
        )
