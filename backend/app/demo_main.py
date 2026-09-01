"""시연 제어 전용 FastAPI 앱.

메인 모니터링 서버와 인증 DB만 공유하고 MQTT 구독·경보 판정 서비스는 시작하지
않는다. 시나리오 주입 프로세스만 관리하므로 촬영 중 메인 서버와 독립적으로
재시작할 수 있다.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import db, observability
from app.routers import auth, demo, demo_console


@asynccontextmanager
async def lifespan(_app: FastAPI):
    observability.setup_logging()
    await db.connect()
    try:
        yield
    finally:
        await demo.shutdown()
        if db.is_initialized():
            await db.disconnect()


app = FastAPI(
    title="26_HP015 Demo Control",
    lifespan=lifespan,
)


@app.get("/health", include_in_schema=False)
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "demo-control"}


app.include_router(auth.router)
app.include_router(demo.router)
app.include_router(demo_console.router)
app.include_router(demo_console.control_router)
