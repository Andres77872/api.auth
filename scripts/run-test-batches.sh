#!/usr/bin/env bash
set -uo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARTIFACT_DIR="${TEST_ARTIFACT_DIR:-${ROOT_DIR}/test-results/host}"
COVERAGE_SHARD_DIR="${ARTIFACT_DIR}/coverage-shards"
COVERAGE_DATA_FILE="${ARTIFACT_DIR}/.coverage"
BATCH_TIMEOUT_SECONDS="${TEST_BATCH_TIMEOUT_SECONDS:-180}"
PYTHON_BIN="${PYTHON_BIN:-${ROOT_DIR}/.venv/bin/python}"
COVERAGE_MEM_LIMIT_MB="${COVERAGE_MEM_LIMIT_MB:-1536}"
COVERAGE_TIMEOUT_SECONDS="${COVERAGE_TIMEOUT_SECONDS:-300}"
PYTEST_MEM_LIMIT_MB="${PYTEST_MEM_LIMIT_MB:-1536}"
PYTEST_TIMEOUT_SECONDS="${PYTEST_TIMEOUT_SECONDS:-60}"
RUN_LOG="${ARTIFACT_DIR}/pytest.log"
SUMMARY_FILE="${ARTIFACT_DIR}/summary.txt"
DEFAULT_LOCK_FILE="/tmp/api-auth-test-workflows.lock"
LOCK_FILE="${TEST_WORKFLOW_LOCK_FILE:-${DEFAULT_LOCK_FILE}}"
FINGERPRINT_SCRIPT="${ROOT_DIR}/scripts/test-source-fingerprint.py"
RUNTIME_FINGERPRINT_SCRIPT="${ROOT_DIR}/scripts/test-runtime-fingerprint.py"
PYTEST_PLUGIN_ARGS=(
  -p pytest_cov.plugin
  -p pytest_asyncio.plugin
  -p anyio.pytest_plugin
)

declare -A REAL_DB_ONLY_TARGETS=(
  ["tests/integration/test_slice22_real_access_resolution.py"]=1
  ["tests/integration/test_slice23_soft_delete_cascades.py"]=1
  ["tests/integration/test_slice24_real_default_groups.py"]=1
)

discover_host_targets() {
  local layer="$1"
  local directory="${ROOT_DIR}/tests/${layer}"
  if [[ ! -d "${directory}" ]]; then
    printf 'Host test layer is missing: %s\n' "${directory}" >&2
    return 2
  fi
  find "${directory}" -type f -name 'test_*.py' -print | LC_ALL=C sort
}

has_real_db_marker() {
  "${PYTHON_BIN}" - "$1" <<'PY'
import ast
import sys
from pathlib import Path


def dotted_name(node):
    if isinstance(node, ast.Call):
        return dotted_name(node.func)
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return tuple(reversed(parts))
    return ()


def contains_real_db_marker(node):
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return any(contains_real_db_marker(item) for item in node.elts)
    return dotted_name(node) == ("pytest", "mark", "real_db")


path = Path(sys.argv[1])
try:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
except (OSError, SyntaxError) as exc:
    print(f"cannot inspect real_db markers in {path}: {exc}", file=sys.stderr)
    raise SystemExit(2)

marked = any(
    contains_real_db_marker(decorator)
    for node in ast.walk(tree)
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    for decorator in node.decorator_list
)
if not marked:
    for statement in tree.body:
        if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
            continue
        targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
        if any(isinstance(target, ast.Name) and target.id == "pytestmark" for target in targets):
            marked = contains_real_db_marker(statement.value)
            if marked:
                break

raise SystemExit(0 if marked else 1)
PY
}

validate_host_junit() {
  "${PYTHON_BIN}" - "$1" <<'PY'
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


report_path = Path(sys.argv[1])
try:
    root = ET.parse(report_path).getroot()
except (OSError, ET.ParseError) as exc:
    print(f"invalid JUnit report {report_path}: {exc}", file=sys.stderr)
    raise SystemExit(2)

cases = list(root.iter("testcase"))
bad = []
for testcase in cases:
    result = next(
        (
            kind
            for kind in ("failure", "error", "skipped")
            if testcase.find(kind) is not None
        ),
        None,
    )
    if result is not None:
        bad.append((str(testcase.get("name") or ""), result))

if bad:
    print(f"host batch contains non-pass JUnit cases: {bad}", file=sys.stderr)
    raise SystemExit(3)
if not cases:
    print(f"host batch has no executed JUnit cases: {report_path}", file=sys.stderr)
    raise SystemExit(4)
print(len(cases))
PY
}

write_totals() {
  printf 'expected_batches=%s\nexpected_completed_batches=%s\nexpected_filtered_batches=%s\ncompleted_batches=%s\nfiltered_batches=%s\nexecuted_tests=%s\nfailed_batches=%s\ncoverage_status=%s\ncertification_status=%s\ncoverage_shards=%s\ncoverage_data_sha256=%s\nsource_fingerprint_end=%s\nsource_stable=%s\nruntime_dependency_fingerprint_end=%s\nruntime_stable=%s\npytest_mem_limit_mb=%s\npytest_timeout_seconds=%s\nbatch_timeout_seconds=%s\ncoverage_mem_limit_mb=%s\ncoverage_timeout_seconds=%s\n' \
    "${expected_batches}" "${expected_completed_batches}" "${expected_filtered_batches}" \
    "${completed_batches}" "${filtered_batches}" "${executed_tests}" "${failed_batches}" \
    "${coverage_status}" "${certification_status}" "${coverage_shards}" \
    "${coverage_data_sha256}" "${source_fingerprint_end}" "${source_stable}" \
    "${runtime_dependency_fingerprint_end}" "${runtime_stable}" \
    "${PYTEST_MEM_LIMIT_MB}" "${PYTEST_TIMEOUT_SECONDS}" "${BATCH_TIMEOUT_SECONDS}" \
    "${COVERAGE_MEM_LIMIT_MB}" "${COVERAGE_TIMEOUT_SECONDS}"
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
    printf '%s must be a canonical positive integer no greater than %s\n' \
      "${name}" "${maximum}" >&2
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

usage() {
  cat <<'EOF'
Usage:
  bash scripts/run-test-batches.sh
  bash scripts/run-test-batches.sh --layer unit|integration|static
  bash scripts/run-test-batches.sh --target tests/<unit|integration|static>/test_file.py

Optional pytest arguments follow `--`, for example:
  bash scripts/run-test-batches.sh --layer unit -- -k password

E2E and real-DB tests intentionally belong to scripts/run-e2e.sh.
EOF
}

if [[ ! -x "${PYTHON_BIN}" ]]; then
  printf 'Python test interpreter is not executable: %s\n' "${PYTHON_BIN}" >&2
  exit 2
fi
if [[ ! -f "${FINGERPRINT_SCRIPT}" || ! -f "${RUNTIME_FINGERPRINT_SCRIPT}" ]]; then
  printf 'Host source or runtime fingerprint helper is unavailable\n' >&2
  exit 2
fi
require_positive_at_most PYTEST_MEM_LIMIT_MB "${PYTEST_MEM_LIMIT_MB}" 1536 || exit 2
require_positive_at_most PYTEST_TIMEOUT_SECONDS "${PYTEST_TIMEOUT_SECONDS}" 60 || exit 2
require_positive_at_most TEST_BATCH_TIMEOUT_SECONDS "${BATCH_TIMEOUT_SECONDS}" 180 || exit 2
require_positive_at_most COVERAGE_MEM_LIMIT_MB "${COVERAGE_MEM_LIMIT_MB}" 1536 || exit 2
require_positive_at_most COVERAGE_TIMEOUT_SECONDS "${COVERAGE_TIMEOUT_SECONDS}" 300 || exit 2

declare -a targets=()
declare -a pytest_args=()
selection="${1:-}"

if [[ "$#" -gt 0 && -z "${1}" ]]; then
  printf 'An explicit empty test-selection argument is not allowed\n' >&2
  exit 2
fi

case "${selection}" in
  ""|--layer|--target)
    ;;
  -h|--help)
    usage
    exit 0
    ;;
  *)
    printf 'Unknown argument: %s\n' "${selection}" >&2
    usage >&2
    exit 2
    ;;
esac

if [[ -z "${selection}" && "${LOCK_FILE}" != "${DEFAULT_LOCK_FILE}" ]]; then
  printf 'Certified full host runs must use the shared workflow lock: %s\n' \
    "${DEFAULT_LOCK_FILE}" >&2
  exit 2
fi
if [[ "${LOCK_FILE}" != "${DEFAULT_LOCK_FILE}" \
   && "${ALLOW_TEST_WORKFLOW_LOCK_OVERRIDE:-0}" != "1" ]]; then
  printf 'Host test lock overrides require ALLOW_TEST_WORKFLOW_LOCK_OVERRIDE=1\n' >&2
  exit 2
fi

runtime_dependency_fingerprint_start="$(
  env -u PYTHONPATH "${PYTHON_BIN}" "${RUNTIME_FINGERPRINT_SCRIPT}"
)"
if [[ ! "${runtime_dependency_fingerprint_start}" =~ ^[0-9a-f]{64}$ ]]; then
  printf 'Could not validate the installed host dependency runtime\n' >&2
  exit 2
fi
python_runtime="$(
  env -u PYTHONPATH "${PYTHON_BIN}" -c \
    'import platform; print(f"{platform.python_implementation()}-{platform.python_version()}")'
)"
if [[ ! "${python_runtime}" =~ ^[A-Za-z0-9._+-]+$ ]]; then
  printf 'Could not attest the host Python runtime\n' >&2
  exit 2
fi

source_fingerprint_pre="$("${PYTHON_BIN}" "${FINGERPRINT_SCRIPT}")"
if [[ ! "${source_fingerprint_pre}" =~ ^[0-9a-f]{64}$ ]]; then
  printf 'Could not fingerprint source before host target discovery\n' >&2
  exit 2
fi

case "${selection}" in
  "")
    selection_scope="full"
    for layer in unit integration static; do
      layer_discovery="$(discover_host_targets "${layer}")"
      discovery_status=$?
      if [[ "${discovery_status}" -ne 0 ]]; then
        exit 2
      fi
      if [[ -n "${layer_discovery}" ]]; then
        mapfile -t layer_targets <<< "${layer_discovery}"
        targets+=("${layer_targets[@]}")
      fi
    done
    ;;
  --layer)
    layer="${2:-}"
    case "${layer}" in
      unit|integration|static)
        selection_scope="layer:${layer}"
        layer_discovery="$(discover_host_targets "${layer}")"
        discovery_status=$?
        if [[ "${discovery_status}" -ne 0 ]]; then
          exit 2
        fi
        if [[ -n "${layer_discovery}" ]]; then
          mapfile -t targets <<< "${layer_discovery}"
        fi
        ;;
      *)
        printf 'Unknown or missing test layer: %s\n' "${layer:-<missing>}" >&2
        usage >&2
        exit 2
        ;;
    esac
    shift 2
    ;;
  --target)
    target="${2:-}"
    case "${target}" in
      tests/unit/test_*.py|tests/integration/test_*.py|tests/static/test_*.py)
        selection_scope="target:${target}"
        targets=("${ROOT_DIR}/${target}")
        ;;
      *)
        printf 'Refusing target outside the host test layers: %s\n' "${target:-<missing>}" >&2
        usage >&2
        exit 2
        ;;
    esac
    shift 2
    ;;
  -h|--help)
    usage
    exit 0
    ;;
  *)
    printf 'Unknown argument: %s\n' "${selection}" >&2
    usage >&2
    exit 2
    ;;
esac

if [[ "${1:-}" == "--" ]]; then
  shift
fi
pytest_args=("$@")

if [[ "${selection_scope}" == "full" && "${#pytest_args[@]}" -ne 0 ]]; then
  printf 'Certified full host runs accept no pytest arguments\n' >&2
  exit 2
fi

if [[ "${#targets[@]}" -eq 0 ]]; then
  printf 'No host test files matched the requested selection\n' >&2
  exit 2
fi

if [[ "${selection_scope}" == "full" && -n "${PYTEST_ADDOPTS:-}" ]]; then
  printf 'PYTEST_ADDOPTS must be empty for a certified full host run\n' >&2
  exit 2
fi

expected_batches="${#targets[@]}"
expected_filtered_batches=0
for absolute_target in "${targets[@]}"; do
  relative_target="${absolute_target#"${ROOT_DIR}/"}"
  if [[ -n "${REAL_DB_ONLY_TARGETS[${relative_target}]+x}" ]]; then
    expected_filtered_batches=$((expected_filtered_batches + 1))
  fi
done
expected_completed_batches=$((expected_batches - expected_filtered_batches))

exec 9>"${LOCK_FILE}"
if ! flock -n 9; then
  printf 'Another api.auth test workflow owns %s; refusing an overlapping run.\n' \
    "${LOCK_FILE}" >&2
  exit 1
fi

mkdir -p "${ARTIFACT_DIR}" "${COVERAGE_SHARD_DIR}"
rm -f "${COVERAGE_SHARD_DIR}"/.coverage.*
rm -f \
  "${COVERAGE_DATA_FILE}" \
  "${ARTIFACT_DIR}"/junit.*.xml \
  "${ARTIFACT_DIR}/coverage.xml" \
  "${ARTIFACT_DIR}/coverage.json"
rm -rf "${ARTIFACT_DIR}/html"
: > "${RUN_LOG}"
: > "${SUMMARY_FILE}"

source_fingerprint_start="$("${PYTHON_BIN}" "${FINGERPRINT_SCRIPT}" 2>>"${RUN_LOG}")"
fingerprint_status=$?
if [[ "${fingerprint_status}" -ne 0 || ! "${source_fingerprint_start}" =~ ^[0-9a-f]{64}$ ]]; then
  printf 'Could not fingerprint the tested source state\n' \
    | tee -a "${RUN_LOG}" "${SUMMARY_FILE}" >&2
  exit 2
fi
if [[ "${source_fingerprint_start}" != "${source_fingerprint_pre}" ]]; then
  printf 'Source changed while host targets were being discovered\n' \
    | tee -a "${RUN_LOG}" "${SUMMARY_FILE}" >&2
  exit 2
fi
printf 'summary_version=1\nworkflow=host\nselection_scope=%s\npytest_args_count=%s\nsource_fingerprint_start=%s\nruntime_dependency_fingerprint_start=%s\npython_runtime=%s\n' \
  "${selection_scope}" "${#pytest_args[@]}" "${source_fingerprint_start}" \
  "${runtime_dependency_fingerprint_start}" "${python_runtime}" \
  >> "${SUMMARY_FILE}"

export PYTHONDONTWRITEBYTECODE=1
export PYTEST_MEM_LIMIT_MB
export PYTEST_TIMEOUT_SECONDS
unset PYTEST_ADDOPTS
unset PYTEST_PLUGINS
unset PYTHONPATH
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1

failed_batches=0
completed_batches=0
filtered_batches=0
executed_tests=0
coverage_status=0
certification_status=0
coverage_shards=0
coverage_data_sha256="missing"
source_fingerprint_end="unavailable"
source_stable=0
runtime_dependency_fingerprint_end="unavailable"
runtime_stable=0
batch_number=0

cd "${ROOT_DIR}"
for absolute_target in "${targets[@]}"; do
  target="${absolute_target#"${ROOT_DIR}/"}"
  batch_number=$((batch_number + 1))

  if [[ ! -f "${absolute_target}" ]]; then
    printf 'MISSING %s\n' "${target}" | tee -a "${RUN_LOG}" "${SUMMARY_FILE}"
    failed_batches=$((failed_batches + 1))
    continue
  fi

  shard="$(printf '%s/.coverage.%04d' "${COVERAGE_SHARD_DIR}" "${batch_number}")"
  batch_report="$(printf '%s/junit.%04d.xml' "${ARTIFACT_DIR}" "${batch_number}")"
  if ! : > "${batch_report}"; then
    printf 'FAIL unable to initialize JUnit report %s\n' "${batch_report}" \
      | tee -a "${RUN_LOG}" "${SUMMARY_FILE}"
    failed_batches=$((failed_batches + 1))
    continue
  fi

  printf '\nBATCH %s\n' "${target}" | tee -a "${RUN_LOG}"
  COVERAGE_FILE="${shard}" \
    timeout --signal=TERM --kill-after=15s "${BATCH_TIMEOUT_SECONDS}" \
    "${PYTHON_BIN}" -m pytest \
      "${target}" \
      "${pytest_args[@]}" \
      -m "not e2e and not real_db and not live_provider" \
      -o addopts= \
      "${PYTEST_PLUGIN_ARGS[@]}" \
      --strict-markers \
      --tb=short \
      -p no:cacheprovider \
      --cov=src \
      --cov-config=.coveragerc \
      --cov-branch \
      --cov-report= \
      --junitxml="${batch_report}" \
      2>&1 | tee -a "${RUN_LOG}"
  batch_status="${PIPESTATUS[0]}"

  if [[ "${batch_status}" -eq 0 ]]; then
    junit_case_count="$(validate_host_junit "${batch_report}" 2>>"${RUN_LOG}")"
    junit_status=$?
    if [[ "${junit_status}" -ne 0 || ! "${junit_case_count}" =~ ^[0-9]+$ ]]; then
      printf 'FAIL(JUNIT_POLICY) %s\n' "${target}" | tee -a "${SUMMARY_FILE}"
      failed_batches=$((failed_batches + 1))
    elif [[ -n "${REAL_DB_ONLY_TARGETS[${target}]+x}" ]]; then
      printf 'FAIL(EXPECTED_REAL_DB_FILTER) %s\n' "${target}" | tee -a "${SUMMARY_FILE}"
      failed_batches=$((failed_batches + 1))
    else
      printf 'PASS %s\n' "${target}" | tee -a "${SUMMARY_FILE}"
      completed_batches=$((completed_batches + 1))
      executed_tests=$((executed_tests + junit_case_count))
    fi
  elif [[ "${batch_status}" -eq 5 ]]; then
    if [[ -n "${REAL_DB_ONLY_TARGETS[${target}]+x}" ]] && has_real_db_marker "${absolute_target}"; then
      printf 'FILTERED %s\n' "${target}" | tee -a "${SUMMARY_FILE}"
      filtered_batches=$((filtered_batches + 1))
    else
      printf 'FAIL(UNEXPECTED_FILTER) %s\n' "${target}" | tee -a "${SUMMARY_FILE}"
      failed_batches=$((failed_batches + 1))
    fi
  else
    printf 'FAIL(%s) %s\n' "${batch_status}" "${target}" | tee -a "${SUMMARY_FILE}"
    failed_batches=$((failed_batches + 1))
  fi
done

if compgen -G "${COVERAGE_SHARD_DIR}/.coverage.*" >/dev/null; then
  coverage_shards="$(
    find "${COVERAGE_SHARD_DIR}" -maxdepth 1 -type f -name '.coverage.*' -printf '.' \
      | wc -c
  )"
  printf '\nCOVERAGE\n' | tee -a "${RUN_LOG}"
  COVERAGE_FILE="${COVERAGE_DATA_FILE}" \
    run_coverage combine --keep "${COVERAGE_SHARD_DIR}" \
    || coverage_status=$?
  COVERAGE_FILE="${COVERAGE_DATA_FILE}" \
    run_coverage report --rcfile=.coveragerc 2>&1 \
    | tee -a "${RUN_LOG}" \
    || coverage_status=$?
  COVERAGE_FILE="${COVERAGE_DATA_FILE}" \
    run_coverage xml --rcfile=.coveragerc -o "${ARTIFACT_DIR}/coverage.xml" \
    || coverage_status=$?
  COVERAGE_FILE="${COVERAGE_DATA_FILE}" \
    run_coverage json --rcfile=.coveragerc -o "${ARTIFACT_DIR}/coverage.json" \
    || coverage_status=$?
  COVERAGE_FILE="${COVERAGE_DATA_FILE}" \
    run_coverage html --rcfile=.coveragerc -d "${ARTIFACT_DIR}/html" \
    || coverage_status=$?
  if [[ -s "${COVERAGE_DATA_FILE}" ]]; then
    coverage_data_sha256="$(sha256sum "${COVERAGE_DATA_FILE}" | cut -d ' ' -f 1)"
  fi
  if [[ ! "${coverage_data_sha256}" =~ ^[0-9a-f]{64}$ ]]; then
    printf 'FAIL combined host coverage data could not be hashed\n' | tee -a "${SUMMARY_FILE}"
    coverage_status=1
    coverage_data_sha256="invalid"
  fi
else
  printf 'FAIL no coverage shards were produced\n' | tee -a "${SUMMARY_FILE}"
  coverage_status=1
fi

if [[ $((completed_batches + filtered_batches + failed_batches)) -ne "${expected_batches}" \
   || "${completed_batches}" -ne "${expected_completed_batches}" \
   || "${filtered_batches}" -ne "${expected_filtered_batches}" \
   || "${executed_tests}" -eq 0 \
   || "${coverage_shards}" -ne "${expected_batches}" ]]; then
  printf 'FAIL(FULL_CERTIFICATION) expected=%s completed=%s/%s filtered=%s/%s failed=%s tests=%s shards=%s\n' \
    "${expected_batches}" "${completed_batches}" "${expected_completed_batches}" \
    "${filtered_batches}" "${expected_filtered_batches}" "${failed_batches}" \
    "${executed_tests}" "${coverage_shards}" | tee -a "${SUMMARY_FILE}"
  certification_status=1
fi

source_fingerprint_end="$("${PYTHON_BIN}" "${FINGERPRINT_SCRIPT}" 2>>"${RUN_LOG}")"
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
  env -u PYTHONPATH "${PYTHON_BIN}" "${RUNTIME_FINGERPRINT_SCRIPT}" 2>>"${RUN_LOG}"
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
