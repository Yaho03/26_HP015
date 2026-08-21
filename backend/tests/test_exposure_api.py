"""노출량 API 라우터 검증 (FR-701~708, §6.2).

DB 없이 되는 것만 본다 — **경로가 등록됐는가**와 **권한 게이트가 붙었는가**.
두 번째가 중요하다. 노출량은 개인 건강 정보이고, 수동 리셋은 자동 해제되지 않는
경보의 유일한 해제 경로다 (§5.2). 게이트가 빠지면 viewer 가 8시간 누적을 지울 수
있게 되는데, 그건 눈으로 리뷰해서 잡을 게 아니라 테스트가 잡아야 한다.
"""
from __future__ import annotations

import pytest

from app.main import app
from app.models.exposure import EXPOSURE_METRICS


def _routes() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for r in app.routes:
        path = getattr(r, "path", None)
        methods = getattr(r, "methods", None)
        if path and methods:
            out.setdefault(path, set()).update(methods)
    return out


def _route(path: str):
    for r in app.routes:
        if getattr(r, "path", None) == path:
            return r
    raise AssertionError(f"경로가 등록되지 않았다: {path}")


def _dependency_names(path: str) -> set[str]:
    """해당 경로에 붙은 의존성 함수 이름들 (Depends 로 감싼 것 포함)."""
    route = _route(path)
    names: set[str] = set()
    for dep in route.dependant.dependencies:
        call = dep.call
        names.add(getattr(call, "__name__", type(call).__name__))
        # require_role("admin") 은 _gate 클로저를 돌려주고, 역할은 자유변수에
        # 튜플로 담겨 있다 (여러 역할을 받을 수 있어서). 문자열만 찾으면 못 잡는다.
        closure = getattr(call, "__closure__", None) or ()
        for cell in closure:
            try:
                value = cell.cell_contents
            except ValueError:
                continue
            names.update(_strings_in(value))
    return names


def _strings_in(value) -> set[str]:
    if isinstance(value, str):
        return {value}
    if isinstance(value, (tuple, list, set, frozenset)):
        out: set[str] = set()
        for item in value:
            out |= _strings_in(item)
        return out
    return set()


# ============================================================
# 경로 등록
# ============================================================

def test_all_six_endpoints_are_registered():
    routes = _routes()
    assert "GET" in routes.get("/api/exposure/current", set())
    assert "GET" in routes.get("/api/exposure/current/{node_id}", set())
    assert "GET" in routes.get("/api/exposure/history", set())
    assert "GET" in routes.get("/api/exposure/limits", set())
    assert "PUT" in routes.get("/api/exposure/limits/{metric}", set())
    assert "POST" in routes.get("/api/exposure/reset", set())


# ============================================================
# 권한 (§6.2 표)
# ============================================================

def test_reset_requires_supervisor_and_csrf():
    """§5.2 MUST — 수동 리셋은 supervisor 이상. 노출량 경보의 유일한 해제 경로다."""
    names = _dependency_names("/api/exposure/reset")
    assert "supervisor" in names, f"권한 게이트가 없다: {names}"
    assert "verify_csrf" in names, f"CSRF 검증이 없다: {names}"


def test_limit_update_requires_admin_and_csrf():
    """노출 기준값은 작업자 안전 기준이다. thresholds 와 같은 등급으로 막는다."""
    names = _dependency_names("/api/exposure/limits/{metric}")
    assert "admin" in names, f"권한 게이트가 없다: {names}"
    assert "verify_csrf" in names, f"CSRF 검증이 없다: {names}"


def test_read_endpoints_are_not_public():
    """노출량은 개인 건강 정보다. PUBLIC_PATHS 에 들어가면 안 된다 (§6.2 주석)."""
    from app.dependencies import auth

    public = getattr(auth, "PUBLIC_PATHS", set())
    for path in (
        "/api/exposure/current",
        "/api/exposure/history",
        "/api/exposure/limits",
        "/api/exposure/reset",
    ):
        assert path not in public, f"{path} 가 인증 없이 열려 있다"


# ============================================================
# 입력 검증
# ============================================================

def test_reset_reason_is_required():
    """사유 없이 지우면 8시간 누적을 지운 근거가 남지 않는다 (§5.2 MUST)."""
    from app.routers.exposure import ExposureResetRequest

    with pytest.raises(Exception):
        ExposureResetRequest(node_id="wearable-01", reason="")
    ok = ExposureResetRequest(node_id="wearable-01", reason="교대 종료")
    assert ok.reason == "교대 종료"


def test_limit_update_requires_a_reference():
    """출처 없는 기준값은 기준값이 아니다 (§3.3 MUST)."""
    from app.routers.exposure import ExposureLimitUpdate

    with pytest.raises(Exception):
        ExposureLimitUpdate(twa_limit_ppm=5000.0)  # reference 누락


def test_exposure_metrics_vocabulary_is_shared():
    """라우터가 받는 metric 목록이 DB CHECK 와 같은 어휘여야 한다 (§2.3)."""
    assert set(EXPOSURE_METRICS) == {"co2_ppm", "co_ppm", "h2s_ppm", "o2_pct"}
