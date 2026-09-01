import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import db, migration_runner, observability
from app.config import settings
from app.dependencies.auth import enforce_authentication
from app.routers import (
    ai_anomalies,
    alert_events,
    audit_log,
    auth,
    demo,
    evacuation,
    exposure,
    health,
    sensor_data,
    thresholds,
    users,
    websocket,
    workers,
)
from app.services import (
    ai_anomaly_service,
    alert_publisher,
    alert_service,
    auth_service,
    connection_monitor,
    evacuation_service,
    exposure_service,
    location_service,
    mqtt_subscriber,
    retention,
    sensor_broadcast,
    uwb_service,
    ws_manager,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    observability.setup_logging()
    await db.connect()
    started_mqtt = False
    started_retention = False
    started_conn_monitor = False
    started_ai_anomaly = False
    try:
        await migration_runner.apply_all()
        # alert_service.init() 실패를 여기서 삼키면(기존 except Exception: pass) 임계값
        # 로드/콜백 등록이 안 된 채로 서버가 "정상" 기동돼 데이터는 계속 쌓이는데 경보
        # 판정만 영구히 멈춘다 — 로그 한 줄도 안 남아 발견이 불가능했다 (이슈 #109,
        # safety-critical). 다른 서비스들(mqtt_subscriber.start() 등)과 동일하게
        # 예외를 그대로 전파시켜 기동 자체를 실패시킨다 (컨테이너 재시작 루프로 즉시 드러남).
        await alert_service.init()
        # 최초 관리자 부트스트랩 (AUTH-9). 마이그레이션 직후, 서비스 기동 전 —
        # 실패해도 기동을 막지 않는다: 부트스트랩은 편의 기능이고 로그로 드러난다.
        try:
            await auth_service.bootstrap_admin()
        except Exception:
            logger.exception("admin bootstrap failed")
        location_service.init()
        uwb_service.init()
        sensor_broadcast.init()
        connection_monitor.init()
        # 신규 기능 2건 (FR-701 누적 노출량, FR-801 탈출 경로). 지금은 스텁이라
        # 경고만 남기고 넘어간다. 두 기능을 병렬 세션에서 만들기 때문에 lifespan
        # 등록 자리를 미리 잡아둔다 — 각 세션이 자기 서비스 모듈 내부만 채우면
        # 되고, 이 파일의 같은 줄을 양쪽에서 고치는 일이 없다.
        await exposure_service.init()
        await evacuation_service.init()
        await mqtt_subscriber.start()
        started_mqtt = True
        alert_publisher.init_publisher(mqtt_subscriber.get_client())
        # 활성 경보 추적 상태를 DB 에서 복구한다 (이슈 #194). 이게 없으면 재시작
        # 직후의 NORMAL 전이가 publish_transition 의 #111 가드에 걸려 통째로
        # 버려지고, 재시작 전에 뜬 경보가 영구히 해제되지 않는다.
        # 같은 DB snapshot으로 발행 측(#194)과 판정 측(#196)을 함께 복구한다.
        # 판정 상태가 normal로 초기화되면 이미 active인 L3가 재발화해 경보 피로와
        # activated_at 단절을 만든다. MQTT retained 대신 영속 이력 DB를 단일
        # 복구 원천으로 사용한다 (04_DATA_CONTRACT §3.5).
        await alert_publisher.restore_runtime_alert_state()
        await retention.start()
        started_retention = True
        await connection_monitor.start()
        started_conn_monitor = True
        # AI 이상징후 (연구용, §9). 안전 경보와 완전히 별개다.
        # init() 은 예외를 밖으로 던지지 않는다 — 모델 파일이 없다고 센서 수집과
        # 안전 경보가 멈추면 연구용 기능 하나 때문에 안전 시스템을 내리는 셈이다.
        # 모델이 없으면 서비스가 model_not_ready 로 남고 화면이 그대로 표시한다.
        ai_anomaly_service.init()
        ai_anomaly_service.set_broadcast(ws_manager.manager.broadcast)
        await ai_anomaly_service.start()
        started_ai_anomaly = True
        yield
    finally:
        if started_ai_anomaly:
            await ai_anomaly_service.stop()
        if started_conn_monitor:
            await connection_monitor.stop()
        if started_retention:
            await retention.stop()
        if started_mqtt:
            await mqtt_subscriber.stop()
        # 노출량은 종료 직전에 마지막 flush 를 한 번 더 한다 (FR-704, §4.5). 이게
        # 없으면 정상 종료에서도 flush 주기만큼(기본 10초) 누적이 날아간다.
        # started_* 플래그를 두지 않는 이유는 stop() 이 열린 윈도우가 없으면 DB 를
        # 건드리지 않고 즉시 돌아오기 때문이다 — 기동이 일찍 실패해도 안전하다.
        # 반드시 db.disconnect() **앞**이어야 한다. flush 가 풀을 쓴다.
        await exposure_service.stop()
        if db.is_initialized():
            await db.disconnect()


app = FastAPI(
    title="26_HP015 Backend",
    lifespan=lifespan,
    # 화이트리스트(/health, /api/auth/login) 외 전 경로 인증 강제 (AUTH-3).
    dependencies=[Depends(enforce_authentication)],
)

# 프론트엔드가 nginx 프록시 없이(예: vite dev server, :5173) 직접 API를 호출하는
# 개발 환경을 위한 CORS 허용. 배포 환경은 nginx가 /api, /ws를 같은 오리진으로
# 프록시하므로 CORS 자체가 발생하지 않지만, 개발 편의를 위해 명시적으로 허용
# 오리진을 설정한다(와일드카드 금지, 이슈 #105).
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(audit_log.router)
app.include_router(users.router)
app.include_router(thresholds.router)
app.include_router(sensor_data.router)
app.include_router(alert_events.router)
app.include_router(ai_anomalies.router)
app.include_router(workers.router)
app.include_router(evacuation.router)
app.include_router(exposure.router)
app.include_router(websocket.router)
# 기본 비활성. settings.demo_control_enabled 가 false 면 모든 경로가 404 다.
app.include_router(demo.router)
