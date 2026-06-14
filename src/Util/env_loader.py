"""Small dotenv loader for runtime bootstrap.

The application reads several required environment variables at import time.
Loading the project `.env` before those imports keeps local runs consistent with
shell-exported deployments without adding a runtime dependency.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _running_under_pytest() -> bool:
    return "PYTEST_CURRENT_TEST" in os.environ or "pytest" in sys.modules


def _parse_value(value: str) -> str:
    value = value.strip()
    if not value:
        return ""

    if value[0] in {"'", '"'}:
        quote = value[0]
        end = 1
        while end < len(value):
            if value[end] == quote and value[end - 1] != "\\":
                return value[1:end]
            end += 1
        return value[1:]

    for index, char in enumerate(value):
        if char == "#" and (index == 0 or value[index - 1].isspace()):
            return value[:index].rstrip()
    return value


def load_env_file(path: Path, *, override: bool = False) -> bool:
    """Load key/value pairs from *path* into ``os.environ``.

    Existing process environment values win by default. The parser intentionally
    supports the simple dotenv syntax this repo uses: comments, optional
    ``export`` prefixes, quoted values, and unquoted inline comments.
    """

    if not path.exists():
        return False

    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key[7:].strip()
        if not key:
            continue

        if override or key not in os.environ:
            os.environ[key] = _parse_value(value)

    return True


def load_project_dotenv(*, override: bool = False, skip_pytest: bool = True) -> bool:
    """Load the repository `.env` file if present.

    Tests load `.env.test` explicitly in ``tests/conftest.py``; skipping the real
    `.env` under pytest prevents local secrets from changing test behavior.
    """

    if skip_pytest and _running_under_pytest():
        return False
    return load_env_file(_project_root() / ".env", override=override)
