"""Drift guards for the `.env.example` contract and the CORS origin default.

These tests read source text and parse it with `ast` instead of importing the
FastAPI application, so they stay deterministic and need no MySQL or Redis.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from src.Util import auth_constants as constants
from src.Util.env_loader import _parse_value


pytestmark = pytest.mark.static

ROOT = Path(__file__).resolve().parents[2]
ENV_EXAMPLE = ROOT / ".env.example"
ORIGIN_CONSUMERS = (
    "src/main.py",
    "src/middleware/request_validation.py",
    "src/Util/email/route_support.py",
)
DEAD_KEY_FILES = (
    ".env.example",
    "src/Util/auth_constants.py",
    "tests/conftest.py",
    "docker-compose.test.yml",
    "docs/USAGE/patreon-link/reference.md",
    "docs/USAGE/stripe-billing/reference.md",
    "docs/USAGE/google-oauth/reference.md",
    "docs/USAGE/oauth/reference.md",
)
DEAD_KEYS = (
    "PATREON_E2E_CREATOR_TOKEN",
    "RUN_STRIPE_LOCAL_E2E",
    # OAuth settings that were loaded but never consumed: link tokens went away with
    # link/finish, the two rate-limit buckets were never enforced, the default group is
    # taken from the binding, and nothing ever derived anything from the passwordless
    # secret (substring match also covers the GOOGLE_OAUTH_ and OAUTH_ spellings).
    "PASSWORDLESS_HASH_SECRET",
    "GOOGLE_OAUTH_LINK_TOKEN_TTL_SECONDS",
    "GOOGLE_OAUTH_LINK_TOKEN_RATE",
    "GOOGLE_OAUTH_JWKS_FETCH_RATE",
    "GOOGLE_OAUTH_DEFAULT_USER_GROUP_HASH",
    # Read by nothing; it documented test-only sign-in code paths that no longer exist.
    "PYTEST_VERSION",
)
ORIGIN_CONSTANT = "DEFAULT_ALLOWED_ORIGINS"
ORIGIN_CONSTANT_MODULE = "src.Util.auth_constants"
# A local copy named `_DEFAULT_ALLOWED_ORIGINS` is the historical form of this
# drift, so the default must be the shared constant by exact name.
ORIGIN_DEFAULT_NAMES = {
    ORIGIN_CONSTANT,
    f"constants.{ORIGIN_CONSTANT}",
    f"auth_constants.{ORIGIN_CONSTANT}",
}
GOOGLE_ENDPOINT_KEYS = (
    "GOOGLE_OAUTH_DISCOVERY_URL",
    "GOOGLE_OAUTH_AUTHORIZE_ENDPOINT",
    "GOOGLE_OAUTH_TOKEN_ENDPOINT",
    "GOOGLE_OAUTH_JWKS_URI",
    "GOOGLE_OAUTH_ISSUERS",
)
# Only uncommented `KEY=` lines are active; `# KEY=` documents a key without setting it.
ACTIVE_KEY_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")
PLACEHOLDER_VALUE = re.compile(r"<[^>]*>")


def _active_entries() -> list[tuple[int, str, str]]:
    """Return ``(line number, key, raw value)`` for every active `.env.example` line."""
    lines = ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
    matches = (
        (number, ACTIVE_KEY_LINE.match(line.strip()))
        for number, line in enumerate(lines, start=1)
    )
    return [(number, m.group(1), m.group(2)) for number, m in matches if m is not None]


def _allowed_origins_defaults(source: str) -> list[ast.expr]:
    """Return the default argument of every ``os.environ.get("ALLOWED_ORIGINS", …)``."""
    defaults = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call) or len(node.args) != 2:
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != "get":
            continue
        if ast.unparse(func.value) != "os.environ":
            continue
        key = node.args[0]
        if isinstance(key, ast.Constant) and key.value == "ALLOWED_ORIGINS":
            defaults.append(node.args[1])
    return defaults


def test_default_allowed_origins_constant_has_no_empty_or_duplicate_entries():
    entries = constants.DEFAULT_ALLOWED_ORIGINS.split(",")
    duplicates = sorted({entry for entry in entries if entries.count(entry) > 1})

    assert entries == [entry.strip() for entry in entries]
    assert "" not in entries, "DEFAULT_ALLOWED_ORIGINS must not contain empty entries"
    assert duplicates == [], f"duplicate origins in DEFAULT_ALLOWED_ORIGINS: {duplicates}"


def _imports_origin_constant(source: str) -> bool:
    """Return whether the module imports the shared constant from its own module."""
    return any(
        node.module == ORIGIN_CONSTANT_MODULE
        and any(alias.name == ORIGIN_CONSTANT for alias in node.names)
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom)
    )


def _origin_offenders(relative: str, source: str) -> list[str]:
    offenders = []
    if not _imports_origin_constant(source):
        offenders.append(
            f"{relative}: does not import {ORIGIN_CONSTANT} from {ORIGIN_CONSTANT_MODULE}"
        )

    defaults = _allowed_origins_defaults(source)
    if not defaults:
        offenders.append(f'{relative}: no os.environ.get("ALLOWED_ORIGINS", …) call')
    offenders.extend(
        f"{relative}:{default.lineno}: ALLOWED_ORIGINS default "
        f"{ast.unparse(default)} is not the shared {ORIGIN_CONSTANT}"
        for default in defaults
        if ast.unparse(default) not in ORIGIN_DEFAULT_NAMES
    )
    return offenders


def test_allowed_origins_fallback_has_a_single_source_of_truth():
    offenders = [
        offender
        for relative in ORIGIN_CONSUMERS
        for offender in _origin_offenders(
            relative, (ROOT / relative).read_text(encoding="utf-8")
        )
    ]

    assert offenders == []


def test_allowed_origins_guard_rejects_a_module_private_origin_copy():
    """The historical drift form (a local `_DEFAULT_ALLOWED_ORIGINS`) must be caught."""
    source = (
        "import os\n"
        '_DEFAULT_ALLOWED_ORIGINS = "http://localhost:3000"\n'
        'raw = os.environ.get("ALLOWED_ORIGINS", _DEFAULT_ALLOWED_ORIGINS)\n'
    )

    assert _origin_offenders("fake/module.py", source) != []


def test_env_example_has_no_duplicate_active_keys():
    keys = [key for _, key, _ in _active_entries()]
    duplicates = sorted({key for key in keys if keys.count(key) > 1})

    assert keys, ".env.example must define at least one active key"
    assert duplicates == [], f"duplicate active keys in .env.example: {duplicates}"


def test_every_active_env_example_value_parses_verbatim():
    """An unquoted value containing `` #`` would be silently truncated on load."""
    hazards = [
        f"{line_number}: {key}={raw_value.strip()!r} loads as {_parse_value(raw_value)!r}"
        for line_number, key, raw_value in _active_entries()
        if raw_value.strip()[:1] not in {"'", '"'}
        and _parse_value(raw_value) != raw_value.strip()
    ]

    assert hazards == []


def test_google_endpoint_overrides_are_never_active_placeholders():
    """Active placeholders override the working built-in defaults and break sign-in."""
    active = {key: raw_value.strip() for _, key, raw_value in _active_entries()}
    offenders = [
        f"{key}={active[key]}"
        for key in GOOGLE_ENDPOINT_KEYS
        if key in active and PLACEHOLDER_VALUE.search(active[key])
    ]

    assert offenders == []


def test_removed_dead_env_keys_do_not_reappear():
    offenders = [
        f"{relative}: {key}"
        for relative in DEAD_KEY_FILES
        for key in DEAD_KEYS
        if key in (ROOT / relative).read_text(encoding="utf-8")
    ]

    assert offenders == []


def test_env_example_documents_every_rate_limit_and_return_url_name():
    groups = (constants.BILLING_RATE_LIMIT_ENV_NAMES, constants.PATREON_RATE_LIMIT_ENV_NAMES)
    expected = {"BILLING_RETURN_URL_ALLOWLIST"}.union(
        *(names for group in groups for names in group.values())
    )
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    documented = set(re.findall(r"^\s*#?\s*([A-Z][A-Z0-9_]+)\s*=", text, flags=re.MULTILINE))

    # Keep the guard non-vacuous if a rate-limit group is ever renamed away.
    assert {"BILLING_CHECKOUT_RATE_LIMIT", "PATREON_S2S_RATE_LIMIT"} <= expected
    assert sorted(expected - documented) == []
