#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT_PATH="${ROOT_DIR}/scripts/run-e2e.sh"
COMPOSE_FILE="${ROOT_DIR}/docker-compose.test.yml"
ENV_FILE="${ROOT_DIR}/.env.test"
COMPOSE_PROJECT_NAME="api-auth-e2e"
ARTIFACT_DIR="${ROOT_DIR}/test-results/e2e"
DEFAULT_LOCK_FILE="/tmp/api-auth-test-workflows.lock"
LOCK_FILE="${TEST_WORKFLOW_LOCK_FILE:-${DEFAULT_LOCK_FILE}}"
FINGERPRINT_SCRIPT="${ROOT_DIR}/scripts/test-source-fingerprint.py"
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

if [[ "$#" -eq 0 ]]; then
    if [[ -n "${PYTEST_ADDOPTS:-}" ]]; then
      printf 'PYTEST_ADDOPTS must be empty for a certified full E2E run.\n' >&2
      exit 2
    fi
    if [[ "${LOCK_FILE}" != "${DEFAULT_LOCK_FILE}" ]]; then
      printf 'Certified full E2E runs must use the shared workflow lock: %s\n' \
        "${DEFAULT_LOCK_FILE}" >&2
      exit 2
    fi
    for resource_setting in \
      E2E_MYSQL_MEMORY_LIMIT=1g \
      E2E_REDIS_MEMORY_LIMIT=128m \
      E2E_MAILPIT_MEMORY_LIMIT=128m \
      E2E_RUNNER_MEMORY_LIMIT=2g
    do
      resource_name="${resource_setting%%=*}"
      resource_default="${resource_setting#*=}"
      if [[ -n "${!resource_name:-}" && "${!resource_name}" != "${resource_default}" ]]; then
        printf 'Certified full E2E runs require %s=%s (received %s).\n' \
          "${resource_name}" "${resource_default}" "${!resource_name}" >&2
        exit 2
      fi
      # Shell exports outrank Compose's --env-file interpolation, so a stale or
      # edited .env.test cannot silently raise the certified container ceilings.
      export "${resource_name}=${resource_default}"
    done
elif [[ "${1}" == "--target" ]]; then
    if [[ -z "${2:-}" ]]; then
      printf 'Usage: bash scripts/run-e2e.sh --target tests/... [-- <pytest args>]\n' >&2
      exit 2
    fi
elif [[ "${1}" == "-h" || "${1}" == "--help" ]]; then
    printf 'Usage: bash scripts/run-e2e.sh [--target tests/... [-- <pytest args>]]\n'
    exit 0
else
    printf 'Full E2E runs accept no pytest arguments; use --target tests/... -- <pytest args>.\n' >&2
    exit 2
fi

if [[ "${LOCK_FILE}" != "${DEFAULT_LOCK_FILE}" \
   && "${ALLOW_TEST_WORKFLOW_LOCK_OVERRIDE:-0}" != "1" ]]; then
  printf 'E2E test lock overrides require ALLOW_TEST_WORKFLOW_LOCK_OVERRIDE=1\n' >&2
  exit 2
fi

cd "${ROOT_DIR}"

ensure_docker_access "$@"

mkdir -p "${ARTIFACT_DIR}"

exec 9>"${LOCK_FILE}"
if ! flock -n 9; then
  printf 'Another api.auth test workflow owns %s; refusing an overlapping run.\n' "${LOCK_FILE}" >&2
  exit 1
fi
rm -f \
  "${ARTIFACT_DIR}/docker-compose.log" \
  "${ARTIFACT_DIR}/summary.txt" \
  "${ARTIFACT_DIR}/pytest.log" \
  "${ARTIFACT_DIR}/.coverage" \
  "${ARTIFACT_DIR}/coverage.xml" \
  "${ARTIFACT_DIR}/coverage.json" \
  "${ARTIFACT_DIR}"/junit.*.xml
rm -rf "${ARTIFACT_DIR}/html"

compose() {
  docker compose \
    --project-name "${COMPOSE_PROJECT_NAME}" \
    --env-file "${ENV_FILE}" \
    -f "${COMPOSE_FILE}" \
    "$@"
}

compose_image_id() {
  local service="$1"
  local fallback_reference="${2:-}"
  local image_reference
  local image_id
  image_reference="$(compose images -q "${service}")"
  if [[ -z "${image_reference}" && -n "${fallback_reference}" ]]; then
    image_reference="${fallback_reference}"
  fi
  if [[ -z "${image_reference}" || "${image_reference}" == *$'\n'* ]]; then
    printf 'Could not resolve exactly one Docker image for %s.\n' "${service}" >&2
    return 2
  fi
  image_id="$(docker image inspect --format '{{.Id}}' "${image_reference}")"
  if [[ ! "${image_id}" =~ ^sha256:[0-9a-f]{64}$ ]]; then
    printf 'Could not attest the resolved Docker image for %s: %s\n' \
      "${service}" "${image_id:-<missing>}" >&2
    return 2
  fi
  printf '%s' "${image_id}"
}

cleanup() {
  local status=$?
  local teardown_status=0
  local attestation_status=0
  local final_fingerprint=""
  trap - EXIT INT TERM
  set +e

  final_fingerprint="$("${FINGERPRINT_PYTHON}" "${FINGERPRINT_SCRIPT}" 2>/dev/null)"
  if [[ "${status}" -eq 0 && "${final_fingerprint}" != "${E2E_EXPECTED_SOURCE_FINGERPRINT}" ]]; then
    printf 'Source changed while the outer E2E workflow was running.\n' >&2
    status=1
  fi
  if [[ "${status}" -ne 0 ]]; then
    compose logs --no-color > "${ARTIFACT_DIR}/docker-compose.log" 2>&1
  fi
  compose down -v --remove-orphans --timeout 20
  teardown_status=$?
  if [[ "${status}" -eq 0 && "${teardown_status}" -ne 0 ]]; then
    printf 'E2E tests passed, but disposable Docker teardown failed with status %s.\n' \
      "${teardown_status}" >&2
    status="${teardown_status}"
  fi

  if [[ -f "${ARTIFACT_DIR}/summary.txt" ]]; then
    printf 'wrapper_status=%s\n' "${status}" >> "${ARTIFACT_DIR}/summary.txt"
    attestation_status=$?
    if [[ "${status}" -eq 0 && "${attestation_status}" -ne 0 ]]; then
      printf 'E2E wrapper could not attest its final status.\n' >&2
      status=1
    fi
  elif [[ "${status}" -eq 0 ]]; then
    printf 'E2E runner returned success without a workflow summary.\n' >&2
    status=1
  fi
  exit "${status}"
}

if [[ -n "${FINGERPRINT_PYTHON:-}" ]]; then
  :
elif command -v python3 >/dev/null 2>&1; then
  FINGERPRINT_PYTHON="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
  FINGERPRINT_PYTHON="$(command -v python)"
else
  printf 'Python is required to fingerprint the E2E source state.\n' >&2
  exit 2
fi
if [[ ! -x "${FINGERPRINT_PYTHON}" || ! -f "${FINGERPRINT_SCRIPT}" ]]; then
  printf 'The E2E source-fingerprint interpreter or helper is unavailable.\n' >&2
  exit 2
fi

E2E_EXPECTED_SOURCE_FINGERPRINT="$(
  "${FINGERPRINT_PYTHON}" "${FINGERPRINT_SCRIPT}"
)"
if [[ ! "${E2E_EXPECTED_SOURCE_FINGERPRINT}" =~ ^[0-9a-f]{64}$ ]]; then
  printf 'Could not fingerprint source before the E2E image build and schema startup.\n' >&2
  exit 2
fi

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

compose config --quiet
compose down -v --remove-orphans --timeout 20
compose build e2e-runner
compose up \
  --force-recreate \
  --renew-anon-volumes \
  --wait \
  --wait-timeout 240 \
  mysql-test redis-test mailpit-test

pre_run_fingerprint="$("${FINGERPRINT_PYTHON}" "${FINGERPRINT_SCRIPT}")"
if [[ "${pre_run_fingerprint}" != "${E2E_EXPECTED_SOURCE_FINGERPRINT}" ]]; then
  printf 'Source changed during the E2E image build or service initialization.\n' >&2
  exit 1
fi

E2E_RUNNER_IMAGE_ID="$(
  compose_image_id e2e-runner api-auth-e2e:py312
)" || exit 2
E2E_MYSQL_IMAGE_ID="$(compose_image_id mysql-test)" || exit 2
E2E_REDIS_IMAGE_ID="$(compose_image_id redis-test)" || exit 2
E2E_MAILPIT_IMAGE_ID="$(compose_image_id mailpit-test)" || exit 2

compose run \
  --rm \
  --no-deps \
  --user "$(id -u):$(id -g)" \
  -e "E2E_EXPECTED_SOURCE_FINGERPRINT=${E2E_EXPECTED_SOURCE_FINGERPRINT}" \
  -e "E2E_RUNNER_IMAGE_ID=${E2E_RUNNER_IMAGE_ID}" \
  -e "E2E_MYSQL_IMAGE_ID=${E2E_MYSQL_IMAGE_ID}" \
  -e "E2E_REDIS_IMAGE_ID=${E2E_REDIS_IMAGE_ID}" \
  -e "E2E_MAILPIT_IMAGE_ID=${E2E_MAILPIT_IMAGE_ID}" \
  e2e-runner \
  bash scripts/run-e2e-batches.sh "$@"
