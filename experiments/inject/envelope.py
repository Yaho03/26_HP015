"""04_DATA_CONTRACT 준수 envelope 생성 헬퍼 (이슈 #82).

telemetry envelope (sensors/wearable 토픽) 과 connection envelope (nodes 토픽) 구분.
simulation 메타데이터(run_id, scenario_id) 포함 옵션.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ulid import ULID

SCHEMA_VERSION = "1.1"


def _iso(ts: datetime) -> str:
    if ts.tzinfo is None:
        return ts.isoformat() + "Z"
    return ts.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def build_envelope(
    *,
    node_id: str,
    data: dict[str, Any],
    sampled_at: datetime,
    source_mode: str = "live",
    run_id: str | None = None,
    scenario_id: str | None = None,
    sequence: int | None = None,
    quality: dict[str, Any] | None = None,
) -> dict[str, Any]:
    envelope: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "message_id": str(ULID()),
        "node_id": node_id,
        "sampled_at": _iso(sampled_at),
        "data": data,
        "source_mode": source_mode,
        "simulation": None,
    }
    if sequence is not None:
        envelope["sequence"] = sequence
    if quality is not None:
        envelope["quality"] = quality
    if source_mode == "simulation":
        envelope["simulation"] = {
            "run_id": run_id or "",
            "scenario_id": scenario_id or "",
        }
    return envelope


def build_connection_envelope(
    *,
    node_id: str,
    status: str,
    reason: str,
    timestamp: datetime,
    boot_id: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "node_id": node_id,
        "status": status,
        "reason": reason,
        "boot_id": boot_id or str(ULID()),
        "timestamp": _iso(timestamp),
    }
