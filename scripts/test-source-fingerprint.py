#!/usr/bin/env python3
"""Print a deterministic fingerprint of the complete test source surface."""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

REQUIRED_SOURCE_DIRECTORIES = (
    "src",
    "tests",
    "schemas",
    "scripts",
    "docs",
)

OPTIONAL_ROOT_FILES = (
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

CACHE_DIRECTORY_NAMES = frozenset(
    {
        "__pycache__",
        ".cache",
        ".hypothesis",
        ".mypy_cache",
        ".nox",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
    }
)
BYTECODE_SUFFIXES = frozenset({".pyc", ".pyo"})

_LENGTH_BYTES = 8


class FingerprintError(RuntimeError):
    """Raised when the requested source surface cannot be fingerprinted."""


def _is_excluded(relative_path: Path) -> bool:
    return (
        any(part in CACHE_DIRECTORY_NAMES for part in relative_path.parts)
        or relative_path.suffix.lower() in BYTECODE_SUFFIXES
    )


def collect_source_files(root: Path = ROOT) -> tuple[Path, ...]:
    """Return every in-scope regular file in deterministic relative-path order."""

    root = root.resolve()
    if not root.is_dir():
        raise FingerprintError(f"repository root is not a directory: {root}")

    symlinked_directories = [
        name for name in REQUIRED_SOURCE_DIRECTORIES if (root / name).is_symlink()
    ]
    if symlinked_directories:
        raise FingerprintError(
            "symlinked source input is not allowed: " + symlinked_directories[0]
        )

    missing_directories = [
        name for name in REQUIRED_SOURCE_DIRECTORIES if not (root / name).exists()
    ]
    if missing_directories:
        joined = ", ".join(missing_directories)
        raise FingerprintError(f"missing required source directories: {joined}")

    invalid_directories = [
        name for name in REQUIRED_SOURCE_DIRECTORIES if not (root / name).is_dir()
    ]
    if invalid_directories:
        joined = ", ".join(invalid_directories)
        raise FingerprintError(f"required source paths are not directories: {joined}")

    files: list[Path] = []
    directory_inputs = (
        path
        for directory_name in REQUIRED_SOURCE_DIRECTORIES
        for path in (root / directory_name).rglob("*")
    )
    for path in sorted(
        directory_inputs, key=lambda candidate: candidate.relative_to(root).as_posix()
    ):
        relative_path = path.relative_to(root)
        if _is_excluded(relative_path):
            continue
        if path.is_symlink():
            raise FingerprintError(
                "symlinked source input is not allowed: " + relative_path.as_posix()
            )
        if path.is_file():
            files.append(path)

    for file_name in OPTIONAL_ROOT_FILES:
        path = root / file_name
        if not path.exists() and not path.is_symlink():
            continue
        if path.is_symlink():
            raise FingerprintError(
                f"symlinked source input is not allowed: {file_name}"
            )
        if not path.is_file():
            raise FingerprintError(f"root input is not a regular file: {file_name}")
        files.append(path)

    return tuple(sorted(files, key=lambda path: path.relative_to(root).as_posix()))


def _update_frame(digest: hashlib._Hash, payload: bytes) -> None:
    digest.update(len(payload).to_bytes(_LENGTH_BYTES, byteorder="big"))
    digest.update(payload)


def source_fingerprint(root: Path = ROOT) -> str:
    """Return the SHA-256 digest for framed relative paths and file contents."""

    root = root.resolve()
    digest = hashlib.sha256()
    for path in collect_source_files(root):
        relative_path = path.relative_to(root).as_posix().encode("utf-8")
        try:
            contents = path.read_bytes()
        except OSError as exc:
            message = f"cannot read source input {relative_path!r}: {exc}"
            raise FingerprintError(message) from exc
        _update_frame(digest, relative_path)
        _update_frame(digest, contents)
    return digest.hexdigest()


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Print the deterministic SHA-256 test-source fingerprint."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=ROOT,
        help="repository root to fingerprint (defaults to the script's parent)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        fingerprint = source_fingerprint(args.root)
    except FingerprintError as exc:
        print(f"test-source-fingerprint: {exc}", file=sys.stderr)
        return 2
    print(fingerprint)
    return 0


if __name__ == "__main__":
    sys.exit(main())
