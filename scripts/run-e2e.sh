#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${ROOT_DIR}/docker-compose.test.yml"
ENV_FILE="${ROOT_DIR}/.env.test"

if [[ ! -f "${ENV_FILE}" ]]; then
  printf 'Missing %s. E2E requires explicit test environment configuration.\n' "${ENV_FILE}" >&2
  exit 1
fi

cd "${ROOT_DIR}"

docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" down -v --remove-orphans
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" up -d --force-recreate --renew-anon-volumes --wait --wait-timeout 180

python -m pytest tests/e2e "$@"
