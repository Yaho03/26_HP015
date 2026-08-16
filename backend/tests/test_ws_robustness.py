"""WebSocket 연결 관리 견고성 (이슈 #122).

브로드캐스트는 인제스트 경로에서 await 된다. 죽었거나 느린 클라이언트 하나가
전체를 막으면 센서 수신까지 지연된다.

전역 싱글턴(ws_manager.manager)을 쓰지 않고 매번 새 인스턴스를 만든다 — 테스트가
서로의 클라이언트 목록을 오염시키지 않게.
"""
from __future__ import annotations

import asyncio

import pytest

from app.services.ws_manager import BROADCAST_TIMEOUT_S, ConnectionManager


class FakeWS:
    """send_json 동작을 조절할 수 있는 가짜 소켓."""

    def __init__(self, *, fail: bool = False, delay: float = 0.0):
        self.fail = fail
        self.delay = delay
        self.sent: list[dict] = []
        self.accepted = False

    async def accept(self):
        self.accepted = True

    async def send_json(self, message: dict):
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail:
            raise RuntimeError("소켓이 죽음")
        self.sent.append(message)


@pytest.fixture
def mgr(monkeypatch) -> ConnectionManager:
    m = ConnectionManager()
    # snapshot 은 DB 를 타므로 여기서는 비운다. 실패 경로는 별도 테스트에서 본다.
    async def empty_snapshot(ws):
        await ws.send_json({"type": "snapshot", "nodes": {}, "alerts": {}})

    monkeypatch.setattr(m, "_send_snapshot", empty_snapshot)
    return m


async def connect_healthy(mgr: ConnectionManager, **degrade) -> FakeWS:
    """정상 연결한 뒤 상태를 나쁘게 만든다.

    연결 시점부터 실패하는 소켓은 등록 자체가 되지 않으므로(설계상 옳다),
    "붙을 때는 멀쩡했다가 나중에 죽는" 실제 상황을 재현한다.
    """
    ws = FakeWS()
    await mgr.connect(ws)
    ws.sent.clear()
    for key, value in degrade.items():
        setattr(ws, key, value)
    return ws


class TestBroadcastIsolation:
    @pytest.mark.asyncio
    async def test_dead_client_does_not_block_others(self, mgr):
        """★ 죽은 클라이언트가 있어도 나머지는 모두 받아야 한다."""
        good1 = await connect_healthy(mgr)
        dead = await connect_healthy(mgr, fail=True)
        good2 = await connect_healthy(mgr)

        await mgr.broadcast({"type": "alert"})

        assert {"type": "alert"} in good1.sent
        assert {"type": "alert"} in good2.sent

    @pytest.mark.asyncio
    async def test_dead_client_is_removed(self, mgr):
        await connect_healthy(mgr)
        await connect_healthy(mgr, fail=True)
        await mgr.broadcast({"type": "alert"})
        assert mgr.client_count() == 1

    @pytest.mark.asyncio
    async def test_slow_client_does_not_stall_broadcast(self, mgr):
        """블로킹하는 클라이언트가 브로드캐스트를 무한정 붙잡으면 안 된다.

        브로드캐스트는 인제스트 경로에서 await 되므로, 여기서 막히면 센서 수신이
        멈춘다.
        """
        await connect_healthy(mgr, delay=BROADCAST_TIMEOUT_S + 5)
        fast = await connect_healthy(mgr)

        started = asyncio.get_event_loop().time()
        await asyncio.wait_for(
            mgr.broadcast({"type": "alert"}), timeout=BROADCAST_TIMEOUT_S + 2
        )
        elapsed = asyncio.get_event_loop().time() - started

        assert elapsed < BROADCAST_TIMEOUT_S + 1, f"{elapsed:.1f}s 걸림"
        assert {"type": "alert"} in fast.sent

    @pytest.mark.asyncio
    async def test_timed_out_client_is_dropped(self, mgr):
        await connect_healthy(mgr, delay=BROADCAST_TIMEOUT_S + 5)
        await mgr.broadcast({"type": "alert"})
        assert mgr.client_count() == 0

    @pytest.mark.asyncio
    async def test_broadcast_with_no_clients_is_safe(self, mgr):
        await mgr.broadcast({"type": "alert"})  # 예외 없이 끝나야 한다

    @pytest.mark.asyncio
    async def test_timeout_is_short_enough_to_not_stall_ingest(self):
        """인제스트가 초당 여러 건을 처리하므로 타임아웃이 길면 밀린다."""
        assert 0 < BROADCAST_TIMEOUT_S <= 5


class TestConnectRegistration:
    @pytest.mark.asyncio
    async def test_successful_connect_registers(self, mgr):
        ws = FakeWS()
        await mgr.connect(ws)
        assert ws.accepted is True
        assert mgr.client_count() == 1

    @pytest.mark.asyncio
    async def test_snapshot_failure_does_not_leave_half_registered(self, monkeypatch):
        """snapshot 전송이 실패한 소켓을 목록에 남기면, 이후 모든 브로드캐스트가
        그 소켓에 대해 실패한다."""
        m = ConnectionManager()

        async def boom(ws):
            raise RuntimeError("snapshot 전송 실패")

        monkeypatch.setattr(m, "_send_snapshot", boom)
        ws = FakeWS()
        with pytest.raises(RuntimeError):
            await m.connect(ws)
        assert m.client_count() == 0


class TestDisconnect:
    @pytest.mark.asyncio
    async def test_disconnect_removes_client(self, mgr):
        ws = FakeWS()
        await mgr.connect(ws)
        mgr.disconnect(ws)
        assert mgr.client_count() == 0

    @pytest.mark.asyncio
    async def test_disconnect_is_idempotent(self, mgr):
        ws = FakeWS()
        await mgr.connect(ws)
        mgr.disconnect(ws)
        mgr.disconnect(ws)  # 두 번 불려도 안전해야 한다 (finally + 예외 경로)
        assert mgr.client_count() == 0


def test_manager_exposes_client_count():
    """테스트가 _clients 내부에 손대지 않게 한다."""
    assert ConnectionManager().client_count() == 0
