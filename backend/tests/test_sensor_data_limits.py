"""sensor-data 조회 입력 검증과 결과 상한 (이슈 #120).

raw sensor_data 는 노드·지표당 초당 1건이 쌓인다. 보존 30일이면 260만 행이라
기간만 넓게 주면 전량이 메모리로 올라온다. CSV 는 그걸 문자열로 한 번 더 복사했다.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import sensor_data


@pytest.fixture
def client(monkeypatch) -> TestClient:
    """레포지토리를 가로채 라우터의 입력 검증만 본다."""
    captured: dict = {}

    async def fake_query(**kwargs):
        captured.update(kwargs)
        return [{"time": "2026-08-16T00:00:00+00:00", "value": 1.0}]

    monkeypatch.setattr(sensor_data.sensor_data_repository, "query", fake_query)
    app = FastAPI()
    app.include_router(sensor_data.router)
    from tests.conftest import install_admin_auth

    install_admin_auth(app)
    c = TestClient(app)
    c.captured = captured  # type: ignore[attr-defined]
    return c


BASE = {
    "node_id": "sensor-01",
    "metric": "co2_ppm",
    "start": "2026-08-16T00:00:00Z",
    "end": "2026-08-16T01:00:00Z",
}


class TestInputValidation:
    def test_valid_request_succeeds(self, client):
        assert client.get("/api/sensor-data", params=BASE).status_code == 200

    @pytest.mark.parametrize("bad", ["어제", "2026-13-45", "", "2026/08/16"])
    def test_malformed_datetime_is_422_not_500(self, client, bad):
        """사용자 입력 오류를 서버 오류로 보고하면 안 된다."""
        resp = client.get("/api/sensor-data", params={**BASE, "start": bad})
        assert resp.status_code == 422, f"{bad!r} → {resp.status_code}"

    def test_end_before_start_is_rejected(self, client):
        resp = client.get(
            "/api/sensor-data",
            params={**BASE, "start": "2026-08-16T05:00:00Z", "end": "2026-08-16T01:00:00Z"},
        )
        assert resp.status_code == 422

    def test_range_beyond_retention_is_rejected(self, client):
        """보존 기간(30일)을 넘겨 조회할 이유가 없다. 데이터도 없다."""
        resp = client.get(
            "/api/sensor-data",
            params={**BASE, "start": "2026-01-01T00:00:00Z", "end": "2026-08-16T00:00:00Z"},
        )
        assert resp.status_code == 422

    def test_range_at_limit_is_allowed(self, client):
        resp = client.get(
            "/api/sensor-data",
            params={**BASE, "start": "2026-07-17T00:00:00Z", "end": "2026-08-16T00:00:00Z"},
        )
        assert resp.status_code == 200


class TestResultLimit:
    def test_limit_defaults_to_bounded_value(self, client):
        client.get("/api/sensor-data", params=BASE)
        assert client.captured["limit"] == sensor_data.DEFAULT_LIMIT

    def test_limit_is_passed_through(self, client):
        client.get("/api/sensor-data", params={**BASE, "limit": 50})
        assert client.captured["limit"] == 50

    def test_limit_above_max_is_rejected(self, client):
        resp = client.get(
            "/api/sensor-data", params={**BASE, "limit": sensor_data.MAX_LIMIT + 1}
        )
        assert resp.status_code == 422

    def test_zero_or_negative_limit_is_rejected(self, client):
        assert client.get("/api/sensor-data", params={**BASE, "limit": 0}).status_code == 422
        assert client.get("/api/sensor-data", params={**BASE, "limit": -5}).status_code == 422

    def test_default_limit_is_actually_bounded(self):
        """상한이 없으면 이 이슈의 OOM 위험이 그대로 남는다."""
        assert 0 < sensor_data.DEFAULT_LIMIT <= sensor_data.MAX_LIMIT
        assert sensor_data.MAX_LIMIT <= 200_000


class TestExport:
    def test_export_streams_csv(self, client):
        resp = client.get("/api/sensor-data/export", params=BASE)
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/csv")
        assert "attachment" in resp.headers["content-disposition"]

    def test_export_body_has_header_and_rows(self, client):
        body = client.get("/api/sensor-data/export", params=BASE).text
        lines = [ln for ln in body.splitlines() if ln]
        assert lines[0] == "time,value"
        assert lines[1].startswith("2026-08-16T00:00:00")

    def test_export_applies_same_validation(self, client):
        resp = client.get("/api/sensor-data/export", params={**BASE, "start": "어제"})
        assert resp.status_code == 422

    def test_export_is_bounded_too(self, client):
        client.get("/api/sensor-data/export", params=BASE)
        assert client.captured["limit"] == sensor_data.DEFAULT_LIMIT


# ============================================================
# CSV Content-Disposition 헤더 인젝션 방지 (#244)
# ============================================================

class TestFilenameSanitization:
    def test_safe_part_strips_crlf_and_quotes(self):
        from app.routers.sensor_data import _safe_filename_part

        assert _safe_filename_part("sensor-01") == "sensor-01"
        # CR/LF 로 헤더 분열 시도
        assert "\r" not in _safe_filename_part("evil\r\nSet-Cookie: x=1")
        assert "\n" not in _safe_filename_part("evil\r\nSet-Cookie: x=1")
        # 따옴표로 filename 파싱 파괴 시도
        assert '"' not in _safe_filename_part('a"; dump.sql')
        # 빈 값/전부 불가 문자 → 폴백
        assert _safe_filename_part("///") == "data"
        # 길이 상한
        assert len(_safe_filename_part("a" * 500)) <= 64
