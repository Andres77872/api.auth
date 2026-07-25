"""Static no-login contracts for Patreon account linking.

Trace: `.dev/sdd/changes/patreon-account-link/tasks.md` task 1.2 and
spec requirements that Patreon is entitlement/link only, never local login.

These tests are intentionally static so they can guard the boundary before the
Patreon runtime exists. They must not import future route modules at collection
time because Phase 1 is a RED proof scaffold.
"""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"

FORBIDDEN_PATREON_AUTH_ROUTES = (
    "/auth/patreon/login",
    "/auth/patreon/authorize",
    "/auth/patreon/callback",
    "/auth/patreon/token",
)

FORBIDDEN_SESSION_ISSUANCE_FRAGMENTS = (
    "issue_project_token_pair",
    "issue_platform_token_pair",
    "rotate_refresh_family",
    "set_auth_cookies",
    ".set_cookie(",
    "TokenPairFields",
    "LoginResponse(",
    "RegisterResponse(",
    "SwitchProjectResponse(",
    "EnhancedUserLogin(",
)

FORBIDDEN_PATREON_RESPONSE_FIELDS = (
    "access_token",
    "refresh_token",
    "session_token",
    "api_key",
    "token_type",
    "expires_in",
    "refresh_expires_in",
    "expires_at",
    "refresh_expires_at",
)

FORBIDDEN_AUTH_VALIDATE_FIELDS = (
    "patreon",
    "entitlement",
    "plan_code",
    "tier_code",
    "subscription_status",
    "link_status",
    "external_source",
)

def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _python_files_under(*roots: Path) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        if root.exists():
            files.extend(sorted(root.rglob("*.py")))
    return files


def _patreon_route_files() -> list[Path]:
    candidates = [SRC / "main.py"]
    route_dir = SRC / "routes"
    if route_dir.exists():
        candidates.extend(sorted(route_dir.glob("*patreon*.py")))
    return [path for path in candidates if path.exists()]


def _patreon_runtime_files() -> list[Path]:
    roots = (SRC / "routes", SRC / "Util" / "patreon", SRC / "workers")
    files = [path for path in _python_files_under(*roots) if "patreon" in path.as_posix().lower()]
    main_path = SRC / "main.py"
    if main_path.exists() and "patreon" in _read(main_path).lower():
        files.append(main_path)
    return sorted(set(files))


def _decorated_route_paths(text: str) -> list[str]:
    route_pattern = re.compile(
        r"@(router|app)\.(get|post|put|patch|delete)\(\s*(['\"])(?P<path>[^'\"]+)\3",
        re.IGNORECASE,
    )
    return [match.group("path") for match in route_pattern.finditer(text)]


def _class_blocks(text: str) -> dict[str, str]:
    blocks: dict[str, str] = {}
    pattern = re.compile(r"^class\s+(?P<name>\w+)\b(?P<body>.*?)(?=^class\s+|\Z)", re.MULTILINE | re.DOTALL)
    for match in pattern.finditer(text):
        blocks[match.group("name")] = match.group(0)
    return blocks


def test_no_forbidden_patreon_login_or_oauth_routes_are_registered_in_source():
    offenders: list[str] = []
    for path in _patreon_route_files():
        text = _read(path)
        for route_path in _decorated_route_paths(text):
            normalized = route_path.rstrip("/").lower()
            if normalized in FORBIDDEN_PATREON_AUTH_ROUTES:
                offenders.append(f"{path.relative_to(ROOT)} registers {route_path}")

    assert offenders == []


def test_patreon_runtime_never_calls_local_session_or_token_issuance_helpers():
    offenders: list[str] = []
    for path in _patreon_runtime_files():
        text = _read(path)
        for fragment in FORBIDDEN_SESSION_ISSUANCE_FRAGMENTS:
            if fragment in text:
                offenders.append(f"{path.relative_to(ROOT)} contains `{fragment}`")

    assert offenders == []


def test_patreon_response_models_do_not_expose_local_auth_token_fields():
    models_path = SRC / "Util" / "Models.py"
    blocks = _class_blocks(_read(models_path))
    offenders: list[str] = []

    for name, block in blocks.items():
        if not name.startswith("Patreon"):
            continue
        header = block.splitlines()[0]
        if "TokenPairFields" in header:
            offenders.append(f"{name} inherits TokenPairFields")
        if not (name.endswith("Response") or "Status" in name or "Entitlement" in name or "Safe" in name):
            continue
        for field in FORBIDDEN_PATREON_RESPONSE_FIELDS:
            if re.search(rf"^\s*{re.escape(field)}\s*[:=]", block, re.MULTILINE):
                offenders.append(f"{name} exposes `{field}`")

    assert offenders == []


def test_auth_validate_response_model_and_route_remain_patreon_entitlement_free():
    models_text = _read(SRC / "Util" / "Models.py")
    validate_block = _class_blocks(models_text).get("ValidateSessionResponse", "")
    assert validate_block, "ValidateSessionResponse must remain inspectable"

    model_offenders = [field for field in FORBIDDEN_AUTH_VALIDATE_FIELDS if field in validate_block.lower()]
    assert model_offenders == []

    auth_route_path = SRC / "routes" / "auth.py"
    auth_text = _read(auth_route_path)
    route_match = re.search(
        r"@router\.get\(\s*['\"]\/validate['\"].*?(?=^@router\.|\Z)",
        auth_text,
        re.MULTILINE | re.DOTALL,
    )
    assert route_match is not None, "GET /auth/validate route must remain inspectable"

    route_block = route_match.group(0).lower()
    route_offenders = [field for field in FORBIDDEN_AUTH_VALIDATE_FIELDS if field in route_block]
    assert route_offenders == []


# Removed: test_production_docs_do_not_publish_patreon_login_or_oauth_session_contracts.
# It excused any doc mention whose surrounding ±2 lines contained a DOC_NEGATION_CONTEXT
# marker — a list that includes "no " and "not ".  English prose satisfies that in
# almost any 5-line window, so the test could not fail.  The Patreon no-login invariant
# is enforced against real artifacts by the four source-scanning tests above, which is
# where it belongs.
