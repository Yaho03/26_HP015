import asyncio
import logging
from collections import deque
from typing import Deque, Optional, Tuple

import paho.mqtt.client as mqtt

from app.config import settings
from app.services import ingest

logger = logging.getLogger(__name__)

# 7개 토픽 패턴 (04_DATA_CONTRACT.md 3.1). '+'는 node_id 자리.
_TOPIC_HANDLERS = {
    "sensors/+/gas": ingest.ingest_telemetry,
    "sensors/+/env": ingest.ingest_telemetry,
    "sensors/+/status": ingest.ingest_status,
    "wearable/+/location": ingest.ingest_telemetry,
    "wearable/+/imu": ingest.ingest_telemetry,
    "wearable/+/vital": ingest.ingest_telemetry,
    "nodes/+/connection": ingest.ingest_connection,
}

# QoS 정책 (04_DATA_CONTRACT.md 3.2): IMU만 0(고주기, 손실 허용), 나머지 1.
_QOS = {"wearable/+/imu": 0}

# DB 장애 시 큐잉 (완료조건 6). 재시작하면 사라지는 메모리 큐 — MVP 단계 한도.
_MAX_QUEUE = 500
_retry_queue: Deque[Tuple[str, bytes]] = deque(maxlen=_MAX_QUEUE)

# 관측성 카운터 (리뷰 반영): 유실/드롭 상황을 로그+숫자로 남긴다.
_overflow_dropped_count = 0
_invalid_dropped_count = 0

_client: Optional[mqtt.Client] = None
_loop: Optional[asyncio.AbstractEventLoop] = None
_retry_task: Optional[asyncio.Task] = None


def _find_handler(topic: str):
    for pattern, handler in _TOPIC_HANDLERS.items():
        if mqtt.topic_matches_sub(pattern, topic):
            return handler
    return None


def _enqueue_retry(topic: str, payload: bytes) -> None:
    global _overflow_dropped_count
    if len(_retry_queue) >= _retry_queue.maxlen:
        _overflow_dropped_count += 1
        logger.warning(
            "retry queue full (maxlen=%d) — oldest queued message will be evicted "
            "(topic=%s, total overflow-dropped=%d)",
            _retry_queue.maxlen,
            topic,
            _overflow_dropped_count,
        )
    _retry_queue.append((topic, payload))


async def _handle_message(topic: str, payload: bytes) -> None:
    global _invalid_dropped_count
    handler = _find_handler(topic)
    if handler is None:
        logger.warning("no handler matched for topic %s", topic)
        return
    try:
        await handler(payload)
    except ingest.DuplicateMessage:
        logger.debug("duplicate message skipped (topic=%s)", topic)
    except ingest.InvalidMessage as e:
        _invalid_dropped_count += 1
        logger.error(
            "invalid message dropped (topic=%s): %s (total invalid-dropped=%d)",
            topic, e, _invalid_dropped_count,
        )
    except Exception:
        logger.exception("ingest failed (transient), queued for retry (topic=%s)", topic)
        _enqueue_retry(topic, payload)


async def _retry_loop() -> None:
    """5초마다 큐를 비우려 시도. 일시적 실패(Exception)면 그 지점에서 멈추고 다음 tick에
    재시도(순서 보존). InvalidMessage(영구 실패)는 막지 않고 즉시 버리고 다음 항목으로 진행 —
    poison message 하나가 뒤 항목들의 처리를 막지 않도록 한다."""
    global _invalid_dropped_count
    while True:
        await asyncio.sleep(5)
        while _retry_queue:
            topic, payload = _retry_queue[0]
            handler = _find_handler(topic)
            if handler is None:
                _retry_queue.popleft()
                continue
            try:
                await handler(payload)
            except ingest.DuplicateMessage:
                pass
            except ingest.InvalidMessage as e:
                _invalid_dropped_count += 1
                logger.error(
                    "invalid message dropped during retry (topic=%s): %s (total invalid-dropped=%d)",
                    topic, e, _invalid_dropped_count,
                )
            except Exception:
                logger.warning("retry still failing for topic %s, will retry later", topic)
                break
            _retry_queue.popleft()


def _on_connect(client: mqtt.Client, userdata, flags, reason_code, properties=None):
    if reason_code.is_failure:
        logger.error("MQTT connect failed: %s", reason_code)
        return
    for pattern in _TOPIC_HANDLERS:
        qos = _QOS.get(pattern, 1)
        client.subscribe(pattern, qos=qos)
    logger.info("MQTT connected, subscribed to %d topic patterns", len(_TOPIC_HANDLERS))


def _on_message(client: mqtt.Client, userdata, msg: mqtt.MQTTMessage):
    if _loop is not None:
        asyncio.run_coroutine_threadsafe(_handle_message(msg.topic, msg.payload), _loop)


async def start() -> None:
    global _client, _loop, _retry_task
    _loop = asyncio.get_running_loop()

    _client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    if settings.mqtt_username:
        _client.username_pw_set(settings.mqtt_username, settings.mqtt_password)
    _client.on_connect = _on_connect
    _client.on_message = _on_message
    _client.connect(settings.mqtt_host, settings.mqtt_port)
    _client.loop_start()

    _retry_task = asyncio.create_task(_retry_loop())


async def stop() -> None:
    global _client, _retry_task
    if _retry_task is not None:
        _retry_task.cancel()
        _retry_task = None
    if _client is not None:
        _client.loop_stop()
        _client.disconnect()
        _client = None
