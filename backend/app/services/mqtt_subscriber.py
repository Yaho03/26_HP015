import asyncio
import logging
from collections import deque
from typing import Deque, Optional, Tuple

import paho.mqtt.client as mqtt

from app.config import settings
from app.observability import metrics
from app.services import ingest

logger = logging.getLogger(__name__)

# 8개 토픽 패턴 (04_DATA_CONTRACT.md 3.1). '+'는 node_id 자리.
# ranging 은 UWB 거리 → 백엔드 삼변측량 경로 (#121, ADR-006).
_TOPIC_HANDLERS = {
    "sensors/+/gas": ingest.ingest_telemetry,
    "sensors/+/env": ingest.ingest_telemetry,
    "sensors/+/status": ingest.ingest_status,
    "wearable/+/location": ingest.ingest_telemetry,
    "wearable/+/ranging": ingest.ingest_ranging,
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
# 구독까지 성공했는지. 클라이언트 객체는 인증이 거부돼도 남으므로 객체 존재만으로는
# 정상 여부를 알 수 없다 (이슈 #119, #115 연쇄).
_subscribed: bool = False
_loop: Optional[asyncio.AbstractEventLoop] = None
_retry_task: Optional[asyncio.Task] = None


def get_client() -> Optional[mqtt.Client]:
    """외부(alert_publisher 등)가 publish 하기 위해 client 참조를 가져간다."""
    return _client


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
        metrics.increment("messages_dropped_duplicate")
    except ingest.InvalidMessage as e:
        _invalid_dropped_count += 1
        metrics.increment("messages_dropped_invalid")
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
    global _subscribed
    if reason_code.is_failure:
        # 인증 거부가 여기로 온다. 예전에는 로그만 남기고 끝나서 /health 가 계속
        # ok 를 반환했고, 백엔드는 아무것도 구독하지 않은 채 정상인 척했다.
        _subscribed = False
        logger.error("MQTT connect failed: %s", reason_code)
        return
    for pattern in _TOPIC_HANDLERS:
        qos = _QOS.get(pattern, 1)
        client.subscribe(pattern, qos=qos)
    _subscribed = True
    logger.info("MQTT connected, subscribed to %d topic patterns", len(_TOPIC_HANDLERS))


def _on_disconnect(client, userdata, flags=None, reason_code=None, properties=None):
    """끊기면 구독 상태를 내리고 재연결 횟수를 센다.

    paho 가 자동 재연결하면 _on_connect 가 다시 불려 _subscribed 가 복구된다.
    """
    global _subscribed
    _subscribed = False
    metrics.increment("mqtt_reconnects")
    logger.warning("MQTT disconnected: %s", reason_code)


def is_healthy() -> bool:
    """실제로 메시지를 받을 수 있는 상태인가.

    소켓이 붙어 있고(is_connected) 토픽 구독까지 끝났을 때만 True.
    """
    return _client is not None and _client.is_connected() and _subscribed


def _on_message(client: mqtt.Client, userdata, msg: mqtt.MQTTMessage):
    if _loop is not None and _loop.is_running():
        try:
            asyncio.run_coroutine_threadsafe(_handle_message(msg.topic, msg.payload), _loop)
        except RuntimeError:
            logger.debug("event loop closed, dropping late MQTT message (topic=%s)", msg.topic)


async def start() -> None:
    global _client, _loop, _retry_task
    _loop = asyncio.get_running_loop()

    _client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    if settings.mqtt_username:
        _client.username_pw_set(settings.mqtt_username, settings.mqtt_password)
    _client.on_connect = _on_connect
    _client.on_disconnect = _on_disconnect
    _client.on_message = _on_message
    _client.connect(settings.mqtt_host, settings.mqtt_port)
    _client.loop_start()

    _retry_task = asyncio.create_task(_retry_loop())


async def stop() -> None:
    global _client, _retry_task
    if _retry_task is not None:
        _retry_task.cancel()
        try:
            await _retry_task
        except asyncio.CancelledError:
            pass
        _retry_task = None
    if _client is not None:
        _client.loop_stop()
        _client.disconnect()
        _client = None
    globals()["_subscribed"] = False
