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
        # 메시지 단위. 지표 단위는 metrics_written 을 본다 (이슈 #117).
        self.messages_processed: int = 0
        self.metrics_written: int = 0
        self.messages_dropped_invalid: int = 0
        self.messages_dropped_duplicate: int = 0
        # 노드별 중복 드롭 분해 (이슈 #104). 재부팅 후 message_id 재사용은
        # 특정 노드의 결함이라 전역 합계만으론 원인 노드를 특정할 수 없다.
        self.messages_dropped_duplicate_by_node: dict[str, int] = {}
        self.alerts_published: int = 0
        self.alerts_resolved: int = 0
        self.mqtt_reconnects: int = 0

    def increment(self, name: str, amount: int = 1) -> None:
        current = getattr(self, name, None)
        if not isinstance(current, int):
            raise AttributeError(f"unknown metric: {name}")
        setattr(self, name, current + amount)

    def record_duplicate_drop(self, node_id: str) -> None:
        """중복 드롭을 전역 + 노드별로 함께 센다 (이슈 #104)."""
        self.messages_dropped_duplicate += 1
        self.messages_dropped_duplicate_by_node[node_id] = (
            self.messages_dropped_duplicate_by_node.get(node_id, 0) + 1
        )

    def snapshot(self) -> dict[str, object]:
        return {
            "messages_processed": self.messages_processed,
            "metrics_written": self.metrics_written,
            "messages_dropped_invalid": self.messages_dropped_invalid,
            "messages_dropped_duplicate": self.messages_dropped_duplicate,
            "messages_dropped_duplicate_by_node": dict(self.messages_dropped_duplicate_by_node),
            "alerts_published": self.alerts_published,
            "alerts_resolved": self.alerts_resolved,
            "mqtt_reconnects": self.mqtt_reconnects,
        }


metrics = _Metrics()
