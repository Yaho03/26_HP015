"""관측성 — 구조화 로깅, 메트릭 카운터 (이슈 #88).

- setup_logging: JSON 포맷 로거 설정 (correlation ID = message_id, MDC 패턴)
- metrics: 싱글톤 카운터 (messages_processed, alerts_published, ...)
"""
from __future__ import annotations

import json
import logging
import sys
from typing import Any


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for attr in ("message_id", "node_id", "metric"):
            v = getattr(record, attr, None)
            if v is not None:
                payload[attr] = v
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)


class _Metrics:
    def __init__(self) -> None:
        self.messages_processed: int = 0
        self.messages_dropped_invalid: int = 0
        self.messages_dropped_duplicate: int = 0
        self.alerts_published: int = 0
        self.alerts_resolved: int = 0
        self.mqtt_reconnects: int = 0

    def increment(self, name: str, amount: int = 1) -> None:
        current = getattr(self, name, None)
        if not isinstance(current, int):
            raise AttributeError(f"unknown metric: {name}")
        setattr(self, name, current + amount)

    def snapshot(self) -> dict[str, int]:
        return {
            "messages_processed": self.messages_processed,
            "messages_dropped_invalid": self.messages_dropped_invalid,
            "messages_dropped_duplicate": self.messages_dropped_duplicate,
            "alerts_published": self.alerts_published,
            "alerts_resolved": self.alerts_resolved,
            "mqtt_reconnects": self.mqtt_reconnects,
        }


metrics = _Metrics()
