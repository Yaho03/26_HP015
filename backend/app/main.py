from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import db, migration_runner, observability
from app.routers import alert_events, health, sensor_data, thresholds, websocket
from app.services import (
    alert_publisher,
    alert_service,
    connection_monitor,
    location_service,
    mqtt_subscriber,
    retention,
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
        connection_monitor.init()
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

app.include_router(health.router)
app.include_router(thresholds.router)
app.include_router(sensor_data.router)
app.include_router(alert_events.router)
app.include_router(websocket.router)
