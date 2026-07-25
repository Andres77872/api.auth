"""Contracts for the deterministic installed-dependency fingerprint helper."""

from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "test-runtime-fingerprint.py"

SPEC = importlib.util.spec_from_file_location("test_runtime_fingerprint_helper", SCRIPT)
assert SPEC is not None
assert SPEC.loader is not None
FINGERPRINT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FINGERPRINT)


def _write_requirements(root: Path, relative_path: str, contents: str) -> Path:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")
    return path


def _versions(**versions: str):
    normalized = {name.replace("_", "-").lower(): version for name, version in versions.items()}

    def lookup(name: str) -> str:
        try:
            return normalized[name]
        except KeyError as exc:
            raise importlib.metadata.PackageNotFoundError(name) from exc

    return lookup


class _Distribution:
    def __init__(self, name: str, version: str):
        self.metadata = {"Name": name}
        self.version = version


def _distributions(**versions: str):
    return tuple(
        _Distribution(name, version)
        for name, version in versions.items()
    )


def test_recursively_collects_active_exact_pins_and_normalizes_pairs(tmp_path):
    _write_requirements(
        tmp_path,
        "requirements.txt",
        """
        Example_Package[feature]==1.0.0
        -r requirements/base.txt
        inactive>=2; python_version < "1"
        """,
    )
    _write_requirements(
        tmp_path,
        "requirements-test.txt",
        """
        --requirement=requirements/base.txt
        pytest==9.1.1  # the test runner
        """,
    )
    _write_requirements(
        tmp_path,
        "requirements/base.txt",
        "AnyIO==4.9.0\nexample-package==1.0\n",
    )

    pins = FINGERPRINT.collect_pinned_requirements(tmp_path)
    pairs = FINGERPRINT.resolve_installed_requirements(
        tmp_path,
        _versions(
            example_package="1.0",
            anyio="4.9",
            pytest="9.1.1",
        ),
    )

    assert pins == (
        ("anyio", "4.9"),
        ("example-package", "1"),
        ("pytest", "9.1.1"),
    )
    assert pairs == (
        "anyio==4.9",
        "example-package==1",
        "pytest==9.1.1",
    )
    expected = hashlib.sha256(
        b"anyio==4.9\nexample-package==1\npytest==9.1.1\n"
    ).hexdigest()
    assert FINGERPRINT.runtime_fingerprint(
        tmp_path,
        _versions(
            example_package="1.0",
            anyio="4.9",
            pytest="9.1.1",
        ),
        _distributions(
            example_package="1.0",
            anyio="4.9",
            pytest="9.1.1",
        ),
    ) == expected


def test_fingerprint_is_independent_of_root_file_and_line_order(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_requirements(first, "requirements.txt", "Beta==2\nalpha==1\n")
    _write_requirements(second, "requirements-test.txt", "alpha==1\nBeta==2\n")
    lookup = _versions(alpha="1", beta="2")

    distributions = _distributions(alpha="1", beta="2")
    assert FINGERPRINT.runtime_fingerprint(
        first, lookup, distributions
    ) == FINGERPRINT.runtime_fingerprint(
        second, lookup, distributions
    )


@pytest.mark.parametrize(
    ("contents", "message"),
    [
        ("example>=1\n", "must use one exact == pin"),
        ("example==1.*\n", "must use one exact == pin"),
        ("example==1,!=1.1\n", "must use one exact == pin"),
        ("-e ../example\n", "editable requirements are not supported"),
        ("--editable=https://example.invalid/repo.git\n", "editable requirements"),
        ("example @ https://example.invalid/example.whl\n", "URL requirements"),
        ("--index-url https://example.invalid/simple\n", "unsupported requirement-file option"),
    ],
)
def test_rejects_non_reproducible_requirement_forms(tmp_path, contents, message):
    _write_requirements(tmp_path, "requirements.txt", contents)

    with pytest.raises(FINGERPRINT.RuntimeFingerprintError, match=re.escape(message)):
        FINGERPRINT.collect_pinned_requirements(tmp_path)


def test_inactive_non_exact_requirement_does_not_enter_runtime_surface(tmp_path):
    _write_requirements(
        tmp_path,
        "requirements.txt",
        'example==1\nlegacy>=2; python_version < "1"\n',
    )

    assert FINGERPRINT.collect_pinned_requirements(tmp_path) == (("example", "1"),)


def test_rejects_conflicting_duplicate_pins(tmp_path):
    _write_requirements(tmp_path, "requirements.txt", "Example==1\n")
    _write_requirements(tmp_path, "requirements-test.txt", "example==2\n")

    with pytest.raises(
        FINGERPRINT.RuntimeFingerprintError,
        match=r"conflicting pins for example: (?:1 and 2|2 and 1)",
    ):
        FINGERPRINT.collect_pinned_requirements(tmp_path)


@pytest.mark.parametrize(
    ("versions", "message"),
    [
        ({}, "required distribution is not installed: example==1"),
        ({"example": "2"}, "required 1, installed 2"),
    ],
)
def test_rejects_missing_or_mismatched_installed_distributions(
    tmp_path, versions, message
):
    _write_requirements(tmp_path, "requirements.txt", "example==1\n")

    with pytest.raises(FINGERPRINT.RuntimeFingerprintError, match=re.escape(message)):
        FINGERPRINT.runtime_fingerprint(
            tmp_path,
            _versions(**versions),
            _distributions(**versions),
        )


def test_rejects_unpinned_installed_transitives_but_ignores_build_tooling(tmp_path):
    _write_requirements(tmp_path, "requirements.txt", "example==1\n")
    lookup = _versions(example="1")

    with pytest.raises(
        FINGERPRINT.RuntimeFingerprintError,
        match=r"not exactly pinned: transitive==2",
    ):
        FINGERPRINT.runtime_fingerprint(
            tmp_path,
            lookup,
            _distributions(example="1", transitive="2", pip="999"),
        )

    assert FINGERPRINT.resolve_runtime_environment(
        tmp_path,
        lookup,
        _distributions(example="1", pip="999", setuptools="999", wheel="999"),
    ) == ("example==1",)


@pytest.mark.parametrize("included", [False, True])
def test_symlinked_requirement_inputs_fail_closed(tmp_path, included):
    outside = tmp_path / "outside.txt"
    outside.write_text("example==1\n", encoding="utf-8")
    if included:
        _write_requirements(tmp_path, "requirements.txt", "-r nested/pins.txt\n")
        (tmp_path / "nested").mkdir()
        (tmp_path / "nested" / "pins.txt").symlink_to(outside)
        expected = "nested/pins.txt"
    else:
        (tmp_path / "requirements.txt").symlink_to(outside)
        expected = "requirements.txt"

    with pytest.raises(
        FINGERPRINT.RuntimeFingerprintError,
        match=rf"symlinked requirement input is not allowed: {re.escape(expected)}",
    ):
        FINGERPRINT.collect_pinned_requirements(tmp_path)


def test_rejects_cyclic_includes(tmp_path):
    _write_requirements(tmp_path, "requirements.txt", "-r nested/base.txt\n")
    _write_requirements(tmp_path, "nested/base.txt", "-r ../requirements.txt\n")

    with pytest.raises(
        FINGERPRINT.RuntimeFingerprintError,
        match=r"cyclic requirement include: requirements.txt -> nested/base.txt -> requirements.txt",
    ):
        FINGERPRINT.collect_pinned_requirements(tmp_path)


def test_cli_prints_exactly_one_sha256_for_the_fully_pinned_repository_runtime():
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(ROOT)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert re.fullmatch(r"[0-9a-f]{64}\n", completed.stdout)
    assert completed.stderr == ""


def test_cli_reports_dependency_mismatch_without_a_digest(tmp_path):
    _write_requirements(tmp_path, "requirements.txt", "pytest==0.0.1\n")

    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(tmp_path)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert "installed distribution version mismatch for pytest" in completed.stderr
