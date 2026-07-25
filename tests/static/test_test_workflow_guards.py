"""Behavioral regression tests for test-workflow certification guards."""

from __future__ import annotations

import fcntl
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
E2E_WRAPPER = ROOT / "scripts" / "run-e2e.sh"
E2E_BATCH_RUNNER = ROOT / "scripts" / "run-e2e-batches.sh"
HOST_RUNNER = ROOT / "scripts" / "run-test-batches.sh"
MERGE_RUNNER = ROOT / "scripts" / "combine-test-coverage.sh"
FINGERPRINT_HELPER = ROOT / "scripts" / "test-source-fingerprint.py"
RUNTIME_FINGERPRINT_HELPER = ROOT / "scripts" / "test-runtime-fingerprint.py"
REAL_DB_DISCOVERY_HELPER = ROOT / "scripts" / "discover-real-db-targets.py"


def _run(
    command: list[str],
    *,
    cwd: Path = ROOT,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )


def _base_env() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("PYTEST_ADDOPTS", None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PATH"] = f"{ROOT / '.venv' / 'bin'}:{env['PATH']}"
    return env


def test_e2e_full_pytest_args_are_rejected_before_artifacts_are_touched(tmp_path):
    artifact_dir = tmp_path / "e2e"
    artifact_dir.mkdir()
    summary = artifact_dir / "summary.txt"
    summary.write_text("sentinel\n", encoding="utf-8")
    env = _base_env()
    env["E2E_ARTIFACT_DIR"] = str(artifact_dir)

    completed = _run(["bash", str(E2E_BATCH_RUNNER), "-k", "no_such_test"], env=env)

    assert completed.returncode == 2
    assert "full runs accept no pytest arguments" in completed.stderr
    assert summary.read_text(encoding="utf-8") == "sentinel\n"


def test_e2e_full_pytest_addopts_are_rejected_before_artifacts_are_touched(tmp_path):
    artifact_dir = tmp_path / "e2e"
    artifact_dir.mkdir()
    summary = artifact_dir / "summary.txt"
    summary.write_text("sentinel\n", encoding="utf-8")
    env = _base_env()
    env["E2E_ARTIFACT_DIR"] = str(artifact_dir)
    env["PYTEST_ADDOPTS"] = "-k no_such_test"

    completed = _run(["bash", str(E2E_BATCH_RUNNER)], env=env)

    assert completed.returncode == 2
    assert "PYTEST_ADDOPTS must be empty" in completed.stderr
    assert summary.read_text(encoding="utf-8") == "sentinel\n"


def test_host_full_pytest_addopts_are_rejected_before_artifacts_are_touched(tmp_path):
    artifact_dir = tmp_path / "host"
    artifact_dir.mkdir()
    summary = artifact_dir / "summary.txt"
    summary.write_text("sentinel\n", encoding="utf-8")
    env = _base_env()
    env["TEST_ARTIFACT_DIR"] = str(artifact_dir)
    env["PYTEST_ADDOPTS"] = "-k no_such_test"

    completed = _run(["bash", str(HOST_RUNNER)], env=env)

    assert completed.returncode == 2
    assert "PYTEST_ADDOPTS must be empty" in completed.stderr
    assert summary.read_text(encoding="utf-8") == "sentinel\n"


def test_host_explicit_empty_full_argument_is_rejected_before_artifacts_are_touched(
    tmp_path,
):
    artifact_dir = tmp_path / "host"
    artifact_dir.mkdir()
    summary = artifact_dir / "summary.txt"
    summary.write_text("sentinel\n", encoding="utf-8")
    env = _base_env()
    env["TEST_ARTIFACT_DIR"] = str(artifact_dir)

    completed = _run(
        ["bash", str(HOST_RUNNER), "", "-k", "one_test_only"],
        env=env,
    )

    assert completed.returncode == 2
    assert "explicit empty test-selection argument" in completed.stderr
    assert summary.read_text(encoding="utf-8") == "sentinel\n"


def test_e2e_explicit_empty_full_argument_is_rejected_before_artifacts_are_touched(
    tmp_path,
):
    artifact_dir = tmp_path / "e2e"
    artifact_dir.mkdir()
    summary = artifact_dir / "summary.txt"
    summary.write_text("sentinel\n", encoding="utf-8")
    env = _base_env()
    env["E2E_ARTIFACT_DIR"] = str(artifact_dir)

    completed = _run(
        ["bash", str(E2E_BATCH_RUNNER), "", "-k", "one_test_only"],
        env=env,
    )

    assert completed.returncode == 2
    assert "full runs accept no pytest arguments" in completed.stderr
    assert summary.read_text(encoding="utf-8") == "sentinel\n"


def test_host_full_lock_override_is_rejected_before_artifacts_are_touched(tmp_path):
    artifact_dir = tmp_path / "host"
    artifact_dir.mkdir()
    summary = artifact_dir / "summary.txt"
    summary.write_text("sentinel\n", encoding="utf-8")
    env = _base_env()
    env["TEST_ARTIFACT_DIR"] = str(artifact_dir)
    env["TEST_WORKFLOW_LOCK_FILE"] = str(tmp_path / "workflow.lock")

    completed = _run(["bash", str(HOST_RUNNER)], env=env)

    assert completed.returncode == 2
    assert "must use the shared workflow lock" in completed.stderr
    assert summary.read_text(encoding="utf-8") == "sentinel\n"


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("PYTEST_MEM_LIMIT_MB", "0"),
        ("PYTEST_MEM_LIMIT_MB", "1537"),
        ("PYTEST_TIMEOUT_SECONDS", "61"),
        ("TEST_BATCH_TIMEOUT_SECONDS", "0"),
        ("COVERAGE_MEM_LIMIT_MB", "99999"),
        ("COVERAGE_TIMEOUT_SECONDS", "301"),
        ("PYTEST_TIMEOUT_SECONDS", "18446744073709551617"),
    ],
)
def test_host_unsafe_resource_overrides_fail_before_artifacts_are_touched(
    tmp_path, name, value
):
    artifact_dir = tmp_path / "host"
    artifact_dir.mkdir()
    summary = artifact_dir / "summary.txt"
    summary.write_text("sentinel\n", encoding="utf-8")
    env = _base_env()
    env["TEST_ARTIFACT_DIR"] = str(artifact_dir)
    env[name] = value

    completed = _run(["bash", str(HOST_RUNNER)], env=env)

    assert completed.returncode == 2
    assert "canonical positive integer no greater than" in completed.stderr
    assert summary.read_text(encoding="utf-8") == "sentinel\n"


def test_host_lock_refuses_overlap_before_artifacts_are_touched(tmp_path):
    artifact_dir = tmp_path / "host"
    artifact_dir.mkdir()
    summary = artifact_dir / "summary.txt"
    summary.write_text("sentinel\n", encoding="utf-8")
    lock_path = tmp_path / "workflow.lock"
    env = _base_env()
    env["TEST_ARTIFACT_DIR"] = str(artifact_dir)
    env["TEST_WORKFLOW_LOCK_FILE"] = str(lock_path)
    env["ALLOW_TEST_WORKFLOW_LOCK_OVERRIDE"] = "1"

    with lock_path.open("w", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        completed = _run(
            [
                "bash",
                str(HOST_RUNNER),
                "--target",
                "tests/static/test_system_endpoint_docs_static.py",
            ],
            env=env,
        )

    assert completed.returncode == 1
    assert "refusing an overlapping run" in completed.stderr
    assert summary.read_text(encoding="utf-8") == "sentinel\n"


def _write_fake_docker(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env bash
set -u
if [[ "${1:-}" == "info" ]]; then
  exit 0
fi
if [[ "${1:-}" == "image" && "${2:-}" == "inspect" ]]; then
  printf 'sha256:%064d\\n' 0
  exit 0
fi
if [[ "${1:-}" != "compose" ]]; then
  exit 90
fi
action=""
for arg in "$@"; do
  case "${arg}" in
    config|down|build|up|run|logs|images)
      action="${arg}"
      break
      ;;
  esac
done
if [[ "${action}" == "images" ]]; then
  if [[ "${!#}" == "e2e-runner" ]]; then
    # `docker compose images` only lists images for created containers; exercise
    # the wrapper's built-image reference fallback for the one-shot runner.
    exit 0
  fi
  printf 'sha256:%064d\\n' 0
  exit 0
fi
if [[ "${action}" == "down" ]]; then
  count=0
  if [[ -f "${FAKE_DOCKER_STATE}" ]]; then
    count="$(<"${FAKE_DOCKER_STATE}")"
  fi
  count=$((count + 1))
  printf '%s\\n' "${count}" > "${FAKE_DOCKER_STATE}"
  if [[ "${count}" -ge 2 ]]; then
    exit "${FAKE_FINAL_DOWN_STATUS}"
  fi
fi
if [[ "${action}" == "run" && -n "${FAKE_SUMMARY_PATH:-}" ]]; then
  printf 'fake_batch_summary=true\\n' > "${FAKE_SUMMARY_PATH}"
fi
exit 0
""",
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def test_e2e_wrapper_propagates_final_teardown_failure_and_clears_stale_log(tmp_path):
    project = tmp_path / "project"
    scripts = project / "scripts"
    artifacts = project / "test-results" / "e2e"
    fake_bin = tmp_path / "bin"
    scripts.mkdir(parents=True)
    artifacts.mkdir(parents=True)
    fake_bin.mkdir()
    shutil.copy2(E2E_WRAPPER, scripts / "run-e2e.sh")
    shutil.copy2(FINGERPRINT_HELPER, scripts / "test-source-fingerprint.py")
    for required_directory in ("src", "tests", "schemas", "docs"):
        (project / required_directory).mkdir()
    (project / ".env.test").write_text("TESTING=true\n", encoding="utf-8")
    stale_log = artifacts / "docker-compose.log"
    stale_log.write_text("stale failure\n", encoding="utf-8")
    fake_docker = fake_bin / "docker"
    _write_fake_docker(fake_docker)

    env = _base_env()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["FAKE_DOCKER_STATE"] = str(tmp_path / "docker-state")
    env["FAKE_FINAL_DOWN_STATUS"] = "37"
    env["FAKE_SUMMARY_PATH"] = str(artifacts / "summary.txt")
    env["TEST_WORKFLOW_LOCK_FILE"] = str(tmp_path / "workflow.lock")
    env["ALLOW_TEST_WORKFLOW_LOCK_OVERRIDE"] = "1"

    completed = _run(
        [
            "bash",
            str(scripts / "run-e2e.sh"),
            "--target",
            "tests/e2e/test_dummy.py",
        ],
        cwd=project,
        env=env,
    )

    assert completed.returncode == 37
    assert "teardown failed with status 37" in completed.stderr
    assert not stale_log.exists()
    assert (artifacts / "summary.txt").read_text(encoding="utf-8").endswith(
        "wrapper_status=37\n"
    )


def test_merge_rejects_duplicate_attestation_keys(tmp_path):
    project = tmp_path / "project"
    scripts = project / "scripts"
    host_dir = project / "test-results" / "host"
    e2e_dir = project / "test-results" / "e2e"
    scripts.mkdir(parents=True)
    host_dir.mkdir(parents=True)
    e2e_dir.mkdir(parents=True)
    shutil.copy2(MERGE_RUNNER, scripts / "combine-test-coverage.sh")
    shutil.copy2(FINGERPRINT_HELPER, scripts / "test-source-fingerprint.py")
    shutil.copy2(RUNTIME_FINGERPRINT_HELPER, scripts / "test-runtime-fingerprint.py")
    (project / ".coveragerc").write_text("[run]\nbranch = True\n", encoding="utf-8")
    (host_dir / "summary.txt").write_text(
        "summary_version=1\nsummary_version=1\n",
        encoding="utf-8",
    )

    env = _base_env()
    env["PYTHON_BIN"] = sys.executable
    env["TEST_WORKFLOW_LOCK_FILE"] = str(tmp_path / "workflow.lock")
    env["ALLOW_TEST_WORKFLOW_LOCK_OVERRIDE"] = "1"
    completed = _run(
        ["bash", str(scripts / "combine-test-coverage.sh")],
        cwd=project,
        env=env,
    )

    assert completed.returncode == 2
    assert "exactly one summary_version entry" in completed.stderr


def test_merge_lock_refuses_to_read_or_replace_moving_artifacts(tmp_path):
    lock_path = tmp_path / "workflow.lock"
    env = _base_env()
    env["TEST_WORKFLOW_LOCK_FILE"] = str(lock_path)
    env["ALLOW_TEST_WORKFLOW_LOCK_OVERRIDE"] = "1"

    with lock_path.open("w", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        completed = _run(["bash", str(MERGE_RUNNER)], env=env)

    assert completed.returncode == 1
    assert "refusing to merge moving artifacts" in completed.stderr


def test_real_db_discovery_uses_recursive_pytest_metadata_for_aliases_and_hooks(tmp_path):
    integration = tmp_path / "tests" / "integration" / "nested"
    integration.mkdir(parents=True)
    (tmp_path / "pytest.ini").write_text(
        "[pytest]\nmarkers =\n    real_db: requires live database\n",
        encoding="utf-8",
    )
    (tmp_path / "tests" / "conftest.py").write_text(
        "import pytest\n"
        "\n"
        "def pytest_collection_modifyitems(items):\n"
        "    for item in items:\n"
        "        if item.name == 'test_hooked':\n"
        "            item.add_marker(pytest.mark.real_db)\n",
        encoding="utf-8",
    )
    (integration / "test_alias.py").write_text(
        "import pytest as pt\n"
        "\n"
        "@pt.mark.real_db\n"
        "def test_aliased():\n"
        "    pass\n",
        encoding="utf-8",
    )
    (integration / "test_hook.py").write_text(
        "def test_hooked():\n"
        "    pass\n",
        encoding="utf-8",
    )
    (integration / "test_ordinary.py").write_text(
        "def test_ordinary():\n"
        "    pass\n",
        encoding="utf-8",
    )

    completed = _run(
        [sys.executable, str(REAL_DB_DISCOVERY_HELPER), "--root", str(tmp_path)],
        env=_base_env(),
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""
    assert completed.stdout.splitlines() == [
        "tests/integration/nested/test_alias.py",
        "tests/integration/nested/test_hook.py",
    ]
