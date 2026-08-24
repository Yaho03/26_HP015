import json
import logging
from datetime import datetime
from typing import Any, List, Optional, Tuple

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
_ranging_callback = None
_reading_callback = None
_status_callback = None
_connection_recovery_callback = None
_exposure_callback = None


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


def set_exposure_callback(callback) -> None:
    """누적 노출량 적산 콜백 주입 (FR-701). ingest_telemetry 가 각 metric 저장 후
    호출한다. exposure_service.init() 에서 등록한다.

    reading_callback 을 나눠 쓰지 않고 슬롯을 따로 둔 이유는 두 가지다. 하나는
    이미 sensor_broadcast 가 그 슬롯을 쓰고 있어서(단일 슬롯) 덮어쓰면 대시보드
    실시간 값이 끊긴다. 다른 하나는 실패 격리다 — 적산이 예외를 내도 브로드캐스트는
    계속 나가야 하고, 그 반대도 마찬가지다."""
    global _exposure_callback
    _exposure_callback = callback


def set_status_callback(callback) -> None:
    """node_status 브로드캐스트 콜백 주입. ingest_status 가 저장 후 호출한다.
    sensor_broadcast.init() 에서 등록한다 (#106)."""
    global _status_callback
    _status_callback = callback


def set_ranging_callback(callback) -> None:
    """UWB 거리 콜백 주입. ingest_ranging 이 호출한다 (#121).
    uwb_service.init() 에서 등록한다."""
    global _ranging_callback
    _ranging_callback = callback

def set_location_callback(callback) -> None:
    """위치 필터링 콜백 주입. ingest_telemetry 가 location metric(x_m/y_m/z_m) 을
    만나면 호출한다 (#70). location_service.init() 에서 등록한다."""
    global _location_callback
    _location_callback = callback


def set_connection_recovery_callback(callback) -> None:
    """노드 offline→online 복귀 콜백 주입. ingest_connection 이 이전 상태가
    offline이었던 노드로부터 online 메시지를 받으면 호출한다 (이슈 #111).
    connection_monitor.init() 에서 등록한다."""
    global _connection_recovery_callback
    _connection_recovery_callback = callback


class DuplicateMessage(Exception):
    """이미 처리한 message_id (FR-101 dedup). 재시도 대상 아님 — 정상 스킵.

    node_id를 함께 싣는다 (이슈 #104) — 재부팅 후 message_id 재사용 같은
    노드 국소 결함은 전역 카운터만으로는 어느 노드인지 알 수 없다."""

    def __init__(self, message_id: str, node_id: str) -> None:
        super().__init__(message_id)
        self.node_id = node_id


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


def _normalize_source_mode(value: Any) -> Optional[str]:
    """envelope 의 source_mode 를 계약값('live'/'simulation')으로 정규화한다.

    확신할 수 없으면 None 이다. 누락/오타/타입 이상을 'live' 로 메우면 주입값이
    정상 실측으로 둔갑해 AI 학습셋을 오염시킨다 (012 마이그레이션 주석 참조).
    여기서 InvalidMessage 를 던지지 않는 이유는, 출처 한 칸 때문에 메시지 전체를
    drop 하면 안전 필수 경보 판정까지 함께 사라지기 때문이다.
    """
    if value in ("live", "simulation"):
        return value
    return None


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
    source_mode = _normalize_source_mode(envelope.get("source_mode"))

    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            is_new = await _mark_processed(conn, message_id, node_id)
            if not is_new:
                raise DuplicateMessage(message_id, node_id)

            extracted = _extract_metrics(data)
            if extracted:
                await conn.executemany(
                    """
                    INSERT INTO sensor_data (time, node_id, metric, value, message_id, source_mode)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    ON CONFLICT DO NOTHING
                    """,
                    [
                        (sampled_at, node_id, metric, value, message_id, source_mode)
                        for metric, value in extracted
                    ],
                )

            # 메시지 1건은 1 로 센다. 예전에는 이 증가가 metric 루프 안에 있어
            # 지표 4개짜리 가스 메시지가 4건으로 집계됐다 (이슈 #117).
            # 지표 단위 집계가 필요하면 metrics_written 을 본다.
            metrics.increment("messages_processed")
            if extracted:
                metrics.increment("metrics_written", len(extracted))

    # 경보 판정·브로드캐스트·적산 콜백은 트랜잭션 **밖에서** 실행한다 (이슈 #237).
    # 트랜잭션 안에서 await 하면 WS broadcast 타임아웃(2초)만큼 커넥션을 붙잡아
    # 풀을 고갈시킨다. 저장(dedup+INSERT)만 원자적이면 되고, 파생 처리는 커밋
    # 후에 순서를 유지하며 흐른다. 커밋 후 콜백이 실패해도 저장은 이미 확정 —
    # 경보 엔진은 상태 기반이라 다음 샘플(1초 후)이 같은 판정을 다시 한다.
    for metric, value in extracted:
        if _alert_callback is not None:
            try:
                await _alert_callback(node_id, metric, value, sampled_at)
            except Exception:
                # 순간값 경보는 이 샘플을 놓치면 끝이므로 (#236) 실패를 세어
                # /api/metrics 로 노출한다 — 로그만으로는 지속적 실패를 못 본다.
                metrics.increment("alert_callback_failures")
                logger.exception(
                    "alert evaluation failed (node=%s metric=%s value=%s)",
                    node_id, metric, value,
                )
        if _reading_callback is not None:
            try:
                await _reading_callback(node_id, metric, value, sampled_at)
            except Exception:
                metrics.increment("broadcast_callback_failures")
                logger.exception(
                    "reading broadcast failed (node=%s metric=%s value=%s)",
                    node_id, metric, value,
                )
        if _exposure_callback is not None:
            try:
                await _exposure_callback(node_id, metric, value, sampled_at)
            except Exception:
                # 적산 실패가 경보 판정과 브로드캐스트를 막으면 안 된다.
                # 노출량은 누적 지표라 한 샘플을 놓쳐도 다음 샘플에서
                # 이어지지만, 순간값 경보는 그 샘플을 놓치면 끝이다.
                metrics.increment("exposure_callback_failures")
                logger.exception(
                    "exposure accumulation failed (node=%s metric=%s value=%s)",
                    node_id, metric, value,
                )

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
                raise DuplicateMessage(message_id, node_id)

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

    connection_updated_at 기준으로 오래된 메시지의 덮어쓰기를 방지하되, status가
    "offline"이면 이 가드를 건너뛰고 무조건 반영한다 (이슈 #107 리뷰 3번).
    MQTT LWT payload는 브로커에 CONNECT 시점에 등록해두고 클라이언트가 죽은 뒤
    브로커가 그 "고정된" bytes를 그대로 발행하는 구조라, LWT의 timestamp는 항상
    "연결했던 시각"이다. 반면 연결 직후 보통 status=online 메시지가 (LWT보다 늦은)
    현재 시각으로 connection_updated_at을 먼저 갱신해두므로, 나중에 노드가 실제로
    죽어 브로커가 LWT를 발행해도 그 timestamp(연결 시각)가 이미 저장된 online의
    timestamp보다 항상 과거라 가드에 막혀 offline 전환이 영구히 반영되지 않았다.
    offline은 safety-critical(연결 끊김 감지)이라 timestamp 신뢰성보다 반영 자체가
    우선이므로 무조건 통과시킨다.

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
        # 조회와 반영을 한 트랜잭션에 묶고 RETURNING 으로 "실제로 반영됐는지"까지
        # 받는다 (2026-08-19 하드웨어 세션 보강). applied 가 None 이면 stale
        # timestamp 가드에 맡겨 UPSERT 자체가 안 된 것이므로 복귀 해제도 하지 않는다.
        async with conn.transaction():
            previous_status = await conn.fetchval(
                "SELECT connection_status FROM node_status WHERE node_id = $1", node_id
            )
            applied = await conn.fetchval(
                """
                INSERT INTO node_status (node_id, connection_status, connection_reason,
                                          connection_updated_at, updated_at, backend_received_at)
                VALUES ($1, $2, $3, $4, '1970-01-01T00:00:00Z', now())
                ON CONFLICT (node_id) DO UPDATE SET
                    connection_status     = EXCLUDED.connection_status,
                    connection_reason     = EXCLUDED.connection_reason,
                    connection_updated_at = EXCLUDED.connection_updated_at,
                    backend_received_at   = now()
                WHERE EXCLUDED.connection_status = 'offline'
                   OR node_status.connection_updated_at IS NULL
                   OR node_status.connection_updated_at < EXCLUDED.connection_updated_at
                RETURNING connection_status
                """,
                node_id,
                status,
                reason,
                ts,
            )

    # offline→online 복귀 감지 (이슈 #111). connection_monitor의 30초 타임아웃이
    # connection_lost L3 경보를 발생시켜도 그걸 NORMAL로 되돌리는 코드가 없어서,
    # 노드가 실제로 복귀해도 경보가 active_alert_ids에 영구 잔류하고 retain
    # 메시지가 고착되던 문제였다. 재연결 시 main.cpp가 항상 이 토픽으로 online을
    # 보내므로(연결 직후 connectMqtt()), 여기가 복귀를 감지하는 자연스러운 지점이다.
    # 처음 보는 노드는 previous_status 가 None 이라 해제 이벤트를 만들지 않는다.
    if (
        status == "online"
        and applied is not None
        and previous_status == "offline"
        and _connection_recovery_callback is not None
    ):
        try:
            await _connection_recovery_callback(node_id)
        except Exception:
            logger.exception("connection recovery callback failed (node=%s)", node_id)


async def ingest_ranging(payload: bytes) -> None:
    """wearable/*/ranging (UWB 앵커 거리) 처리 — 이슈 #121.

    거리 자체는 최종 관측값이 아니라 좌표를 얻기 위한 중간 데이터라 DB 에 넣지
    않는다. 저장되는 것은 삼변측량으로 나온 위치다 (기존 location 경로와 동일).
    """
    envelope = _parse_envelope(payload)
    node_id, sampled_at_raw = _require(envelope, "node_id", "sampled_at")
    node_id = _expect_str(node_id, "node_id")
    sampled_at = _parse_ts(sampled_at_raw)

    data = envelope.get("data")
    if not isinstance(data, dict):
        raise InvalidMessage("ranging payload requires object 'data'")
    ranges = data.get("ranges")
    if not isinstance(ranges, list):
        raise InvalidMessage("ranging data requires list 'ranges'")

    metrics.increment("messages_processed")
    if _ranging_callback is None:
        return
    try:
        await _ranging_callback(node_id, ranges, sampled_at)
    except Exception:
        logger.exception("ranging callback failed (node=%s)", node_id)
