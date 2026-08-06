from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import db
from app.routers import health
from app.services import mqtt_subscriber


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect()
    await mqtt_subscriber.start()
    yield
    await mqtt_subscriber.stop()
    await db.disconnect()


# 백엔드 앱 (이슈 #37 골격 + #51 MQTT 수신/저장 파이프라인).
# 경보 판정은 후속 이슈에서 구현한다.
app = FastAPI(title="26_HP015 Backend", lifespan=lifespan)

app.include_router(health.router)
