# 빌드 단계 — 휠 컴파일에만 gcc 가 필요하다.
FROM python:3.10-slim AS build

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libc6-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# 런타임 단계 — 컴파일러를 남기지 않는다. 공격면이 줄고 이미지도 작아진다.
FROM python:3.10-slim

WORKDIR /app

COPY --from=build /install /usr/local
COPY app/ ./app/
COPY migrations/ ./migrations/

# 컨테이너 안에서 root 로 돌 이유가 없다 (이슈 #128).
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# /health 는 degraded 여도 200 을 반환하므로(이슈 #119) 본문의 status 를 봐야 한다.
# MQTT·DB 연결에 시간이 걸리므로 start-period 를 넉넉히 준다.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import json,urllib.request,sys; \
sys.exit(0 if json.load(urllib.request.urlopen('http://localhost:8000/health', timeout=4))['status']=='ok' else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
