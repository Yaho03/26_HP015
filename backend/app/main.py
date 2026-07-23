from fastapi import FastAPI

from app.routers import health

# 백엔드 앱 골격 (이슈 #37).
# MQTT 수신은 #44, DB 스키마/쿼리는 #50, 경보 판정은 후속 이슈에서 구현한다.
app = FastAPI(title="26_HP015 Backend")

app.include_router(health.router)
