#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT_PATH="${ROOT_DIR}/scripts/run-e2e.sh"
COMPOSE_FILE="${ROOT_DIR}/docker-compose.test.yml"
ENV_FILE="${ROOT_DIR}/.env.test"
DOCKER_GROUP_REEXEC_ENV="E2E_DOCKER_GROUP_REEXEC"

group_has_current_user() {
  local group="$1"
  local user group_entry member_list member
  local members=()

  user="$(id -un 2>/dev/null || true)"
  [[ -n "${group}" && -n "${user}" ]] || return 1

  group_entry="$(getent group "${group}" 2>/dev/null || true)"
  [[ -n "${group_entry}" ]] || return 1

  member_list="${group_entry##*:}"
  IFS=',' read -r -a members <<< "${member_list}"
  for member in "${members[@]}"; do
    if [[ "${member}" == "${user}" ]]; then
      return 0
    fi
  done

  return 1
}

docker_reentry_group() {
  local socket_group

  if [[ -n "${E2E_DOCKER_GROUP:-}" ]] && group_has_current_user "${E2E_DOCKER_GROUP}"; then
    printf '%s\n' "${E2E_DOCKER_GROUP}"
    return 0
  fi

  socket_group="$(stat -Lc '%G' /var/run/docker.sock 2>/dev/null || true)"
  if [[ -n "${socket_group}" && "${socket_group}" != "UNKNOWN" ]] && group_has_current_user "${socket_group}"; then
    printf '%s\n' "${socket_group}"
    return 0
  fi

  if group_has_current_user "docker"; then
    printf 'docker\n'
    return 0
  fi

  return 1
}

reexec_with_docker_group() {
  local group="$1"
  local cmd quoted arg
  shift

  if [[ -n "${!DOCKER_GROUP_REEXEC_ENV:-}" ]]; then
    return 1
  fi

  if ! command -v sg >/dev/null 2>&1; then
    return 1
  fi

  if ! sg "${group}" -c 'true' >/dev/null 2>&1; then
    return 1
  fi

  printf 'Docker is not reachable with the current process groups; re-running under group "%s".\n' "${group}" >&2

  printf -v cmd 'cd %q && %s=1 exec bash %q' "${ROOT_DIR}" "${DOCKER_GROUP_REEXEC_ENV}" "${SCRIPT_PATH}"
  for arg in "$@"; do
    printf -v quoted ' %q' "${arg}"
    cmd+="${quoted}"
  done

  exec sg "${group}" -c "${cmd}"
}

ensure_docker_access() {
  local docker_error group socket_summary active_groups

  if docker info >/dev/null 2>&1; then
    return 0
  fi

  docker_error="$(docker info 2>&1 || true)"
  group="$(docker_reentry_group || true)"
  if [[ -n "${group}" ]]; then
    reexec_with_docker_group "${group}" "$@"
  fi

  socket_summary="$(stat -Lc '%A %U:%G %n' /var/run/docker.sock 2>/dev/null || printf 'missing /var/run/docker.sock')"
  active_groups="$(id -Gn 2>/dev/null || true)"

  printf 'Docker is not reachable from this process.\n' >&2
  printf 'Active groups: %s\n' "${active_groups:-unknown}" >&2
  printf 'Docker socket: %s\n' "${socket_summary}" >&2
  printf '\nDocker error:\n%s\n' "${docker_error}" >&2

  if [[ -n "${group}" ]]; then
    printf '\nThe current user is configured for group "%s", but this process cannot enter it.\n' "${group}" >&2
    printf 'For Codex, run this command with external approval, for example: bash scripts/run-e2e.sh\n' >&2
    printf 'For Claude or another local agent, restart the agent from a fresh login shell or run: sg %q -c %q\n' "${group}" "bash ${SCRIPT_PATH}" >&2
  else
    printf '\nAdd the current user to the Docker socket group, then restart the agent shell/session.\n' >&2
  fi

  exit 1
}

if [[ ! -f "${ENV_FILE}" ]]; then
  printf 'Missing %s. E2E requires explicit test environment configuration.\n' "${ENV_FILE}" >&2
  exit 1
fi

cd "${ROOT_DIR}"

ensure_docker_access "$@"

docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" down -v --remove-orphans
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" build e2e-runner
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" up -d --force-recreate --renew-anon-volumes --wait --wait-timeout 180 mysql-test redis-test

docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" run --rm e2e-runner python -m pytest tests/e2e "$@"
