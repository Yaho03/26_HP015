"""이슈 #109: alert_service.init() 실패가 조용히 삼켜지던 문제 — TDD 테스트."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_alert_service_init_failure_propagates_and_stops_startup(monkeypatch):
    """alert_service.init()이 실패하면 lifespan 자체가 실패해야 한다 (기존엔
    except Exception: pass로 삼켜져서 로그도 없이 서버가 "정상" 기동됐음).
    이후 단계(location_service.init() 등)로 넘어가지 않는지도 함께 확인한다."""
    from app import main as app_main
    from app.services import alert_service, location_service

    async def _boom():
        raise RuntimeError("threshold repository unreachable")
    monkeypatch.setattr(alert_service, "init", _boom)

    location_init_called = False

    def _mark_called():
        nonlocal location_init_called
        location_init_called = True
    monkeypatch.setattr(location_service, "init", _mark_called)

    async def _noop():
        return None
    monkeypatch.setattr(app_main.db, "connect", _noop)
    monkeypatch.setattr(app_main.db, "is_initialized", lambda: False)
    monkeypatch.setattr(app_main.migration_runner, "apply_all", _noop)

    async def _disconnect_noop():
        return None
    monkeypatch.setattr(app_main.db, "disconnect", _disconnect_noop)

    with pytest.raises(RuntimeError, match="threshold repository unreachable"):
        async with app_main.lifespan(app_main.app):
            pass

    assert not location_init_called, "alert_service.init() 실패 후에는 이후 단계로 진행되면 안 됨"
