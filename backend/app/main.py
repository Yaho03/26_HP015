from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import db, migration_runner, observability
from app.config import settings
from app.dependencies.auth import enforce_authentication
from app.routers import (
    alert_events,
    auth,
    demo,
    exposure,
    health,
    sensor_data,
    thresholds,
    websocket,
    workers,
)
from app.services import (
    alert_publisher,
    alert_service,
    connection_monitor,
    evacuation_service,
    exposure_service,
    location_service,
    mqtt_subscriber,
    retention,
    sensor_broadcast,
    uwb_service,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    observability.setup_logging()
    await db.connect()
    started_mqtt = False
    started_retention = False
    started_conn_monitor = False
    try:
        await migration_runner.apply_all()
        # alert_service.init() 실패를 여기서 삼키면(기존 except Exception: pass) 임계값
        # 로드/콜백 등록이 안 된 채로 서버가 "정상" 기동돼 데이터는 계속 쌓이는데 경보
        # 판정만 영구히 멈춘다 — 로그 한 줄도 안 남아 발견이 불가능했다 (이슈 #109,
        # safety-critical). 다른 서비스들(mqtt_subscriber.start() 등)과 동일하게
        # 예외를 그대로 전파시켜 기동 자체를 실패시킨다 (컨테이너 재시작 루프로 즉시 드러남).
        await alert_service.init()
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
        await retention.start()
        started_retention = True
        await connection_monitor.start()
        started_conn_monitor = True
        yield
    finally:
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
app.include_router(thresholds.router)
app.include_router(sensor_data.router)
app.include_router(alert_events.router)
app.include_router(workers.router)
app.include_router(exposure.router)
app.include_router(websocket.router)
# 기본 비활성. settings.demo_control_enabled 가 false 면 모든 경로가 404 다.
app.include_router(demo.router)
