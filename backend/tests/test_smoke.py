"""백엔드 테스트 인프라 smoke test (이슈: TDD 인프라 구축).

목적: pytest + asyncio 설정이 정상 동작하는지, app 패키지 import 가 가능한지 검증.
이후 모든 백엔드 이슈에서 이 인프라를 기반으로 TDD 진행한다.
"""
import pytest


def test_app_importable():
    """app.main 모듈이 정상적으로 import 되어야 한다."""
    from app.main import app
    assert app.title == "26_HP015 Backend"


def test_settings_loaded():
    """config.Settings 가 기본값으로 로드되어야 한다."""
    from app.config import settings
    assert settings.mqtt_host == "localhost"
    assert settings.mqtt_port == 1883


@pytest.mark.asyncio
async def test_asyncio_mode_works():
    """asyncio_mode=auto 설정이 동작하는지 검증."""
    import asyncio
    await asyncio.sleep(0)
    assert True
