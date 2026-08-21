# docker/ — 로컬 개발 인프라

TimescaleDB(시계열 DB) + Mosquitto(MQTT 브로커)를 Docker Compose로 실행한다. (이슈 #35)

> DB 스키마/hypertable은 #50, MQTT 메시지 처리는 #44/#37에서 구현한다. 여기서는 두 서버를 띄우는 것까지만 다룬다.

## 1. 환경 변수 준비

```bash
cd docker
cp .env.example .env
# .env 를 열어 POSTGRES_PASSWORD, MQTT_PASSWORD 를 실제 값으로 수정
```

`docker/.env` 는 `.gitignore` 로 무시된다 (비밀 값이 저장소에 올라가지 않음).

### 최초 관리자 계정 (AUTH-9)

`.env` 의 `BOOTSTRAP_ADMIN_USERNAME` / `BOOTSTRAP_ADMIN_PASSWORD` 를 채우면
백엔드 기동 시 **사용자가 한 명도 없을 때만** 관리자 계정이 1회 생성된다.
마이그레이션 SQL에 계정이 하드코딩되지 않는다. 첫 로그인 후 비밀번호 변경이
강제되며(`must_change_password`), 변경 전에는 다른 API 접근이 차단된다.
이미 계정이 있으면 이 값들은 무시된다 — `.env` 유출로 운영 계정이
교체되는 일이 없다.

## 2. Mosquitto 인증 파일 생성

> **`scripts/deploy.sh up` 을 쓰면 이 단계는 자동이다** (이슈 #115). `docker/.env` 에
> MQTT_USERNAME / MQTT_PASSWORD 만 채워두면 passwordfile 이 없을 때 스크립트가
> 같은 값으로 만들어 준다. 아래는 직접 만들거나 값을 바꿔 다시 만들 때 쓴다.
>
> `.env` 의 비밀번호를 바꿨다면 passwordfile 을 지우고 다시 실행해야 한다.
> 기존 파일이 있으면 스크립트는 건드리지 않는다.

Mosquitto는 해시된 `passwordfile` 로 인증한다. **`docker/.env` 의 `MQTT_USERNAME` / `MQTT_PASSWORD` 와 동일한 값**으로 생성한다:

```bash
# docker/ 에서 실행. <user> <password> 는 docker/.env 값과 반드시 동일하게.
docker run --rm -v "$(pwd)/mosquitto/config:/mosquitto/config" eclipse-mosquitto:2.0 \
  mosquitto_passwd -b -c /mosquitto/config/passwordfile <user> <password>

# 예시 (.env.example 기본값 기준 — 실제로는 각자 정한 값 사용):
docker run --rm -v "$(pwd)/mosquitto/config:/mosquitto/config" eclipse-mosquitto:2.0 \
  mosquitto_passwd -b -c /mosquitto/config/passwordfile hp015 change_me_dev_password
```

> `<password>` 는 `docker/.env` 의 `MQTT_PASSWORD` 와 반드시 같아야 한다. 다르면 인증에 실패한다.

생성된 `mosquitto/config/passwordfile` 도 `.gitignore` 로 무시된다.

## 3. 실행

```bash
docker compose up -d      # 백그라운드 실행
docker compose ps         # 상태 확인 (두 컨테이너 running)
docker compose logs -f    # 로그 확인
docker compose down       # 중지
```

## 4. 동작 확인

```bash
# TimescaleDB 접속 (비밀번호는 .env 값)
docker exec -it hp015-timescaledb psql -U hp015 -d hp015 -c "SELECT extname FROM pg_extension;"

# MQTT 발행/구독 테스트 (mosquitto 클라이언트 필요)
mosquitto_sub -h localhost -p 1883 -u hp015 -P <password> -t test &
mosquitto_pub -h localhost -p 1883 -u hp015 -P <password> -t test -m "hello"
```

## 구성

| 서비스 | 이미지 | 포트 | 볼륨 |
|--------|--------|------|------|
| timescaledb | `timescale/timescaledb:2.17.2-pg16` | 5432 | `timescale-data` |
| mosquitto | `eclipse-mosquitto:2.0` | 1883 | `mosquitto-data`, `./mosquitto/config` |
