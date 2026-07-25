"""Static invariants for the resource-safe host and Docker test workflows."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PATH = ROOT / "docker-compose.test.yml"
DOCKERFILE_PATH = ROOT / "Dockerfile.e2e"
RUNNER_PATH = ROOT / "scripts" / "run-e2e.sh"
BATCH_RUNNER_PATH = ROOT / "scripts" / "run-e2e-batches.sh"
HOST_BATCH_RUNNER_PATH = ROOT / "scripts" / "run-test-batches.sh"


def _service_block(compose: str, service: str) -> str:
    match = re.search(
        rf"(?ms)^  {re.escape(service)}:\n(?P<body>.*?)(?=^  [a-zA-Z0-9_-]+:\n|^volumes:\n|\Z)",
        compose,
    )
    assert match is not None, f"missing Compose service {service}"
    return match.group("body")


def test_compose_mounts_every_canonical_schema_file():
    compose = COMPOSE_PATH.read_text(encoding="utf-8")
    schema_files = sorted(
        path.relative_to(ROOT).as_posix()
        for family in ("tables", "stored_procedures", "triggers")
        for path in (ROOT / "schemas" / family).glob("*.sql")
    )

    missing = [relative for relative in schema_files if f"./{relative}:" not in compose]
    assert missing == [], f"fresh Docker schema omits canonical SQL: {missing}"


def test_every_e2e_service_has_hard_resource_limits():
    compose = COMPOSE_PATH.read_text(encoding="utf-8")
    for service in ("mysql-test", "redis-test", "mailpit-test", "e2e-runner"):
        block = _service_block(compose, service)
        assert "mem_limit:" in block
        assert "memswap_limit:" in block
        assert "cpus:" in block
        assert "pids_limit:" in block


def test_compose_is_project_scoped_and_does_not_publish_test_ports():
    compose = COMPOSE_PATH.read_text(encoding="utf-8")
    assert "container_name:" not in compose
    assert "\n    ports:" not in compose
    assert "mysql-e2e-data:/var/lib/mysql" in compose


def test_e2e_images_are_explicitly_version_pinned():
    compose = COMPOSE_PATH.read_text(encoding="utf-8")
    dockerfile = DOCKERFILE_PATH.read_text(encoding="utf-8")

    expected_images = {
        "mysql-test": "mysql:8.0.46-oraclelinux9",
        "redis-test": "redis:7.4.9-alpine3.21",
        "mailpit-test": "axllent/mailpit:v1.30.5",
    }
    for service, image in expected_images.items():
        assert f"image: {image}" in _service_block(compose, service)

    assert dockerfile.startswith("FROM python:3.12.13-slim-bookworm\n")
    assert "image: api-auth-e2e:py312" in _service_block(compose, "e2e-runner")
    assert ":latest" not in compose


def test_container_environment_cannot_silently_skip_required_infrastructure():
    compose = COMPOSE_PATH.read_text(encoding="utf-8")
    runner = _service_block(compose, "e2e-runner")
    assert 'E2E_REQUIRE_REAL_INFRA: "true"' in runner
    assert 'PYTEST_DOTENV_OVERRIDE: "false"' in runner
    assert 'E2E_USE_COMPOSE_MAILPIT: "true"' in runner
    assert 'RUN_PATREON_E2E: "false"' in runner
    assert 'RUN_STRIPE_E2E: "false"' in runner


def test_wrapper_always_tears_down_volumes_and_runs_one_shot_runner():
    script = RUNNER_PATH.read_text(encoding="utf-8")
    assert "trap cleanup EXIT" in script
    assert "down -v --remove-orphans" in script
    assert "--renew-anon-volumes" in script
    assert "--rm" in script
    assert "--no-deps" in script
    assert 'bash scripts/run-e2e-batches.sh "$@"' in script
    assert 'teardown_status=$?' in script
    assert '"${status}" -eq 0 && "${teardown_status}" -ne 0' in script
    assert "wrapper_status=%s" in script
    assert "rm -f \\" in script
    assert '"${ARTIFACT_DIR}/docker-compose.log"' in script
    assert '"${ARTIFACT_DIR}/summary.txt"' in script
    assert '"${ARTIFACT_DIR}/.coverage"' in script


def test_wrapper_attests_source_before_build_and_again_before_and_after_execution():
    script = RUNNER_PATH.read_text(encoding="utf-8")

    initial = script.index('E2E_EXPECTED_SOURCE_FINGERPRINT="$(')
    build = script.index("compose build e2e-runner")
    before_run = script.index('pre_run_fingerprint="$(')
    run = script.index("compose run \\")
    cleanup_check = script.index('final_fingerprint="$(')

    assert initial < build < before_run < run
    assert cleanup_check < script.index("compose down -v", cleanup_check)
    assert "-e \"E2E_EXPECTED_SOURCE_FINGERPRINT=" in script
    for service in ("e2e-runner", "mysql-test", "redis-test", "mailpit-test"):
        assert f"compose_image_id {service}" in script
    assert "compose_image_id e2e-runner api-auth-e2e:py312" in script
    assert "docker image inspect --format '{{.Id}}'" in script
    for variable in (
        "E2E_RUNNER_IMAGE_ID",
        "E2E_MYSQL_IMAGE_ID",
        "E2E_REDIS_IMAGE_ID",
        "E2E_MAILPIT_IMAGE_ID",
    ):
        assert f'-e "{variable}=${{{variable}}}"' in script


def test_batch_runner_is_serial_and_produces_cumulative_branch_coverage():
    script = BATCH_RUNNER_PATH.read_text(encoding="utf-8")

    assert "find tests/e2e -type f -name 'test_*.py'" in script
    assert 'REAL_DB_DISCOVERY_SCRIPT="scripts/discover-real-db-targets.py"' in script
    assert 'python "${REAL_DB_DISCOVERY_SCRIPT}"' in script
    assert "ast.parse" not in script
    assert "grep -q '@pytest\\.mark\\.real_db'" not in script
    assert "--cov-append" in script
    assert "--cov-branch" in script
    assert "coverage.xml" in script
    assert "coverage.json" in script
    assert "ThreadPool" not in script
    assert "xdist" not in script


def test_e2e_batch_runner_fails_coverage_erase_and_labels_selection_scope():
    script = BATCH_RUNNER_PATH.read_text(encoding="utf-8")
    erase = script.index("run_coverage erase")
    erase_status = script.index('coverage_erase_status="${PIPESTATUS[0]}"')
    erase_failure = script.index('if [[ "${coverage_erase_status}" -ne 0 ]]')

    assert erase < erase_status < erase_failure
    assert 'selection_scope="target"' in script
    assert 'selection_scope="full"' in script
    assert "selection_scope=%s\\npytest_args_count=%s" in script
    assert "write_totals" in script
    assert "expected_completed_batches=%s" in script
    assert "expected_filtered_batches=%s" in script
    assert "certification_status=%s" in script
    assert "coverage_data_sha256=%s" in script


def test_e2e_full_certification_cannot_be_filtered_by_args_or_environment():
    wrapper = RUNNER_PATH.read_text(encoding="utf-8")
    script = BATCH_RUNNER_PATH.read_text(encoding="utf-8")

    for source in (wrapper, script):
        assert "Full E2E runs accept no pytest arguments" in source or (
            "full runs accept no pytest arguments" in source
        )
        assert "PYTEST_ADDOPTS" in source

    assert 'elif [[ "$#" -eq 0 ]]; then' in script
    assert 'selection_scope="filtered"' not in script
    assert '"${selection_scope}" != "full"' in script
    assert "unset PYTEST_ADDOPTS" in script
    assert "-o addopts=" in script
    assert "FAIL(FULL_CERTIFICATION)" in script
    assert 'completed_batches}" -ne "${expected_batches}' in script
    assert 'filtered_batches}" -ne 0' in script
    assert "full runs accept no pytest arguments" in script


def test_e2e_batch_runner_enforces_fresh_junit_skip_allowlist():
    script = BATCH_RUNNER_PATH.read_text(encoding="utf-8")

    assert "validate_skip_report" in script
    assert 'batch_report="$(printf \'%s/junit.%04d.xml\'' in script
    assert 'if ! : > "${batch_report}"' in script
    assert '--junitxml="${batch_report}"' in script
    assert "actual_counter != expected_counter" in script
    assert "missing expected skips:" in script
    assert "unexpected skips or reasons:" in script
    assert "EXPECTED_SKIP(%s)" in script
    assert "expected_skip_batches=%s" in script
    assert "expected_skipped_tests=%s" in script

    for flag, target in (
        ("RUN_PATREON_LOCAL_E2E", "tests/e2e/test_patreon_link_mailpit.py"),
        ("RUN_PATREON_E2E", "tests/e2e/test_patreon_live_opt_in.py"),
        ("RUN_STRIPE_E2E", "tests/e2e/test_stripe_live_opt_in.py"),
    ):
        assert flag in script
        assert target in script


def test_optional_provider_tests_skip_only_when_safely_disabled():
    patreon_local = (ROOT / "tests/e2e/test_patreon_link_mailpit.py").read_text(encoding="utf-8")
    patreon_live = (ROOT / "tests/e2e/test_patreon_live_opt_in.py").read_text(encoding="utf-8")
    stripe_live = (ROOT / "tests/e2e/test_stripe_live_opt_in.py").read_text(encoding="utf-8")

    helper = patreon_local[
        patreon_local.index("def _mailpit_server()"):
        patreon_local.index("\n\nclass _FakePatreonAPIHandler")
    ]
    assert "pytest.skip" not in helper
    assert "optional Patreon local E2E disabled" in patreon_local

    for source, provider in ((patreon_live, "Patreon"), (stripe_live, "Stripe")):
        assert "@pytest.mark.live_provider" in source
        assert f"live {provider} smoke disabled" in source
        assert f"live {provider} smoke was enabled but required env vars are missing" in source
        assert "pytest.fail(" in source


def test_coverage_configuration_tracks_all_source_with_branches():
    config = (ROOT / ".coveragerc").read_text(encoding="utf-8")
    assert "branch = True" in config
    assert re.search(r"(?m)^source =\s*$\n\s+src$", config)
    assert "relative_files = True" in config


def test_host_batch_runner_discovers_only_host_layers_and_runs_files_serially():
    script = HOST_BATCH_RUNNER_PATH.read_text(encoding="utf-8")

    assert "discover_host_targets()" in script
    assert "find \"${directory}\" -type f -name 'test_*.py'" in script
    assert "for layer in unit integration static" in script
    assert "discover_host_targets e2e" not in script
    assert "unit|integration|static)" in script
    assert "tests/e2e/test_*.py|" not in script

    loop = 'for absolute_target in "${targets[@]}"; do'
    invocation = '"${PYTHON_BIN}" -m pytest'
    loop_start = script.rindex(loop)
    loop_end = script.index("\ndone\n", loop_start)
    assert script.count(invocation) == 1
    assert loop_start < script.index(invocation) < loop_end
    assert "ThreadPool" not in script
    assert "xdist" not in script
    assert "/tmp/api-auth-test-workflows.lock" in script
    assert "flock -n 9" in script


def test_host_batch_runner_cannot_collect_e2e_real_db_or_live_provider_tests():
    script = HOST_BATCH_RUNNER_PATH.read_text(encoding="utf-8")
    forwarded_args = '"${pytest_args[@]}"'
    exclusion = '-m "not e2e and not real_db and not live_provider"'

    assert exclusion in script
    assert script.index(forwarded_args) < script.index(exclusion)
    assert "E2E and real-DB tests intentionally belong to scripts/run-e2e.sh." in script
    assert "REAL_DB_ONLY_TARGETS" in script
    assert "FAIL(UNEXPECTED_FILTER)" in script
    assert "has_real_db_marker" in script


def test_host_batch_runner_enforces_memory_and_nested_timeouts():
    script = HOST_BATCH_RUNNER_PATH.read_text(encoding="utf-8")
    conftest = (ROOT / "tests/conftest.py").read_text(encoding="utf-8")

    assert 'BATCH_TIMEOUT_SECONDS="${TEST_BATCH_TIMEOUT_SECONDS:-180}"' in script
    assert 'PYTEST_MEM_LIMIT_MB="${PYTEST_MEM_LIMIT_MB:-1536}"' in script
    assert 'PYTEST_TIMEOUT_SECONDS="${PYTEST_TIMEOUT_SECONDS:-60}"' in script
    assert "require_positive_at_most PYTEST_MEM_LIMIT_MB" in script
    assert "require_positive_at_most PYTEST_TIMEOUT_SECONDS" in script
    assert "require_positive_at_most TEST_BATCH_TIMEOUT_SECONDS" in script
    assert 'value_length="${#value}"' in script
    assert 'maximum_length="${#maximum}"' in script
    assert 'COVERAGE_MEM_LIMIT_MB="${COVERAGE_MEM_LIMIT_MB:-1536}"' in script
    assert 'current_soft_kib="$(ulimit -S -v)"' in script
    assert 'current_hard_kib="$(ulimit -H -v)"' in script
    assert 'ulimit -S -v "${effective_kib}"' in script
    assert 'COVERAGE_TIMEOUT_SECONDS="${COVERAGE_TIMEOUT_SECONDS:-300}"' in script
    assert "timeout --foreground" not in script
    assert 'timeout --signal=TERM --kill-after=15s \\' in script
    assert (
        'timeout --signal=TERM --kill-after=15s '
        '"${BATCH_TIMEOUT_SECONDS}"'
    ) in script
    for key in (
        "pytest_mem_limit_mb",
        "pytest_timeout_seconds",
        "batch_timeout_seconds",
        "coverage_mem_limit_mb",
        "coverage_timeout_seconds",
    ):
        assert f"{key}=%s" in script
    assert "_RUNNER_SAFETY_ENV" in conftest
    assert '"PYTEST_MEM_LIMIT_MB"' in conftest
    assert '"PYTEST_TIMEOUT_SECONDS"' in conftest
    assert "os.environ[_safety_name] = _safety_value" in conftest


def test_host_batch_runner_uses_unique_shards_then_combines_coverage():
    script = HOST_BATCH_RUNNER_PATH.read_text(encoding="utf-8")
    loop = 'for absolute_target in "${targets[@]}"; do'
    loop_end = script.index("\ndone\n", script.rindex(loop))
    combine = 'run_coverage combine --keep "${COVERAGE_SHARD_DIR}"'

    assert "batch_number=$((batch_number + 1))" in script
    assert (
        "shard=\"$(printf '%s/.coverage.%04d' "
        '"${COVERAGE_SHARD_DIR}" "${batch_number}")"'
    ) in script
    assert 'COVERAGE_FILE="${shard}" \\' in script
    assert "--cov-branch" in script
    assert script.index(combine) > loop_end
    assert "coverage.xml" in script
    assert "coverage.json" in script
    assert '"${ARTIFACT_DIR}/html"' in script
    assert '--junitxml="${batch_report}"' in script
    assert "validate_host_junit" in script
    assert "host batch contains non-pass JUnit cases" in script
    assert "coverage_shards=%s" in script
    assert "coverage_data_sha256=%s" in script


def test_host_and_e2e_attest_the_same_stable_source_surface():
    host = HOST_BATCH_RUNNER_PATH.read_text(encoding="utf-8")
    e2e = BATCH_RUNNER_PATH.read_text(encoding="utf-8")

    for script, workflow in ((host, "host"), (e2e, "e2e")):
        assert "scripts/test-source-fingerprint.py" in script
        assert "source_fingerprint_start" in script
        assert "source_fingerprint_end" in script
        assert "source_stable=%s" in script
        assert "FAIL(SOURCE_STATE_CHANGED)" in script
        assert "scripts/test-runtime-fingerprint.py" in script
        assert "runtime_dependency_fingerprint_start" in script
        assert "runtime_dependency_fingerprint_end" in script
        assert "runtime_stable=%s" in script
        assert "FAIL(RUNTIME_STATE_CHANGED)" in script
        assert "python_runtime=%s" in script
        assert f"workflow={workflow}" in script


def test_host_and_e2e_wrappers_share_one_cross_workflow_lock():
    wrapper = RUNNER_PATH.read_text(encoding="utf-8")
    host = HOST_BATCH_RUNNER_PATH.read_text(encoding="utf-8")

    default_lock = "/tmp/api-auth-test-workflows.lock"
    assert default_lock in wrapper
    assert default_lock in host
    assert "TEST_WORKFLOW_LOCK_FILE" in wrapper
    assert "TEST_WORKFLOW_LOCK_FILE" in host
    assert "flock -n 9" in wrapper
    assert "flock -n 9" in host
    assert 'LOCK_FILE}" != "${DEFAULT_LOCK_FILE}' in wrapper
    assert 'LOCK_FILE}" != "${DEFAULT_LOCK_FILE}' in host


def test_certified_pytest_runs_disable_ambient_plugins_and_load_only_pinned_plugins():
    host = HOST_BATCH_RUNNER_PATH.read_text(encoding="utf-8")
    e2e = BATCH_RUNNER_PATH.read_text(encoding="utf-8")

    for script in (host, e2e):
        assert "unset PYTEST_ADDOPTS" in script
        assert "unset PYTEST_PLUGINS" in script
        assert "unset PYTHONPATH" in script
        assert "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1" in script
        assert "-p pytest_cov.plugin" in script
        assert "-p pytest_asyncio.plugin" in script
        assert "-p anyio.pytest_plugin" in script
        assert "--strict-markers" in script


def test_e2e_runner_bounds_and_attests_test_and_coverage_resources():
    script = BATCH_RUNNER_PATH.read_text(encoding="utf-8")

    assert "require_positive_at_most PYTEST_MEM_LIMIT_MB" in script
    assert "require_positive_at_most PYTEST_TIMEOUT_SECONDS" in script
    assert "require_positive_at_most E2E_BATCH_TIMEOUT_SECONDS" in script
    assert "require_positive_at_most E2E_COVERAGE_TIMEOUT_SECONDS" in script
    assert "timeout --foreground" not in script
    assert "run_coverage erase" in script
    assert "run_coverage report" in script
    for key in (
        "pytest_mem_limit_mb",
        "pytest_timeout_seconds",
        "batch_timeout_seconds",
        "coverage_timeout_seconds",
    ):
        assert f"{key}=%s" in script


def test_full_wrapper_overrides_env_file_memory_interpolation_with_safe_defaults():
    script = RUNNER_PATH.read_text(encoding="utf-8")

    for setting in (
        "E2E_MYSQL_MEMORY_LIMIT=1g",
        "E2E_REDIS_MEMORY_LIMIT=128m",
        "E2E_MAILPIT_MEMORY_LIMIT=128m",
        "E2E_RUNNER_MEMORY_LIMIT=2g",
    ):
        assert setting in script
    assert 'export "${resource_name}=${resource_default}"' in script
