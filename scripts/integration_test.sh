#!/usr/bin/env bash
# 통합 테스트 러너 (이슈 #85).
# 백엔드 pytest + 프론트엔드 tsc/lint + inject tests + YAML lint 를 한 번에 실행.
# 실패 시 0이 아닌 exit code 반환 (CI 에서 활용).

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FAILED=0

run() {
  local label="$1"; shift
  echo "── ${label} ──"
  if "$@"; then
    echo "✓ ${label} passed"
  else
    echo "✗ ${label} FAILED"
    FAILED=1
  fi
  echo
}

cd "${ROOT_DIR}"

if [[ -f backend/.venv/bin/pytest ]]; then
  PYTEST="backend/.venv/bin/pytest"
else
  PYTEST="pytest"
fi

run "Backend pytest" "${PYTEST}" backend/tests/ -q
run "Inject pytest"  "${PYTEST}" experiments/inject/tests/ -q

if [[ -d frontend/node_modules ]]; then
  run "Frontend tsc"  bash -c 'cd frontend && npx tsc -b'
  run "Frontend lint" bash -c 'cd frontend && npm run lint'
else
  echo "⚠ Frontend node_modules 없음 - npm ci 먼저 실행\n"
fi

if [[ -f .github/workflows/ci.yml ]]; then
  if command -v yamllint >/dev/null 2>&1; then
    run "YAML lint (ci.yml)" yamllint .github/workflows/ci.yml
  else
    run "YAML syntax (ci.yml)" python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"
  fi
fi

if [[ ${FAILED} -ne 0 ]]; then
  echo "=================="
  echo "통합 테스트 실패 🚫"
  exit 1
fi

echo "=================="
echo "통합 테스트 통과 ✅"
exit 0
