"""Contracts for safe host/E2E coverage artifact merging."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MERGE_RUNNER = ROOT / "scripts" / "combine-test-coverage.sh"
HOST_RUNNER = ROOT / "scripts" / "run-test-batches.sh"


def test_merge_requires_complete_full_workflow_summaries():
    script = MERGE_RUNNER.read_text(encoding="utf-8")

    assert "load_summary" in script
    assert "validate_summary" in script
    assert "summary must contain exactly one" in script
    assert 'summary[selection_scope]}" == "full"' in script
    assert "failed_batches" in script
    assert "coverage_status" in script
    assert "certification_status" in script
    assert '"${HOST_DIR}/summary.txt"' in script
    assert '"${E2E_DIR}/summary.txt"' in script


def test_merge_uses_exact_inputs_and_preserves_them():
    script = MERGE_RUNNER.read_text(encoding="utf-8")

    assert '"${HOST_DATA}"' in script
    assert '"${E2E_DATA}"' in script
    assert "--keep" in script
    assert "--append" not in script
    assert "host_hash_before" in script
    assert "host_hash_after" in script
    assert "e2e_hash_before" in script
    assert "e2e_hash_after" in script
    assert 'host_summary[coverage_data_sha256]' in script
    assert 'e2e_summary[coverage_data_sha256]' in script


def test_merge_writes_all_combined_report_formats():
    script = MERGE_RUNNER.read_text(encoding="utf-8")

    assert '"${OUTPUT_DIR}/coverage.xml"' in script
    assert '"${OUTPUT_DIR}/coverage.json"' in script
    assert '"${OUTPUT_DIR}/html"' in script


def test_host_runner_labels_scope_and_preserves_per_file_shards():
    script = HOST_RUNNER.read_text(encoding="utf-8")

    assert 'selection_scope="full"' in script
    assert 'selection_scope="layer:${layer}"' in script
    assert 'selection_scope="target:${target}"' in script
    assert "coverage combine --keep" in script


def test_merge_rejects_inconsistent_batch_arithmetic_and_filtered_e2e():
    script = MERGE_RUNNER.read_text(encoding="utf-8")

    assert "expected_completed_batches" in script
    assert "expected_filtered_batches" in script
    assert "actual batch arithmetic is inconsistent" in script
    assert "completed/filtered batch disposition does not match the manifest" in script
    assert "E2E summary contains filtered or incomplete batches" in script
    assert "wrapper_status" in script
    assert "coverage_shards" in script
    assert "Host coverage shard count does not match" in script


def test_merge_requires_matching_current_stable_source_fingerprints():
    script = MERGE_RUNNER.read_text(encoding="utf-8")

    assert "scripts/test-source-fingerprint.py" in script
    assert "source_fingerprint_start" in script
    assert "source_fingerprint_end" in script
    assert "source_stable" in script
    assert "current_fingerprint" in script
    assert "Host, E2E, and current source fingerprints do not all match" in script
    assert "scripts/test-runtime-fingerprint.py" in script
    assert "runtime_dependency_fingerprint_start" in script
    assert "runtime_dependency_fingerprint_end" in script
    assert "current_runtime_fingerprint" in script
    assert (
        "Host, E2E, and current installed dependency fingerprints do not all match"
        in script
    )
    assert "current_python_runtime" in script
    assert "Host coverage Python runtime does not match" in script


def test_merge_holds_the_cross_workflow_lock_while_reading_and_writing():
    script = MERGE_RUNNER.read_text(encoding="utf-8")
    lock = script.index('exec 9>"${LOCK_FILE}"')
    invalidation = script.index('rm -f "${OUTPUT_DIR}/summary.txt"')
    summaries = script.index("load_summary host_summary")

    assert "/tmp/api-auth-test-workflows.lock" in script
    assert "TEST_WORKFLOW_LOCK_FILE" in script
    assert "flock -n 9" in script
    assert lock < invalidation < summaries
    assert "ALLOW_TEST_WORKFLOW_LOCK_OVERRIDE" in script


def test_merge_coverage_processes_have_the_same_memory_ceiling():
    script = MERGE_RUNNER.read_text(encoding="utf-8")

    assert 'COVERAGE_MEM_LIMIT_MB="${COVERAGE_MEM_LIMIT_MB:-1536}"' in script
    assert 'current_soft_kib="$(ulimit -S -v)"' in script
    assert 'current_hard_kib="$(ulimit -H -v)"' in script
    assert 'ulimit -S -v "${effective_kib}"' in script
    assert 'COVERAGE_TIMEOUT_SECONDS="${COVERAGE_TIMEOUT_SECONDS:-300}"' in script
    assert "timeout --foreground" not in script
    assert 'timeout --signal=TERM --kill-after=15s' in script
    assert "1536 || exit 2" in script
    assert "300 || exit 2" in script
    assert "run_coverage combine" in script
    assert "run_coverage report" in script
    assert "run_coverage html" in script


def test_merge_publishes_a_combined_attestation():
    script = MERGE_RUNNER.read_text(encoding="utf-8")

    assert '"${OUTPUT_DIR}/summary.txt"' in script
    assert "source_fingerprint_sha256=%s" in script
    assert "host_coverage_sha256=%s" in script
    assert "e2e_coverage_sha256=%s" in script
    assert "combined_coverage_sha256=%s" in script
    assert "runtime_dependency_sha256=%s" in script
    assert "host_python_runtime=%s" in script
    assert "e2e_python_runtime=%s" in script
    assert "e2e_runner_image_id=%s" in script
    assert "mysql_image_id=%s" in script
    assert "redis_image_id=%s" in script
    assert "mailpit_image_id=%s" in script
    assert "final_fingerprint" in script
    assert "Source changed while combined coverage reports were being generated" in script
    assert "final_runtime_fingerprint" in script
    assert "Installed dependencies changed while combined reports were being generated" in script
    assert 'mv "${summary_tmp}" "${OUTPUT_DIR}/summary.txt"' in script


def test_merge_requires_certified_bounded_resource_values():
    script = MERGE_RUNNER.read_text(encoding="utf-8")

    for key in (
        "pytest_mem_limit_mb",
        "pytest_timeout_seconds",
        "batch_timeout_seconds",
        "coverage_timeout_seconds",
    ):
        assert key in script
    assert "coverage_mem_limit_mb" in script
    assert "require_positive_at_most" in script
    assert '"${#value}" -gt 10' in script
