"""health & metrics API (이슈 #88, #119)."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app import db
from app.dependencies.auth import require_role
from app.services import evacuation_service, exposure_service, mqtt_subscriber

router = APIRouter()


@router.get("/health")
async def health():
    """실제 상태를 반환한다.

    예전에는 클라이언트 객체와 커넥션 풀의 존재 여부만 봤다. MQTT 인증이 거부돼
    아무 토픽도 구독하지 못한 상태에서도 ok 를 반환했고(#115 연쇄), 사이드바 연결
    표시가 이 응답을 그대로 믿으므로 화면까지 같이 거짓말했다.

    HTTP 상태는 항상 200 이다. 상태는 본문으로 알린다 — 엔드포인트 자체가 죽은
    것과 의존 서비스가 degraded 인 것은 구분되어야 한다.
    """
    mqtt_ok = mqtt_subscriber.is_healthy()
    db_ok = await db.ping()
    evacuation = evacuation_service.status()
    exposure = exposure_service.status()
    return {
        # 경로/노출 기능은 status 에 반영하지 않는다. 통행 구조가 없어도 센서 수집과
        # 가스 경보는 정상이고, 그쪽이 이 시스템의 본체다. 경로가 꺼진 것을
        # degraded 로 올리면 컨테이너 헬스체크가 재시작 루프를 돈다
        # (12_EVACUATION_ROUTE_SPEC §6.3).
        "status": "ok" if (mqtt_ok and db_ok) else "degraded",
        "mqtt": {"connected": mqtt_ok},
        "db": {"pool_initialized": db_ok},
        # 꺼져 있으면 왜 꺼졌는지까지 싣는다. 대시보드가 이 사유를 그대로 배너에
        # 띄운다 — 조용히 사라지지 않게 하는 것이 요점이다 (이슈 #154 의 교훈).
        "evacuation": evacuation.model_dump() if hasattr(evacuation, "model_dump") else evacuation,
        "exposure": exposure.model_dump() if hasattr(exposure, "model_dump") else exposure,
    }


@router.get("/api/metrics")
def get_metrics(_admin=Depends(require_role("admin"))):
    from app.observability import metrics
    return metrics.snapshot()
