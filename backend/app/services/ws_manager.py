"""WebSocket connection manager (이슈 #58).

연결된 대시보드 클라이언트들에게 alert 이벤트/노드 상태 변화를 브로드캐스트한다.
연결 시 현재 활성 alert + 노드 상태 snapshot 을 먼저 전송한다.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Set

from fastapi import WebSocket

logger = logging.getLogger(__name__)

# 브로드캐스트는 인제스트 경로에서 await 된다. 죽었거나 느린 클라이언트 하나가
# 전체를 붙잡으면 센서 수신까지 멈춘다. 로컬 대시보드는 밀리초 단위로 받으므로
# 이 시간을 못 지키면 사실상 죽은 것으로 본다 (이슈 #122).
BROADCAST_TIMEOUT_S = 2.0


class ConnectionManager:
    def __init__(self) -> None:
        self._clients: Set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        """수락 → snapshot 전송 → 등록 순서로 진행한다.

        등록을 마지막에 하는 이유는, snapshot 전송이 실패한 소켓이 목록에 남으면
        이후 모든 브로드캐스트가 그 소켓에 대해 실패하기 때문이다.
        """
        await ws.accept()
        await self._send_snapshot(ws)
        self._clients.add(ws)
        logger.info("ws client connected (total=%d)", len(self._clients))

    def disconnect(self, ws: WebSocket) -> None:
        """여러 번 불려도 안전하다. 라우터가 finally 에서 호출한다."""
        if ws not in self._clients:
            return
        self._clients.discard(ws)
        logger.info("ws client disconnected (total=%d)", len(self._clients))

    def client_count(self) -> int:
        return len(self._clients)

    async def _send_snapshot(self, ws: WebSocket) -> None:
        """새로 연결된 클라이언트에게 현재 상태를 즉시 전송 — 경보 발생 전까지
        화면이 비어있거나, 새로고침 시 상태가 초기화되는 문제 방지 (이슈 #106).

        DB 조회 실패(풀 미초기화 등) 시에도 연결 자체는 끊지 않고 빈 snapshot으로
        폴백한다 — 초기 상태 표시는 best-effort이고, 이후 실시간 브로드캐스트로
        채워지기 때문이다.
        """
        nodes: dict = {}
        alerts: dict = {}
        try:
            from app.db import get_pool

            pool = get_pool()
            async with pool.acquire() as conn:
                node_rows = await conn.fetch("SELECT * FROM node_status")
                for row in node_rows:
                    nodes[row["node_id"]] = {
                        "battery_pct": row["battery_pct"],
                        "wifi_rssi_dbm": row["wifi_rssi_dbm"],
                        "connection_status": row["connection_status"],
                        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
                    }

                # node_status보다 먼저(또는 그것 없이) gas/env 리딩만 온 노드도 있으므로
                # (예: status 메시지 도착 전) sensor_data의 (node_id, metric)별 최신값도
                # 합쳐서 복원한다 — 안 그러면 새로고침 시 그 노드 카드 자체가 사라진다.
                reading_rows = await conn.fetch(
                    """
                    SELECT DISTINCT ON (node_id, metric) node_id, metric, value, time
                    FROM sensor_data
                    ORDER BY node_id, metric, time DESC
                    """
                )
                for row in reading_rows:
                    node_id = row["node_id"]
                    node = nodes.setdefault(node_id, {})
                    readings = node.setdefault("readings", {})
                    readings[row["metric"]] = {
                        "metric": row["metric"],
                        "value": row["value"],
                        "sampled_at": row["time"].isoformat(),
                    }

                alert_rows = await conn.fetch(
                    """
                    SELECT DISTINCT ON (source_node_id, alert_key) *
                    FROM alert_events
                    ORDER BY source_node_id, alert_key, published_at DESC
                    """
                )
                for row in alert_rows:
                    if row["status"] != "active":
                        continue
                    # node_id:alert_key 복합 키 — 코드리뷰 반영. alert_key만 쓰면
                    # sensor-01/sensor-02가 둘 다 co2_ppm active일 때 하나가
                    # 덮어써진다 (프론트 deriveAlertKey와 동일 규칙으로 통일).
                    key = f'{row["source_node_id"]}:{row["alert_key"]}'
                    alerts[key] = {
                        "node_id": row["source_node_id"],
                        "level": row["level"],
                        "trigger_value": row["trigger_value"],
                        "threshold": row["threshold"],
                        "activated_at": row["activated_at"].isoformat() if row["activated_at"] else None,
                    }
        except Exception:
            logger.exception("snapshot query failed, sending empty snapshot")
            nodes, alerts = {}, {}

        await ws.send_json({"type": "snapshot", "nodes": nodes, "alerts": alerts})

    async def broadcast(self, message: dict) -> None:
        """모든 클라이언트에 동시에 보낸다.

        예전에는 순차 await 라 앞의 클라이언트가 느리면 뒤가 그만큼 밀렸고,
        타임아웃이 없어 응답하지 않는 소켓 하나가 무한정 붙잡을 수 있었다.
        """
        clients = list(self._clients)
        if not clients:
            return

        async def send(ws: WebSocket) -> bool:
            try:
                await asyncio.wait_for(ws.send_json(message), BROADCAST_TIMEOUT_S)
                return True
            except asyncio.TimeoutError:
                logger.warning("ws send timed out after %.1fs, dropping client", BROADCAST_TIMEOUT_S)
                return False
            except Exception:
                return False

        results = await asyncio.gather(
            *(send(ws) for ws in clients), return_exceptions=True
        )
        for ws, ok in zip(clients, results):
            if ok is not True:
                self._clients.discard(ws)


manager = ConnectionManager()
