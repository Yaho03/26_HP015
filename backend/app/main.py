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
        try:
            await alert_service.init()
        except Exception:
            pass
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
