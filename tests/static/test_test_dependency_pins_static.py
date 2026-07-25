"""Contracts for deterministic host and Docker test dependencies."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EXACT_PIN = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9_.-]*"
    r"(?:\[[A-Za-z0-9_,.-]+\])?"
    r"==[^=<>!~\s*]+"
    r"(?:\s*;\s*\S.*)?"
)


def _active_requirement_entries(path: Path):
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = re.sub(r"\s+#.*$", "", raw_line).strip()
        if not line or line.startswith("#"):
            continue

        # Include/constraint and index/configuration directives affect pip, but
        # they are not dependency entries. Editable installs are dependencies
        # and deliberately remain subject to the exact-pin check below.
        if line.startswith(("-r ", "--requirement ", "-c ", "--constraint ")):
            continue
        if line.startswith("--") and not line.startswith("--editable "):
            continue

        yield line_number, line


def test_every_active_requirement_entry_is_exactly_pinned():
    requirement_files = sorted(ROOT.glob("requirements*.txt"))
    assert requirement_files

    entries = [
        (path.relative_to(ROOT).as_posix(), line_number, line)
        for path in requirement_files
        for line_number, line in _active_requirement_entries(path)
    ]
    invalid = [
        f"{path}:{line_number}: {line}"
        for path, line_number, line in entries
        if EXACT_PIN.fullmatch(line) is None
    ]

    assert entries
    assert invalid == [], f"active requirements must use exact == pins: {invalid}"


def test_e2e_build_tooling_is_exactly_pinned():
    dockerfile = (ROOT / "Dockerfile.e2e").read_text(encoding="utf-8")

    assert "pip==26.1.2" in dockerfile
    assert "setuptools==83.0.0" in dockerfile
    assert "wheel==0.47.0" in dockerfile
