#!/usr/bin/env bash
set -uo pipefail

ARTIFACT_DIR="${E2E_ARTIFACT_DIR:-/test-results/e2e}"
COVERAGE_DATA_FILE="${COVERAGE_FILE:-${ARTIFACT_DIR}/.coverage}"
BATCH_TIMEOUT_SECONDS="${E2E_BATCH_TIMEOUT_SECONDS:-900}"
COVERAGE_TIMEOUT_SECONDS="${E2E_COVERAGE_TIMEOUT_SECONDS:-300}"
PYTEST_MEM_LIMIT_MB="${PYTEST_MEM_LIMIT_MB:-1536}"
PYTEST_TIMEOUT_SECONDS="${PYTEST_TIMEOUT_SECONDS:-60}"
RUN_LOG="${ARTIFACT_DIR}/pytest.log"
SUMMARY_FILE="${ARTIFACT_DIR}/summary.txt"
FINGERPRINT_SCRIPT="scripts/test-source-fingerprint.py"
RUNTIME_FINGERPRINT_SCRIPT="scripts/test-runtime-fingerprint.py"
REAL_DB_DISCOVERY_SCRIPT="scripts/discover-real-db-targets.py"
PYTEST_PLUGIN_ARGS=(
  -p pytest_cov.plugin
  -p pytest_asyncio.plugin
  -p anyio.pytest_plugin
)

validate_skip_report() {
  python - "$1" "$2" <<'PY'
import os
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path


report_path = Path(sys.argv[1])
target = sys.argv[2]


def env_truthy(name):
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def normalized_reason(value):
    reason = str(value or "").strip()
    if reason.startswith("Skipped: "):
        reason = reason[len("Skipped: "):]
    return reason


optional_specs = {
    "tests/e2e/test_patreon_link_mailpit.py": (
        "RUN_PATREON_LOCAL_E2E",
        "test_fake_patreon_api_mailpit_proof_loop_never_issues_local_session",
        "optional Patreon local E2E disabled; set RUN_PATREON_LOCAL_E2E=1 to run",
    ),
    "tests/e2e/test_patreon_live_opt_in.py": (
        "RUN_PATREON_E2E",
        "test_live_patreon_manual_resync_and_s2s_read_are_opt_in_only",
        "live Patreon smoke disabled; set RUN_PATREON_E2E=1 to run",
    ),
    "tests/e2e/test_stripe_live_opt_in.py": (
        "RUN_STRIPE_E2E",
        "test_live_stripe_checkout_and_portal_are_explicit_opt_in_only",
        "live Stripe smoke disabled; set RUN_STRIPE_E2E=true to run",
    ),
}

expected = []
spec = optional_specs.get(target)
if spec is not None and not env_truthy(spec[0]):
    expected.append((spec[1], spec[2]))

try:
    root = ET.parse(report_path).getroot()
except (OSError, ET.ParseError) as exc:
    print(f"invalid JUnit report {report_path}: {exc}")
    raise SystemExit(2)

actual = []
case_count = 0
result_errors = []
for testcase in root.iter("testcase"):
    case_count += 1
    if testcase.find("failure") is not None or testcase.find("error") is not None:
        result_errors.append(str(testcase.get("name") or ""))
    skipped = testcase.find("skipped")
    if skipped is None:
        continue
    actual.append(
        (
            str(testcase.get("name") or ""),
            normalized_reason(skipped.get("message") or skipped.text),
        )
    )

if result_errors:
    print(f"JUnit report contains failed/error cases despite a successful pytest status: {result_errors}")
    raise SystemExit(4)

expected_counter = Counter(expected)
actual_counter = Counter(actual)
if actual_counter != expected_counter:
    missing = list((expected_counter - actual_counter).elements())
    unexpected = list((actual_counter - expected_counter).elements())
    if missing:
        print(f"missing expected skips: {missing}")
    if unexpected:
        print(f"unexpected skips or reasons: {unexpected}")
    raise SystemExit(3)

description = "none"
if actual:
    description = "; ".join(f"{name}: {reason}" for name, reason in actual)
print(f"{case_count}|{len(actual)}|{description.replace('|', '/')}")
PY
}

write_totals() {
  printf 'expected_batches=%s\nexpected_completed_batches=%s\nexpected_filtered_batches=%s\ncompleted_batches=%s\nfiltered_batches=%s\nexecuted_tests=%s\nexpected_skip_batches=%s\nexpected_skipped_tests=%s\nfailed_batches=%s\ncoverage_status=%s\ncertification_status=%s\ncoverage_data_sha256=%s\nsource_fingerprint_end=%s\nsource_stable=%s\nruntime_dependency_fingerprint_end=%s\nruntime_stable=%s\npytest_mem_limit_mb=%s\npytest_timeout_seconds=%s\nbatch_timeout_seconds=%s\ncoverage_timeout_seconds=%s\n' \
    "${expected_batches}" "${expected_completed_batches}" "${expected_filtered_batches}" \
    "${completed_batches}" "${filtered_batches}" "${executed_tests}" \
    "${expected_skip_batches}" "${expected_skipped_tests}" "${failed_batches}" \
    "${coverage_status}" "${certification_status}" "${coverage_data_sha256}" \
    "${source_fingerprint_end}" "${source_stable}" \
    "${runtime_dependency_fingerprint_end}" "${runtime_stable}" \
    "${PYTEST_MEM_LIMIT_MB}" "${PYTEST_TIMEOUT_SECONDS}" "${BATCH_TIMEOUT_SECONDS}" \
    "${COVERAGE_TIMEOUT_SECONDS}"
}

require_positive_at_most() {
  local name="$1"
  local value="$2"
  local maximum="$3"
  local value_length="${#value}"
  local maximum_length="${#maximum}"
  if [[ ! "${value}" =~ ^[1-9][0-9]*$ \
     || "${value_length}" -gt "${maximum_length}" \
     || ( "${value_length}" -eq "${maximum_length}" && "${value}" > "${maximum}" ) ]]; then
    printf 'run-e2e-batches: %s must be a canonical positive integer no greater than %s\n' \
      "${name}" "${maximum}" >&2
    return 2
  fi
}

run_coverage() {
  timeout --signal=TERM --kill-after=15s \
    "${COVERAGE_TIMEOUT_SECONDS}" python -m coverage "$@"
}

failed_batches=0
completed_batches=0
filtered_batches=0
executed_tests=0
expected_skip_batches=0
expected_skipped_tests=0
coverage_status=0
certification_status=0
coverage_data_sha256="missing"
expected_batches=0
expected_completed_batches=0
expected_filtered_batches=0
source_fingerprint_end="unavailable"
source_stable=0
runtime_dependency_fingerprint_end="unavailable"
runtime_stable=0

declare -a targets=()
declare -a pytest_args=()
requested_target=""

require_positive_at_most PYTEST_MEM_LIMIT_MB "${PYTEST_MEM_LIMIT_MB}" 1536 || exit 2
require_positive_at_most PYTEST_TIMEOUT_SECONDS "${PYTEST_TIMEOUT_SECONDS}" 60 || exit 2
require_positive_at_most E2E_BATCH_TIMEOUT_SECONDS "${BATCH_TIMEOUT_SECONDS}" 900 || exit 2
require_positive_at_most E2E_COVERAGE_TIMEOUT_SECONDS "${COVERAGE_TIMEOUT_SECONDS}" 300 || exit 2

if [[ "$#" -gt 0 && "${1}" == "--target" ]]; then
  selection_scope="target"
  if [[ -z "${2:-}" ]]; then
    printf 'run-e2e-batches: --target requires a test file under tests/\n' >&2
    exit 2
  fi
  case "${2}" in
    tests/*)
      requested_target="${2}"
      ;;
    *)
      printf 'run-e2e-batches: refusing target outside tests/: %s\n' "${2}" >&2
      exit 2
      ;;
  esac
  shift 2
  if [[ "${1:-}" == "--" ]]; then
    shift
  fi
  pytest_args=("$@")
elif [[ "$#" -eq 0 ]]; then
  selection_scope="full"
  if [[ -n "${PYTEST_ADDOPTS:-}" ]]; then
    printf 'run-e2e-batches: PYTEST_ADDOPTS must be empty for a certified full run\n' >&2
    exit 2
  fi
  pytest_args=()
else
  printf 'run-e2e-batches: full runs accept no pytest arguments; use --target tests/... -- <pytest args>\n' >&2
  exit 2
fi

for image_variable in \
  E2E_RUNNER_IMAGE_ID \
  E2E_MYSQL_IMAGE_ID \
  E2E_REDIS_IMAGE_ID \
  E2E_MAILPIT_IMAGE_ID
do
  if [[ ! "${!image_variable:-}" =~ ^sha256:[0-9a-f]{64}$ ]]; then
    printf 'run-e2e-batches: %s is missing or invalid\n' "${image_variable}" >&2
    exit 2
  fi
done

expected_outer_fingerprint="${E2E_EXPECTED_SOURCE_FINGERPRINT:-}"
if [[ ! "${expected_outer_fingerprint}" =~ ^[0-9a-f]{64}$ ]]; then
  printf 'run-e2e-batches: wrapper source fingerprint is missing or invalid\n' >&2
  exit 2
fi
source_fingerprint_pre="$(python "${FINGERPRINT_SCRIPT}")"
if [[ "${source_fingerprint_pre}" != "${expected_outer_fingerprint}" ]]; then
  printf 'run-e2e-batches: source does not match the pre-build wrapper fingerprint\n' >&2
  exit 2
fi

if [[ "${selection_scope}" == "target" ]]; then
  targets=("${requested_target}")
else
  if [[ ! -d tests/e2e || ! -d tests/integration ]]; then
    printf 'run-e2e-batches: required test directories are missing\n' >&2
    exit 2
  fi
  e2e_discovery="$(find tests/e2e -type f -name 'test_*.py' -print | LC_ALL=C sort)"
  e2e_discovery_status=$?
  if [[ "${e2e_discovery_status}" -ne 0 ]]; then
    printf 'run-e2e-batches: recursive E2E target discovery failed (%s)\n' \
      "${e2e_discovery_status}" >&2
    exit 2
  fi
  if [[ -n "${e2e_discovery}" ]]; then
    mapfile -t targets <<< "${e2e_discovery}"
  fi
  real_db_discovery="$(
    env -u PYTHONPATH -u PYTEST_PLUGINS \
      PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
      python "${REAL_DB_DISCOVERY_SCRIPT}"
  )"
  discovery_status=$?
  if [[ "${discovery_status}" -ne 0 ]]; then
    printf 'run-e2e-batches: real_db target discovery failed (%s)\n' \
      "${discovery_status}" >&2
    exit 2
  fi
  if [[ -n "${real_db_discovery}" ]]; then
    mapfile -t real_db_targets <<< "${real_db_discovery}"
    targets+=("${real_db_targets[@]}")
  fi
fi

if [[ "${#targets[@]}" -eq 0 ]]; then
  printf 'run-e2e-batches: no E2E or real-DB integration targets were found\n' >&2
  exit 2
fi

source_fingerprint_discovery_end="$(python "${FINGERPRINT_SCRIPT}")"
if [[ "${source_fingerprint_discovery_end}" != "${source_fingerprint_pre}" ]]; then
  printf 'run-e2e-batches: source changed while E2E targets were being discovered\n' >&2
  exit 2
fi

runtime_dependency_fingerprint_start="$(
  env -u PYTHONPATH python "${RUNTIME_FINGERPRINT_SCRIPT}"
)"
if [[ ! "${runtime_dependency_fingerprint_start}" =~ ^[0-9a-f]{64}$ ]]; then
  printf 'run-e2e-batches: could not validate installed dependency versions\n' >&2
  exit 2
fi
python_runtime="$(
  env -u PYTHONPATH python -c \
    'import platform; print(f"{platform.python_implementation()}-{platform.python_version()}")'
)"
if [[ ! "${python_runtime}" =~ ^[A-Za-z0-9._+-]+$ ]]; then
  printf 'run-e2e-batches: could not attest the Python runtime\n' >&2
  exit 2
fi

mkdir -p "${ARTIFACT_DIR}"
rm -f \
  "${ARTIFACT_DIR}"/junit.*.xml \
  "${ARTIFACT_DIR}/coverage.xml" \
  "${ARTIFACT_DIR}/coverage.json"
rm -rf "${ARTIFACT_DIR}/html"
: > "${RUN_LOG}"
: > "${SUMMARY_FILE}"

expected_batches="${#targets[@]}"
expected_completed_batches="${expected_batches}"
source_fingerprint_start="${source_fingerprint_discovery_end}"

printf 'summary_version=1\nworkflow=e2e\nselection_scope=%s\npytest_args_count=%s\nsource_fingerprint_start=%s\nruntime_dependency_fingerprint_start=%s\npython_runtime=%s\ne2e_runner_image_id=%s\nmysql_image_id=%s\nredis_image_id=%s\nmailpit_image_id=%s\n' \
  "${selection_scope}" "${#pytest_args[@]}" "${source_fingerprint_start}" \
  "${runtime_dependency_fingerprint_start}" "${python_runtime}" \
  "${E2E_RUNNER_IMAGE_ID}" "${E2E_MYSQL_IMAGE_ID}" "${E2E_REDIS_IMAGE_ID}" \
  "${E2E_MAILPIT_IMAGE_ID}" \
  | tee -a "${SUMMARY_FILE}"

# A caller's environment must not inject -k/-m/--ignore filters into a run
# certified as full. Only the suite's pinned plugins are loaded; project
# conftests still load normally, while ambient entry points and PYTEST_PLUGINS
# cannot modify collection.
unset PYTEST_ADDOPTS
unset PYTEST_PLUGINS
unset PYTHONPATH
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
export PYTEST_MEM_LIMIT_MB
export PYTEST_TIMEOUT_SECONDS

export COVERAGE_FILE="${COVERAGE_DATA_FILE}"
run_coverage erase 2>&1 | tee -a "${RUN_LOG}"
coverage_erase_status="${PIPESTATUS[0]}"
if [[ "${coverage_erase_status}" -ne 0 ]]; then
  printf 'FAIL(%s) cumulative coverage erase\n' "${coverage_erase_status}" \
    | tee -a "${SUMMARY_FILE}"
  coverage_status="${coverage_erase_status}"
  write_totals | tee -a "${SUMMARY_FILE}"
  exit 1
fi

batch_number=0

for target in "${targets[@]}"; do
  batch_number=$((batch_number + 1))
  if [[ ! -f "${target}" ]]; then
    printf 'MISSING %s\n' "${target}" | tee -a "${RUN_LOG}" "${SUMMARY_FILE}"
    failed_batches=$((failed_batches + 1))
    continue
  fi

  marker_args=()
  if [[ "${target}" == tests/integration/* ]]; then
    marker_args=(-m real_db)
  fi
  batch_report="$(printf '%s/junit.%04d.xml' "${ARTIFACT_DIR}" "${batch_number}")"
  if ! : > "${batch_report}"; then
    printf 'FAIL unable to initialize JUnit report %s\n' "${batch_report}" \
      | tee -a "${RUN_LOG}" "${SUMMARY_FILE}"
    failed_batches=$((failed_batches + 1))
    continue
  fi

  printf '\nBATCH %s\n' "${target}" | tee -a "${RUN_LOG}"
  timeout --signal=TERM --kill-after=15s "${BATCH_TIMEOUT_SECONDS}" \
    python -m pytest \
      "${target}" \
      "${marker_args[@]}" \
      -o addopts= \
      "${PYTEST_PLUGIN_ARGS[@]}" \
      --strict-markers \
      --tb=short \
      -p no:cacheprovider \
      --cov=src \
      --cov-config=.coveragerc \
      --cov-branch \
      --cov-append \
      --cov-report= \
      --junitxml="${batch_report}" \
      "${pytest_args[@]}" \
      2>&1 | tee -a "${RUN_LOG}"
  batch_status="${PIPESTATUS[0]}"

  if [[ "${batch_status}" -eq 0 ]]; then
    skip_policy_output="$(validate_skip_report "${batch_report}" "${target}" 2>&1)"
    skip_policy_status=$?
    printf 'SKIP_POLICY %s %s\n' "${target}" "${skip_policy_output}" | tee -a "${RUN_LOG}"
    if [[ "${skip_policy_status}" -ne 0 ]]; then
      printf 'FAIL(SKIP_POLICY) %s\n' "${target}" | tee -a "${SUMMARY_FILE}"
      failed_batches=$((failed_batches + 1))
      continue
    fi

    IFS='|' read -r case_count skip_count skip_description <<< "${skip_policy_output}"
    if [[ ! "${case_count}" =~ ^[0-9]+$ || ! "${skip_count}" =~ ^[0-9]+$ ]]; then
      printf 'FAIL(SKIP_POLICY_OUTPUT) %s\n' "${target}" | tee -a "${SUMMARY_FILE}"
      failed_batches=$((failed_batches + 1))
      continue
    fi

    completed_batches=$((completed_batches + 1))
    executed_tests=$((executed_tests + case_count))
    if [[ "${skip_count}" -gt 0 ]]; then
      printf 'EXPECTED_SKIP(%s) %s\n' "${skip_count}" "${target}" | tee -a "${SUMMARY_FILE}"
      expected_skip_batches=$((expected_skip_batches + 1))
      expected_skipped_tests=$((expected_skipped_tests + skip_count))
    else
      printf 'PASS %s\n' "${target}" | tee -a "${SUMMARY_FILE}"
    fi
  elif [[ "${batch_status}" -eq 5 && "${selection_scope}" != "full" && "${#pytest_args[@]}" -gt 0 ]]; then
    printf 'FILTERED %s\n' "${target}" | tee -a "${SUMMARY_FILE}"
    filtered_batches=$((filtered_batches + 1))
  else
    printf 'FAIL(%s) %s\n' "${batch_status}" "${target}" | tee -a "${SUMMARY_FILE}"
    failed_batches=$((failed_batches + 1))
  fi
done

if [[ -f "${COVERAGE_DATA_FILE}" ]]; then
  printf '\nCOVERAGE\n' | tee -a "${RUN_LOG}"
  run_coverage report --rcfile=.coveragerc 2>&1 | tee -a "${RUN_LOG}" \
    || coverage_status=$?
  run_coverage xml --rcfile=.coveragerc -o "${ARTIFACT_DIR}/coverage.xml" \
    || coverage_status=$?
  run_coverage json --rcfile=.coveragerc -o "${ARTIFACT_DIR}/coverage.json" \
    || coverage_status=$?
  run_coverage html --rcfile=.coveragerc -d "${ARTIFACT_DIR}/html" \
    || coverage_status=$?
  coverage_data_sha256="$(sha256sum "${COVERAGE_DATA_FILE}" | cut -d ' ' -f 1)"
  if [[ ! "${coverage_data_sha256}" =~ ^[0-9a-f]{64}$ ]]; then
    printf 'FAIL cumulative coverage data could not be hashed\n' | tee -a "${SUMMARY_FILE}"
    coverage_status=1
    coverage_data_sha256="invalid"
  fi
else
  printf 'FAIL no cumulative coverage data was produced\n' | tee -a "${SUMMARY_FILE}"
  coverage_status=1
fi

if [[ "${selection_scope}" == "full" ]]; then
  if [[ "${completed_batches}" -ne "${expected_batches}" || "${filtered_batches}" -ne 0 || "${executed_tests}" -eq 0 ]]; then
    printf 'FAIL(FULL_CERTIFICATION) expected=%s completed=%s filtered=%s executed_tests=%s\n' \
      "${expected_batches}" "${completed_batches}" "${filtered_batches}" "${executed_tests}" \
      | tee -a "${SUMMARY_FILE}"
    certification_status=1
  fi
fi

source_fingerprint_end="$(python "${FINGERPRINT_SCRIPT}" 2>>"${RUN_LOG}")"
fingerprint_status=$?
if [[ "${fingerprint_status}" -ne 0 || "${source_fingerprint_end}" != "${source_fingerprint_start}" ]]; then
  printf 'FAIL(SOURCE_STATE_CHANGED) start=%s end=%s\n' \
    "${source_fingerprint_start}" "${source_fingerprint_end:-unavailable}" \
    | tee -a "${SUMMARY_FILE}"
  certification_status=1
else
  source_stable=1
fi

runtime_dependency_fingerprint_end="$(
  env -u PYTHONPATH python "${RUNTIME_FINGERPRINT_SCRIPT}" 2>>"${RUN_LOG}"
)"
runtime_fingerprint_status=$?
if [[ "${runtime_fingerprint_status}" -ne 0 \
   || "${runtime_dependency_fingerprint_end}" != "${runtime_dependency_fingerprint_start}" ]]; then
  printf 'FAIL(RUNTIME_STATE_CHANGED) start=%s end=%s\n' \
    "${runtime_dependency_fingerprint_start}" \
    "${runtime_dependency_fingerprint_end:-unavailable}" \
    | tee -a "${SUMMARY_FILE}"
  certification_status=1
else
  runtime_stable=1
fi

write_totals | tee -a "${SUMMARY_FILE}"

if [[ "${failed_batches}" -ne 0 || "${coverage_status}" -ne 0 || "${certification_status}" -ne 0 ]]; then
  exit 1
fi
