from fastapi import FastAPI

# Skeleton app. Routers, MQTT ingest, WebSocket, and TimescaleDB wiring
# are added in issue #37.
app = FastAPI(title="26_HP015 Backend")


@app.get("/health")
def health():
    return {"status": "ok"}
