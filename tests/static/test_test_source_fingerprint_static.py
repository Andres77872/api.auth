"""Contracts for the deterministic test-source fingerprint helper."""

from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "test-source-fingerprint.py"

SPEC = importlib.util.spec_from_file_location("test_source_fingerprint_helper", SCRIPT)
assert SPEC is not None
assert SPEC.loader is not None
FINGERPRINT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FINGERPRINT)


def _make_project(root: Path, entries: list[tuple[str, bytes]]) -> None:
    for directory in FINGERPRINT.REQUIRED_SOURCE_DIRECTORIES:
        (root / directory).mkdir(parents=True, exist_ok=True)
    for relative_path, contents in entries:
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)


def test_declares_the_complete_source_and_root_config_scope():
    assert FINGERPRINT.REQUIRED_SOURCE_DIRECTORIES == (
        "src",
        "tests",
        "schemas",
        "scripts",
        "docs",
    )
    assert FINGERPRINT.OPTIONAL_ROOT_FILES == (
        ".coveragerc",
        "pytest.ini",
        "requirements.txt",
        "requirements-test.txt",
        "Dockerfile",
        "Dockerfile.e2e",
        "docker-compose.test.yml",
        ".dockerignore",
        ".env.test",
        ".env.example",
        "README.md",
    )

    repository_inputs = {
        path.relative_to(ROOT).as_posix()
        for path in FINGERPRINT.collect_source_files(ROOT)
    }
    assert "scripts/test-source-fingerprint.py" in repository_inputs
    assert "tests/static/test_test_source_fingerprint_static.py" in repository_inputs


def test_fingerprint_is_independent_of_creation_order_and_metadata(tmp_path):
    entries = [
        ("src/app.py", b"print('hello')\n"),
        ("tests/unit/test_app.py", b"def test_app(): pass\n"),
        ("schemas/tables.sql", b"CREATE TABLE example (id INT);\n"),
        ("scripts/check.sh", b"#!/bin/sh\n"),
        ("pytest.ini", b"[pytest]\n"),
        ("requirements.txt", b"example==1.0\n"),
    ]
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    _make_project(first_root, entries)
    _make_project(second_root, list(reversed(entries)))

    first_digest = FINGERPRINT.source_fingerprint(first_root)
    for path in FINGERPRINT.collect_source_files(first_root):
        os.utime(path, (1, 1))

    assert FINGERPRINT.source_fingerprint(first_root) == first_digest
    assert FINGERPRINT.source_fingerprint(second_root) == first_digest


@pytest.mark.parametrize("root_file", FINGERPRINT.OPTIONAL_ROOT_FILES)
def test_each_present_root_config_affects_the_digest(tmp_path, root_file):
    _make_project(tmp_path, [("src/app.py", b"before\n"), (root_file, b"config\n")])
    before = FINGERPRINT.source_fingerprint(tmp_path)

    (tmp_path / root_file).write_bytes(b"changed config\n")

    assert FINGERPRINT.source_fingerprint(tmp_path) != before


def test_cache_and_bytecode_artifacts_are_excluded(tmp_path):
    _make_project(tmp_path, [("src/app.py", b"source\n")])
    before = FINGERPRINT.source_fingerprint(tmp_path)

    excluded_entries = [
        ("src/__pycache__/app.cpython-313.pyc", b"cached"),
        ("tests/.pytest_cache/v/cache/nodeids", b"cached"),
        ("schemas/.mypy_cache/state.json", b"cached"),
        ("scripts/.ruff_cache/state", b"cached"),
        ("scripts/loose.pyc", b"bytecode"),
        ("schemas/legacy.pyo", b"optimized bytecode"),
    ]
    _make_project(tmp_path, excluded_entries)

    assert FINGERPRINT.source_fingerprint(tmp_path) == before
    for relative_path, _ in excluded_entries:
        (tmp_path / relative_path).write_bytes(b"different ignored contents")
    assert FINGERPRINT.source_fingerprint(tmp_path) == before


@pytest.mark.parametrize(
    ("link_path", "target_is_directory"),
    [
        ("src/a-link.py", False),
        ("tests/a-link", True),
    ],
)
def test_non_excluded_directory_tree_symlinks_fail_closed(
    tmp_path, link_path, target_is_directory
):
    _make_project(tmp_path, [("src/app.py", b"source\n")])
    target = tmp_path / "outside-input"
    if target_is_directory:
        target.mkdir()
    else:
        target.write_bytes(b"external source\n")
    (tmp_path / link_path).symlink_to(target, target_is_directory=target_is_directory)

    with pytest.raises(
        FINGERPRINT.FingerprintError,
        match=rf"^symlinked source input is not allowed: {re.escape(link_path)}$",
    ):
        FINGERPRINT.source_fingerprint(tmp_path)


@pytest.mark.parametrize("root_file", ["pytest.ini", "requirements.txt"])
@pytest.mark.parametrize("dangling", [False, True])
def test_root_input_symlinks_fail_closed_even_when_dangling(
    tmp_path, root_file, dangling
):
    _make_project(tmp_path, [("src/app.py", b"source\n")])
    target = tmp_path / "outside-root-input"
    if not dangling:
        target.write_bytes(b"external config\n")
    (tmp_path / root_file).symlink_to(target)

    with pytest.raises(
        FINGERPRINT.FingerprintError,
        match=rf"^symlinked source input is not allowed: {re.escape(root_file)}$",
    ):
        FINGERPRINT.source_fingerprint(tmp_path)


def test_required_source_directory_symlink_fails_closed(tmp_path):
    _make_project(tmp_path, [("src/app.py", b"source\n")])
    real_src = tmp_path / "real-src"
    (tmp_path / "src").rename(real_src)
    (tmp_path / "src").symlink_to(real_src, target_is_directory=True)

    with pytest.raises(
        FINGERPRINT.FingerprintError,
        match=r"^symlinked source input is not allowed: src$",
    ):
        FINGERPRINT.source_fingerprint(tmp_path)


def test_symlinks_inside_excluded_cache_directories_remain_excluded(tmp_path):
    _make_project(tmp_path, [("src/app.py", b"source\n")])
    before = FINGERPRINT.source_fingerprint(tmp_path)
    cache_directory = tmp_path / "tests" / ".pytest_cache"
    cache_directory.mkdir()
    (cache_directory / "external").symlink_to(tmp_path / "missing-cache-target")

    assert FINGERPRINT.source_fingerprint(tmp_path) == before


def test_paths_and_contents_are_length_framed(tmp_path):
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    _make_project(first_root, [("src/a", b"bc")])
    _make_project(second_root, [("src/ab", b"c")])

    assert b"src/a" + b"bc" == b"src/ab" + b"c"
    assert (
        FINGERPRINT.source_fingerprint(first_root)
        != FINGERPRINT.source_fingerprint(second_root)
    )


def test_cli_prints_exactly_one_lowercase_sha256_digest(tmp_path):
    _make_project(tmp_path, [("scripts/helper.py", b"pass\n")])

    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(tmp_path)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert re.fullmatch(r"[0-9a-f]{64}\n", completed.stdout)
    assert completed.stderr == ""


def test_cli_rejects_missing_required_source_directories(tmp_path):
    (tmp_path / "src").mkdir()

    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(tmp_path)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert "missing required source directories" in completed.stderr
    assert "tests" in completed.stderr
    assert "schemas" in completed.stderr
    assert "scripts" in completed.stderr
