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

cd "${DOCKER_DIR}"

case "${ACTION}" in
  up)
    if [[ ! -f .env ]]; then
      echo "ERROR: docker/.env 가 없습니다. .env.example 을 복사해 값 채우세요." >&2
      exit 1
    fi
    echo "→ 통합 스택 빌드 및 시작..."
    docker compose build
    docker compose up -d
    echo "→ 헬스 체크 대기 중..."
    for i in {1..30}; do
      if curl -sf http://localhost:8000/health >/dev/null 2>&1; then
        echo "✓ Backend healthy"
        break
      fi
      sleep 2
    done
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
