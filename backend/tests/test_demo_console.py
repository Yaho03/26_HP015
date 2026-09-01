from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import demo_console
from tests.conftest import install_admin_auth


def test_demo_console_is_an_operator_page():
    app = FastAPI()
    app.include_router(demo_console.router)
    app.include_router(demo_console.control_router)
    install_admin_auth(app)
    client = TestClient(app)
    entry = client.get("/", follow_redirects=False)
    assert entry.status_code == 307
    assert entry.headers["location"] == "/login"
    assert client.get("/login").status_code == 200
    response = client.get("/control")
    assert response.status_code == 200
    assert "데모 제어실" in response.text
    assert "전체 자동 시연 시작" in response.text
    assert "2분 영상 촬영 시나리오" in response.text
    assert "촬영 대기 상태 시작" in response.text
    assert "CO₂ 단계별 위험 경보" in response.text
    assert "H₂S 누적 노출 위험" in response.text
    assert "비상 탈출 경로" in response.text
    assert "/api/demo/playlist/run" not in response.text  # 경로는 함수 조합으로 유지
