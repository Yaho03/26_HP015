from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import db, migration_runner, observability
from app.config import settings
from app.routers import alert_events, health, sensor_data, thresholds, websocket
from app.services import (
    alert_publisher,
    alert_service,
    connection_monitor,
    location_service,
    mqtt_subscriber,
    retention,
    sensor_broadcast,
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
        try:
            await alert_service.init()
        except Exception:
            pass
        location_service.init()
        sensor_broadcast.init()
        await mqtt_subscriber.start()
        started_mqtt = True
        alert_publisher.init_publisher(mqtt_subscriber.get_client())
        alert_service._publisher = alert_publisher._publisher
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
        if db.is_initialized():
            await db.disconnect()


app = FastAPI(title="26_HP015 Backend", lifespan=lifespan)

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
app.include_router(thresholds.router)
app.include_router(sensor_data.router)
app.include_router(alert_events.router)
app.include_router(websocket.router)
