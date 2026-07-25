#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOST_DIR="${ROOT_DIR}/test-results/host"
E2E_DIR="${ROOT_DIR}/test-results/e2e"
OUTPUT_DIR="${ROOT_DIR}/test-results/combined"
PYTHON_BIN="${PYTHON_BIN:-${ROOT_DIR}/.venv/bin/python}"
COVERAGE_MEM_LIMIT_MB="${COVERAGE_MEM_LIMIT_MB:-1536}"
COVERAGE_TIMEOUT_SECONDS="${COVERAGE_TIMEOUT_SECONDS:-300}"
RCFILE="${ROOT_DIR}/.coveragerc"
FINGERPRINT_SCRIPT="${ROOT_DIR}/scripts/test-source-fingerprint.py"
RUNTIME_FINGERPRINT_SCRIPT="${ROOT_DIR}/scripts/test-runtime-fingerprint.py"
HOST_DATA="${HOST_DIR}/.coverage"
E2E_DATA="${E2E_DIR}/.coverage"
COMBINED_DATA="${OUTPUT_DIR}/.coverage"
DEFAULT_LOCK_FILE="/tmp/api-auth-test-workflows.lock"
LOCK_FILE="${TEST_WORKFLOW_LOCK_FILE:-${DEFAULT_LOCK_FILE}}"

COMMON_SUMMARY_KEYS=(
  summary_version
  workflow
  selection_scope
  pytest_args_count
  source_fingerprint_start
  source_fingerprint_end
  source_stable
  runtime_dependency_fingerprint_start
  runtime_dependency_fingerprint_end
  runtime_stable
  python_runtime
  expected_batches
  expected_completed_batches
  expected_filtered_batches
  completed_batches
  filtered_batches
  executed_tests
  failed_batches
  coverage_status
  certification_status
  coverage_data_sha256
  pytest_mem_limit_mb
  pytest_timeout_seconds
  batch_timeout_seconds
  coverage_timeout_seconds
)

summary_value() {
  local label="$1"
  local summary="$2"
  local key="$3"
  local -a values=()

  mapfile -t values < <(sed -n "s/^${key}=//p" "${summary}")
  if [[ "${#values[@]}" -ne 1 ]]; then
    printf '%s summary must contain exactly one %s entry: %s\n' \
      "${label}" "${key}" "${summary}" >&2
    return 2
  fi
  printf '%s' "${values[0]}"
}

load_summary() {
  local output_name="$1"
  local label="$2"
  local summary="$3"
  shift 3
  local -n output="${output_name}"
  local key

  if [[ ! -s "${summary}" ]]; then
    printf '%s coverage summary is missing or empty: %s\n' "${label}" "${summary}" >&2
    return 2
  fi
  for key in "$@"; do
    output["${key}"]="$(summary_value "${label}" "${summary}" "${key}")" || return 2
  done
}

require_uint() {
  local label="$1"
  local key="$2"
  local value="$3"
  if [[ ! "${value}" =~ ^(0|[1-9][0-9]*)$ || "${#value}" -gt 10 ]]; then
    printf '%s summary has a non-canonical unsigned integer for %s: %s\n' \
      "${label}" "${key}" "${value}" >&2
    return 2
  fi
}

require_sha256() {
  local label="$1"
  local key="$2"
  local value="$3"
  if [[ ! "${value}" =~ ^[0-9a-f]{64}$ ]]; then
    printf '%s summary has an invalid SHA-256 for %s: %s\n' \
      "${label}" "${key}" "${value}" >&2
    return 2
  fi
}

require_positive_at_most() {
  local label="$1"
  local key="$2"
  local value="$3"
  local maximum="$4"
  local value_length="${#value}"
  local maximum_length="${#maximum}"
  if [[ ! "${value}" =~ ^[1-9][0-9]*$ \
     || "${value_length}" -gt "${maximum_length}" \
     || ( "${value_length}" -eq "${maximum_length}" && "${value}" > "${maximum}" ) ]]; then
    printf '%s summary has an unsafe %s value (maximum %s): %s\n' \
      "${label}" "${key}" "${maximum}" "${value}" >&2
    return 2
  fi
}

run_coverage() {
  (
    local requested_kib current_soft_kib current_hard_kib effective_kib
    requested_kib=$((COVERAGE_MEM_LIMIT_MB * 1024))
    current_soft_kib="$(ulimit -S -v)"
    current_hard_kib="$(ulimit -H -v)"
    effective_kib="${requested_kib}"
    if [[ "${current_soft_kib}" != "unlimited" && "${current_soft_kib}" -lt "${effective_kib}" ]]; then
      effective_kib="${current_soft_kib}"
    fi
    if [[ "${current_hard_kib}" != "unlimited" && "${current_hard_kib}" -lt "${effective_kib}" ]]; then
      effective_kib="${current_hard_kib}"
    fi
    if ! ulimit -S -v "${effective_kib}"; then
      printf 'Could not apply the non-weakening coverage memory limit\n' >&2
      exit 2
    fi
    exec timeout --signal=TERM --kill-after=15s \
      "${COVERAGE_TIMEOUT_SECONDS}" "${PYTHON_BIN}" -m coverage "$@"
  )
}

validate_summary() {
  local summary_name="$1"
  local label="$2"
  local expected_workflow="$3"
  local -n summary="${summary_name}"
  local key
  local -a integer_keys=(
    pytest_args_count
    source_stable
    runtime_stable
    expected_batches
    expected_completed_batches
    expected_filtered_batches
    completed_batches
    filtered_batches
    executed_tests
    failed_batches
    coverage_status
    certification_status
    pytest_mem_limit_mb
    pytest_timeout_seconds
    batch_timeout_seconds
    coverage_timeout_seconds
  )

  [[ "${summary[summary_version]}" == "1" ]] || {
    printf '%s summary version is unsupported: %s\n' "${label}" "${summary[summary_version]}" >&2
    return 2
  }
  [[ "${summary[workflow]}" == "${expected_workflow}" ]] || {
    printf '%s summary workflow mismatch: %s\n' "${label}" "${summary[workflow]}" >&2
    return 2
  }
  [[ "${summary[selection_scope]}" == "full" ]] || {
    printf '%s coverage is not from a full workflow run\n' "${label}" >&2
    return 2
  }

  for key in "${integer_keys[@]}"; do
    require_uint "${label}" "${key}" "${summary[${key}]}" || return 2
  done
  require_sha256 "${label}" source_fingerprint_start \
    "${summary[source_fingerprint_start]}" || return 2
  require_sha256 "${label}" source_fingerprint_end \
    "${summary[source_fingerprint_end]}" || return 2
  require_sha256 "${label}" coverage_data_sha256 \
    "${summary[coverage_data_sha256]}" || return 2
  require_sha256 "${label}" runtime_dependency_fingerprint_start \
    "${summary[runtime_dependency_fingerprint_start]}" || return 2
  require_sha256 "${label}" runtime_dependency_fingerprint_end \
    "${summary[runtime_dependency_fingerprint_end]}" || return 2
  if [[ ! "${summary[python_runtime]}" =~ ^[A-Za-z0-9._+-]+$ ]]; then
    printf '%s summary has an invalid Python runtime identity: %s\n' \
      "${label}" "${summary[python_runtime]}" >&2
    return 2
  fi

  if (( summary[expected_batches] == 0 )); then
    printf '%s summary certifies zero expected batches\n' "${label}" >&2
    return 2
  fi
  if (( summary[expected_completed_batches] + summary[expected_filtered_batches]
        != summary[expected_batches] )); then
    printf '%s expected batch arithmetic is inconsistent\n' "${label}" >&2
    return 2
  fi
  if (( summary[completed_batches] + summary[filtered_batches] + summary[failed_batches]
        != summary[expected_batches] )); then
    printf '%s actual batch arithmetic is inconsistent\n' "${label}" >&2
    return 2
  fi
  if (( summary[completed_batches] != summary[expected_completed_batches]
        || summary[filtered_batches] != summary[expected_filtered_batches] )); then
    printf '%s completed/filtered batch disposition does not match the manifest\n' \
      "${label}" >&2
    return 2
  fi
  if (( summary[pytest_args_count] != 0
        || summary[executed_tests] == 0
        || summary[failed_batches] != 0
        || summary[coverage_status] != 0
        || summary[certification_status] != 0
        || summary[source_stable] != 1
        || summary[runtime_stable] != 1 )); then
    printf '%s summary is not a successful unfiltered stable run\n' "${label}" >&2
    return 2
  fi
  if [[ "${summary[source_fingerprint_start]}" != "${summary[source_fingerprint_end]}" ]]; then
    printf '%s source changed while its workflow was running\n' "${label}" >&2
    return 2
  fi
  if [[ "${summary[runtime_dependency_fingerprint_start]}" \
        != "${summary[runtime_dependency_fingerprint_end]}" ]]; then
    printf '%s dependency runtime changed while its workflow was running\n' \
      "${label}" >&2
    return 2
  fi

  require_positive_at_most "${label}" pytest_mem_limit_mb \
    "${summary[pytest_mem_limit_mb]}" 1536 || return 2
  require_positive_at_most "${label}" pytest_timeout_seconds \
    "${summary[pytest_timeout_seconds]}" 60 || return 2
  require_positive_at_most "${label}" coverage_timeout_seconds \
    "${summary[coverage_timeout_seconds]}" 300 || return 2
  if [[ "${expected_workflow}" == "host" ]]; then
    require_positive_at_most "${label}" batch_timeout_seconds \
      "${summary[batch_timeout_seconds]}" 180 || return 2
  else
    require_positive_at_most "${label}" batch_timeout_seconds \
      "${summary[batch_timeout_seconds]}" 900 || return 2
  fi
}

if [[ ! -x "${PYTHON_BIN}" ]]; then
  printf 'Coverage interpreter is not executable: %s\n' "${PYTHON_BIN}" >&2
  exit 2
fi
require_positive_at_most "Combined coverage" COVERAGE_MEM_LIMIT_MB \
  "${COVERAGE_MEM_LIMIT_MB}" 1536 || exit 2
require_positive_at_most "Combined coverage" COVERAGE_TIMEOUT_SECONDS \
  "${COVERAGE_TIMEOUT_SECONDS}" 300 || exit 2
if [[ ! -f "${RCFILE}" || ! -f "${FINGERPRINT_SCRIPT}" \
   || ! -f "${RUNTIME_FINGERPRINT_SCRIPT}" ]]; then
  printf 'Coverage configuration or fingerprint helper is missing\n' >&2
  exit 2
fi

if [[ "${LOCK_FILE}" != "${DEFAULT_LOCK_FILE}" \
   && "${ALLOW_TEST_WORKFLOW_LOCK_OVERRIDE:-0}" != "1" ]]; then
  printf 'Coverage merge must use the shared workflow lock: %s\n' \
    "${DEFAULT_LOCK_FILE}" >&2
  exit 2
fi

exec 9>"${LOCK_FILE}"
if ! flock -n 9; then
  printf 'A test workflow is still running; refusing to merge moving artifacts.\n' >&2
  exit 1
fi

mkdir -p "${OUTPUT_DIR}"
# A merge attempt invalidates the previous success attestation immediately.
# Reports may remain useful for diagnosis, but cannot be mistaken for this run.
rm -f "${OUTPUT_DIR}/summary.txt"

declare -A host_summary=()
declare -A e2e_summary=()
load_summary host_summary "Host" "${HOST_DIR}/summary.txt" \
  "${COMMON_SUMMARY_KEYS[@]}" coverage_shards coverage_mem_limit_mb
load_summary e2e_summary "E2E" "${E2E_DIR}/summary.txt" \
  "${COMMON_SUMMARY_KEYS[@]}" expected_skip_batches expected_skipped_tests wrapper_status \
  e2e_runner_image_id mysql_image_id redis_image_id mailpit_image_id
validate_summary host_summary "Host" host
validate_summary e2e_summary "E2E" e2e
require_uint "Host" coverage_shards "${host_summary[coverage_shards]}"
require_positive_at_most "Host" coverage_mem_limit_mb \
  "${host_summary[coverage_mem_limit_mb]}" 1536
require_uint "E2E" expected_skip_batches "${e2e_summary[expected_skip_batches]}"
require_uint "E2E" expected_skipped_tests "${e2e_summary[expected_skipped_tests]}"
require_uint "E2E" wrapper_status "${e2e_summary[wrapper_status]}"
for image_key in \
  e2e_runner_image_id \
  mysql_image_id \
  redis_image_id \
  mailpit_image_id
do
  if [[ ! "${e2e_summary[${image_key}]}" =~ ^sha256:[0-9a-f]{64}$ ]]; then
    printf 'E2E summary has an invalid Docker image identity for %s: %s\n' \
      "${image_key}" "${e2e_summary[${image_key}]}" >&2
    exit 2
  fi
done

if (( host_summary[coverage_shards] != host_summary[expected_batches] )); then
  printf 'Host coverage shard count does not match its expected batch manifest\n' >&2
  exit 2
fi
if (( e2e_summary[expected_filtered_batches] != 0
      || e2e_summary[completed_batches] != e2e_summary[expected_batches]
      || e2e_summary[wrapper_status] != 0 )); then
  printf 'E2E summary contains filtered or incomplete batches\n' >&2
  exit 2
fi

current_fingerprint="$("${PYTHON_BIN}" "${FINGERPRINT_SCRIPT}")"
require_sha256 "Current" source_fingerprint "${current_fingerprint}"
if [[ "${host_summary[source_fingerprint_start]}" != "${current_fingerprint}" \
   || "${e2e_summary[source_fingerprint_start]}" != "${current_fingerprint}" ]]; then
  printf 'Host, E2E, and current source fingerprints do not all match\n' >&2
  exit 2
fi

current_runtime_fingerprint="$(
  env -u PYTHONPATH "${PYTHON_BIN}" "${RUNTIME_FINGERPRINT_SCRIPT}"
)"
require_sha256 "Current" runtime_dependency_fingerprint \
  "${current_runtime_fingerprint}"
if [[ "${host_summary[runtime_dependency_fingerprint_start]}" \
      != "${current_runtime_fingerprint}" \
   || "${e2e_summary[runtime_dependency_fingerprint_start]}" \
      != "${current_runtime_fingerprint}" ]]; then
  printf 'Host, E2E, and current installed dependency fingerprints do not all match\n' >&2
  exit 2
fi
current_python_runtime="$(
  env -u PYTHONPATH "${PYTHON_BIN}" -c \
    'import platform; print(f"{platform.python_implementation()}-{platform.python_version()}")'
)"
if [[ ! "${current_python_runtime}" =~ ^[A-Za-z0-9._+-]+$ \
   || "${host_summary[python_runtime]}" != "${current_python_runtime}" ]]; then
  printf 'Host coverage Python runtime does not match the current merge interpreter\n' >&2
  exit 2
fi

for data_file in "${HOST_DATA}" "${E2E_DATA}"; do
  if [[ ! -s "${data_file}" ]]; then
    printf 'Coverage data is missing or empty: %s\n' "${data_file}" >&2
    exit 2
  fi
done

host_hash_before="$(sha256sum "${HOST_DATA}" | cut -d ' ' -f 1)"
e2e_hash_before="$(sha256sum "${E2E_DATA}" | cut -d ' ' -f 1)"
if [[ "${host_hash_before}" != "${host_summary[coverage_data_sha256]}" \
   || "${e2e_hash_before}" != "${e2e_summary[coverage_data_sha256]}" ]]; then
  printf 'A coverage data file does not match the hash attested by its workflow\n' >&2
  exit 2
fi

rm -f \
  "${COMBINED_DATA}" \
  "${OUTPUT_DIR}/coverage.xml" \
  "${OUTPUT_DIR}/coverage.json"
rm -rf "${OUTPUT_DIR}/html"

cd "${ROOT_DIR}"
COVERAGE_FILE="${COMBINED_DATA}" \
  run_coverage combine \
    --rcfile="${RCFILE}" \
    --keep \
    "${HOST_DATA}" \
    "${E2E_DATA}"

COVERAGE_FILE="${COMBINED_DATA}" \
  run_coverage report --rcfile="${RCFILE}"
COVERAGE_FILE="${COMBINED_DATA}" \
  run_coverage xml --rcfile="${RCFILE}" \
    -o "${OUTPUT_DIR}/coverage.xml"
COVERAGE_FILE="${COMBINED_DATA}" \
  run_coverage json --rcfile="${RCFILE}" \
    -o "${OUTPUT_DIR}/coverage.json"
COVERAGE_FILE="${COMBINED_DATA}" \
  run_coverage html --rcfile="${RCFILE}" \
    -d "${OUTPUT_DIR}/html"

host_hash_after="$(sha256sum "${HOST_DATA}" | cut -d ' ' -f 1)"
e2e_hash_after="$(sha256sum "${E2E_DATA}" | cut -d ' ' -f 1)"
if [[ "${host_hash_before}" != "${host_hash_after}" || "${e2e_hash_before}" != "${e2e_hash_after}" ]]; then
  printf 'Coverage combine unexpectedly changed an input data file\n' >&2
  exit 1
fi

combined_hash="$(sha256sum "${COMBINED_DATA}" | cut -d ' ' -f 1)"
final_fingerprint="$("${PYTHON_BIN}" "${FINGERPRINT_SCRIPT}")"
require_sha256 "Current" final_source_fingerprint "${final_fingerprint}"
if [[ "${final_fingerprint}" != "${current_fingerprint}" ]]; then
  printf 'Source changed while combined coverage reports were being generated\n' >&2
  exit 1
fi
final_runtime_fingerprint="$(
  env -u PYTHONPATH "${PYTHON_BIN}" "${RUNTIME_FINGERPRINT_SCRIPT}"
)"
require_sha256 "Current" final_runtime_dependency_fingerprint \
  "${final_runtime_fingerprint}"
if [[ "${final_runtime_fingerprint}" != "${current_runtime_fingerprint}" ]]; then
  printf 'Installed dependencies changed while combined reports were being generated\n' >&2
  exit 1
fi

summary_tmp="${OUTPUT_DIR}/summary.txt.tmp.$$"
trap 'rm -f "${summary_tmp}"' EXIT
printf 'summary_version=1\nsource_fingerprint_sha256=%s\nruntime_dependency_sha256=%s\nhost_python_runtime=%s\ne2e_python_runtime=%s\ne2e_runner_image_id=%s\nmysql_image_id=%s\nredis_image_id=%s\nmailpit_image_id=%s\nhost_coverage_sha256=%s\ne2e_coverage_sha256=%s\ncombined_coverage_sha256=%s\n' \
  "${final_fingerprint}" "${final_runtime_fingerprint}" \
  "${host_summary[python_runtime]}" "${e2e_summary[python_runtime]}" \
  "${e2e_summary[e2e_runner_image_id]}" "${e2e_summary[mysql_image_id]}" \
  "${e2e_summary[redis_image_id]}" "${e2e_summary[mailpit_image_id]}" \
  "${host_hash_before}" "${e2e_hash_before}" "${combined_hash}" \
  > "${summary_tmp}"
mv "${summary_tmp}" "${OUTPUT_DIR}/summary.txt"
trap - EXIT

printf 'Combined host and E2E branch coverage under %s\n' "${OUTPUT_DIR}"
