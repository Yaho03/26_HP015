#!/usr/bin/env bash
# 통합 배포 스크립트 (이슈 #85).
# docker-compose 로 TimescaleDB + Mosquitto + Backend + Frontend 전체 스택을 띄운다.
#
# 사용:
#   ./scripts/deploy.sh up       # 전체 스택 시작 (백그라운드)
#   ./scripts/deploy.sh down     # 전체 스택 중지
#   ./scripts/deploy.sh restart  # 백엔드/프론트엔드만 재시작 (DB/브로커 유지)
#   ./scripts/deploy.sh status   # 서비스 상태
#   ./scripts/deploy.sh logs     # 로그 follow
#   ./scripts/deploy.sh health   # /health 엔드포인트 확인

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOCKER_DIR="${ROOT_DIR}/docker"
ACTION="${1:-up}"

# --- Mosquitto passwordfile 자동 생성 (이슈 #115) -----------------------------
# mosquitto.conf 는 allow_anonymous false + password_file 을 요구하는데, 그 파일은
# 자격증명이라 커밋되지 않는다. 새로 clone 한 사람은 파일이 없어 브로커 인증이
# 거부되고, 백엔드는 뜨지만 아무것도 구독하지 못한 채 정상인 척한다.
# README 의 수동 명령을 안 읽으면 원인을 찾기 어려우므로 여기서 만들어 준다.
PASSWORD_FILE="${DOCKER_DIR}/mosquitto/config/passwordfile"

ensure_passwordfile() {
  if [[ -f "${PASSWORD_FILE}" ]]; then
    return 0
  fi

  # .env 는 KEY=value 형식이다. 값에 공백이 있어도 그대로 읽는다.
  local user pass
  user="$(grep -E '^MQTT_USERNAME=' .env | head -1 | cut -d= -f2-)"
  pass="$(grep -E '^MQTT_PASSWORD=' .env | head -1 | cut -d= -f2-)"

  if [[ -z "${user}" || -z "${pass}" ]]; then
    echo "ERROR: docker/.env 에 MQTT_USERNAME / MQTT_PASSWORD 를 채우세요." >&2
    echo "       비우면 브로커가 익명 접속을 거부해 백엔드가 구독하지 못합니다." >&2
    exit 1
  fi

  echo "→ mosquitto passwordfile 이 없어 .env 값으로 생성합니다..."
  docker run --rm -v "${DOCKER_DIR}/mosquitto/config:/mosquitto/config" \
    eclipse-mosquitto:2.0 \
    mosquitto_passwd -b -c /mosquitto/config/passwordfile "${user}" "${pass}" >/dev/null

  # 브로커가 너무 열린 권한을 경고한다.
  chmod 600 "${PASSWORD_FILE}"
  echo "✓ passwordfile 생성 (user=${user})"
}


cd "${DOCKER_DIR}"

case "${ACTION}" in
  up)
    if [[ ! -f .env ]]; then
      echo "ERROR: docker/.env 가 없습니다. .env.example 을 복사해 값 채우세요." >&2
      exit 1
    fi
    ensure_passwordfile
    echo "→ 통합 스택 빌드 및 시작..."
    docker compose build
    docker compose up -d
    echo "→ 헬스 체크 대기 중..."
    # /health 는 degraded 여도 200 을 반환한다. 응답 유무가 아니라 내용을 봐야
    # MQTT 인증 실패 같은 상황을 잡을 수 있다 (이슈 #119).
    health_body=""
    for i in {1..30}; do
      health_body="$(curl -sf http://localhost:8000/health 2>/dev/null || true)"
      if [[ "${health_body}" == *'"status":"ok"'* ]]; then
        echo "✓ Backend healthy"
        break
      fi
      sleep 2
    done
    if [[ "${health_body}" != *'"status":"ok"'* ]]; then
      echo "⚠ Backend 가 정상 상태가 아닙니다:" >&2
      echo "  ${health_body:-응답 없음}" >&2
      echo "  mqtt.connected=false 이면 passwordfile 과 docker/.env 의" >&2
      echo "  MQTT_USERNAME/MQTT_PASSWORD 가 일치하는지 확인하세요." >&2
    fi
    echo
    echo "✓ 스택 실행 중"
    echo "  - Frontend: http://localhost:5173"
    echo "  - Backend:  http://localhost:8000"
    echo "  - DB:       localhost:5432"
    echo "  - MQTT:     localhost:1883"
    ;;

  down)
    echo "→ 스택 중지..."
    docker compose down
    ;;

  restart)
    echo "→ 앱 서비스만 재시작 (DB/브로커 유지)..."
    docker compose restart backend frontend
    ;;

  status)
    docker compose ps
    ;;

  logs)
    docker compose logs -f --tail=100
    ;;

  health)
    echo "→ Backend /health:"
    curl -sS http://localhost:8000/health || echo "UNREACHABLE"
    echo
    echo "→ Metrics:"
    curl -sS http://localhost:8000/api/metrics || echo "UNREACHABLE"
    echo
    ;;

  *)
    echo "Usage: $0 {up|down|restart|status|logs|health}" >&2
    exit 2
    ;;
esac
