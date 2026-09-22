"""Repository-wide documentation drift guards.

These tests intentionally inspect source text instead of importing the FastAPI
application so they stay deterministic and do not require MySQL or Redis.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from urllib.parse import unquote

from src.Util.documentation_renderer import DocumentationRenderer


ROOT = Path(__file__).resolve().parents[2]
ROUTES = ROOT / "src" / "routes"
CENTRAL_INDEXES = (
    ROOT / "README.md",
    ROOT / "src" / "README.md",
    ROOT / "docs" / "USAGE" / "README.md",
)

ROUTE_COUNTS = {
    "admin_billing.py": 22,
    "admin_dashboard.py": 8,
    "admin_oauth.py": 20,
    "admin_patreon.py": 7,
    "admin_project_groups.py": 7,
    "admin_user_groups.py": 13,
    "api_keys.py": 7,
    "audit_logs.py": 6,
    "auth.py": 13,
    "auth_google.py": 5,
    "auth_oauth.py": 9,
    "auth_patreon.py": 4,
    "bulk_operations.py": 4,
    "email_templates.py": 8,
    "email_webhooks.py": 1,
    "global_roles.py": 28,
    "internal_billing.py": 6,
    "internal_email.py": 3,
    "internal_patreon.py": 2,
    "patreon_webhooks.py": 1,
    "permission_assignments.py": 17,
    "projects.py": 11,
    "stripe_webhooks.py": 2,
    "system.py": 7,
    "user_api_keys.py": 5,
    "user_types_auth.py": 10,
    "users.py": 19,
}

ROUTE_DECORATOR = re.compile(
    r"^\s*@router\.(?:get|post|put|patch|delete)\s*\(",
    re.MULTILINE,
)
ROUTE_OPERATION = re.compile(
    r"^\s*@router\.(get|post|put|patch|delete)\s*"
    r"\(\s*([\"'])(.*?)\2",
    re.MULTILINE | re.DOTALL,
)
ROUTER_PREFIX = re.compile(
    r"^\s*router\s*=\s*APIRouter\s*\(\s*prefix\s*=\s*([\"'])(.*?)\1",
    re.MULTILINE | re.DOTALL,
)
MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
MARKDOWN_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE)
REPOSITORY_FILE_REFERENCE = re.compile(
    r"(?<![\w/])"
    r"((?:src|docs|schemas|scripts|tests)/"
    r"(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+"
    r"\.(?:py|sql|md|sh|http|json|ya?ml))"
)


def _documentation_files() -> list[Path]:
    files = [ROOT / "README.md", ROOT / "src" / "README.md"]
    files.extend((ROOT / "docs").rglob("*.md"))
    files.extend((ROOT / "schemas" / "docs").rglob("*.md"))
    return sorted(set(files))


def _slugify(text: str) -> str:
    """Match ``DocumentationRenderer._slugify`` exactly."""

    return re.sub(r"[^\w\s-]", "", text.lower()).strip().replace(" ", "-")


def _canonical_route(path: str) -> str:
    normalized = re.sub(r"\{[^}]+\}", "{}", path)
    return normalized.rstrip("/") or "/"


def _source_route_operations() -> set[tuple[str, str]]:
    operations: set[tuple[str, str]] = set()

    for route_file in ROUTES.glob("*.py"):
        source = route_file.read_text(encoding="utf-8")
        prefix_match = ROUTER_PREFIX.search(source)
        prefix = prefix_match.group(2).rstrip("/") if prefix_match else ""
        for match in ROUTE_OPERATION.finditer(source):
            method, _, local_path = match.groups()
            full_path = f"{prefix}{local_path}" or "/"
            operations.add((method.upper(), _canonical_route(full_path)))

    return operations


def _resolve_local_target(source: Path, target: str) -> tuple[Path | None, str]:
    decoded = unquote(target)
    path_part, _, fragment = decoded.partition("#")
    path_part = path_part.partition("?")[0]

    if not path_part:
        return source, fragment
    if path_part.startswith(("http://", "https://", "mailto:", "tel:")):
        return None, fragment
    if path_part == "/documentation":
        return ROOT / "docs" / "USAGE" / "README.md", fragment
    if path_part.startswith("/documentation/"):
        return ROOT / "docs" / path_part.removeprefix("/documentation/"), fragment
    if path_part.startswith("/docs/USAGE/"):
        return ROOT / "docs" / "USAGE" / path_part.removeprefix("/docs/USAGE/"), fragment
    if path_part.startswith("/"):
        # Other absolute paths are API routes, not repository file links.
        return None, fragment

    resolved = (source.parent / path_part).resolve()
    if resolved.is_dir():
        readme = resolved / "README.md"
        return (readme if readme.exists() else resolved), fragment
    return resolved, fragment


def test_route_inventory_matches_source_and_central_indexes():
    actual = {
        path.name: len(ROUTE_DECORATOR.findall(path.read_text(encoding="utf-8")))
        for path in sorted(ROUTES.glob("*.py"))
        if path.name != "__init__.py"
    }

    assert actual == ROUTE_COUNTS
    assert sum(actual.values()) == 245

    for index in CENTRAL_INDEXES:
        text = index.read_text(encoding="utf-8")
        assert re.search(r"\b245\b.*\b27\b|\b27\b.*\b245\b", text, re.DOTALL)
        for module, count in ROUTE_COUNTS.items():
            assert re.search(
                rf"`{re.escape(module)}`[^\n]*\|\s*{count}\s*\|",
                text,
            ), f"{index.relative_to(ROOT)} has a stale/missing count for {module}"


def test_reference_route_tables_only_list_registered_operations():
    actual = _source_route_operations()
    failures: list[str] = []
    method_pattern = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE)\b")

    for source in sorted((ROOT / "docs" / "USAGE").rglob("reference.md")):
        for line_number, line in enumerate(
            source.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            if not line.startswith("|"):
                continue
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            route_indexes = [
                index
                for index, cell in enumerate(cells)
                if cell.startswith("`/") and cell.endswith("`")
            ]
            if len(route_indexes) != 1:
                continue

            route_index = route_indexes[0]
            if route_index + 1 >= len(cells):
                continue
            methods = method_pattern.findall(cells[route_index + 1])
            route = cells[route_index].strip("`")
            for method in methods:
                operation = (method, _canonical_route(route))
                if operation not in actual:
                    failures.append(
                        f"{source.relative_to(ROOT)}:{line_number} -> "
                        f"unregistered {method} {route}"
                    )

    assert failures == []


def test_local_markdown_links_and_renderer_anchors_resolve():
    failures: list[str] = []

    for source in _documentation_files():
        text = source.read_text(encoding="utf-8")
        for raw_target in MARKDOWN_LINK.findall(text):
            target, fragment = _resolve_local_target(source, raw_target)
            if target is None:
                continue
            if not target.exists():
                failures.append(
                    f"{source.relative_to(ROOT)} -> missing {raw_target}"
                )
                continue
            if not fragment or not target.is_file() or target.suffix.lower() != ".md":
                continue

            target_text = target.read_text(encoding="utf-8")
            anchors = {_slugify(heading) for heading in MARKDOWN_HEADING.findall(target_text)}
            if fragment not in anchors:
                failures.append(
                    f"{source.relative_to(ROOT)} -> missing anchor {raw_target}"
                )

    assert failures == []


def test_markdown_corpus_renders_without_errors():
    failures: list[str] = []

    for source in _documentation_files():
        try:
            rendered = DocumentationRenderer.render_page(
                source.read_text(encoding="utf-8"),
                source.stem,
                str(source.relative_to(ROOT)),
            )
            if "<article>" not in rendered:
                failures.append(
                    f"{source.relative_to(ROOT)} -> missing rendered article"
                )
        except Exception as exc:  # pragma: no cover - reports the source file
            failures.append(f"{source.relative_to(ROOT)} -> {exc!r}")

    assert failures == []


def test_json_code_fences_contain_valid_json():
    failures: list[str] = []

    for source in _documentation_files():
        text = source.read_text(encoding="utf-8")
        for index, block in enumerate(
            re.findall(r"```json\s*\n(.*?)```", text, re.DOTALL),
            start=1,
        ):
            try:
                json.loads(block)
            except json.JSONDecodeError as exc:
                failures.append(
                    f"{source.relative_to(ROOT)} JSON block {index} -> {exc}"
                )

    assert failures == []


def test_retired_route_and_inventory_claims_do_not_return():
    text = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in _documentation_files()
    )

    forbidden = (
        "167 endpoints",
        "17 route modules",
        "/admin/billing/groups",
        "| `/admin/project-groups/{hash}/projects` | GET |",
        "| `GET` | `/admin/project-groups/{hash}/projects` |",
        "The API still accepts `X-token-user` and `X-token-collection`",
        "There is **no rate limiting** on any endpoint",
        "The API accepts any password, including empty strings",
    )
    for stale_claim in forbidden:
        assert stale_claim not in text


def test_maintenance_metadata_is_not_fragile():
    failures: list[str] = []
    fragile_reference = re.compile(
        r"(?:[A-Za-z0-9_./-]+\.(?:py|sql)):\d+"
        r"|commit\s+`[0-9a-f]{7,40}`"
    )

    for source in _documentation_files():
        text = source.read_text(encoding="utf-8", errors="ignore")
        if re.search(r"\*\*Last [Uu]pdated:\*\*", text):
            failures.append(f"{source.relative_to(ROOT)} -> manual update date")
        if fragile_reference.search(text):
            failures.append(
                f"{source.relative_to(ROOT)} -> fragile line/commit reference"
            )

    assert failures == []


def test_documented_repository_file_references_exist():
    failures: list[str] = []

    for source in _documentation_files():
        text = source.read_text(encoding="utf-8", errors="ignore")
        for reference in REPOSITORY_FILE_REFERENCE.findall(text):
            if not (ROOT / reference).exists():
                failures.append(
                    f"{source.relative_to(ROOT)} -> missing {reference}"
                )

    assert failures == []


def test_schema_inventory_matches_canonical_sql():
    schema_files = list((ROOT / "schemas").rglob("*.sql"))
    schema_text = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in schema_files
    )
    schema_index = (ROOT / "schemas" / "docs" / "README.md").read_text(
        encoding="utf-8"
    )

    expected_counts = {
        "Tables": len(re.findall(r"^CREATE TABLE", schema_text, re.MULTILINE)),
        "Indexes": len(
            re.findall(
                r"^CREATE(?: UNIQUE)? INDEX",
                schema_text,
                re.MULTILINE,
            )
        ),
        "Stored Procedures": len(
            re.findall(r"^CREATE PROCEDURE", schema_text, re.MULTILINE)
        ),
        "Functions": len(
            re.findall(r"^CREATE FUNCTION", schema_text, re.MULTILINE)
        ),
        "Views": len(
            re.findall(
                r"^CREATE(?: OR REPLACE)? VIEW",
                schema_text,
                re.MULTILINE,
            )
        ),
        "Triggers": len(
            re.findall(r"^CREATE TRIGGER", schema_text, re.MULTILINE)
        ),
    }
    assert expected_counts == {
        "Tables": 73,
        "Indexes": 83,
        "Stored Procedures": 308,
        "Functions": 1,
        "Views": 18,
        "Triggers": 123,
    }

    for label, count in expected_counts.items():
        assert re.search(
            rf"\*\*{re.escape(label)}\*\*:\s*{count}\b",
            schema_index,
        )

    activity_seed = (
        ROOT / "schemas" / "tables" / "08_activity_logging_tables.sql"
    ).read_text(encoding="utf-8")
    assert len(set(re.findall(r"act-cat-\d{3}", activity_seed))) == 111
    assert "111 seeded" in schema_index
    assert "16 billing IDs reserved in runtime but not yet seeded" in schema_index


def test_documented_activity_type_count_matches_runtime_enum():
    source = (ROOT / "src" / "Util" / "activity_logger.py").read_text(
        encoding="utf-8"
    )
    module = ast.parse(source)
    enum_class = next(
        node
        for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == "ActivityType"
    )
    count = sum(
        1
        for node in enum_class.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
    )
    assert count == 112

    for relative in (
        "docs/USAGE/audit_logs/reference.md",
        "docs/USAGE/audit_logs/usage.md",
    ):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "112" in text


def test_first_root_bootstrap_caveat_matches_source():
    seed = (
        ROOT / "schemas" / "tables" / "05_initialize_data.sql"
    ).read_text(encoding="utf-8")
    scripts = "\n".join(
        (ROOT / relative).read_text(encoding="utf-8")
        for relative in (
            "scripts/create_database.py",
            "scripts/recreate_database.py",
        )
    )
    verifier = (ROOT / "src" / "Util" / "password_security.py").read_text(
        encoding="utf-8"
    )
    guide = (ROOT / "docs" / "USAGE" / "getting-started.md").read_text(
        encoding="utf-8"
    )

    seeded_password = re.search(r"Password hash for '([^']+)'", seed)
    printed_passwords = set(
        re.findall(r'print\("    Password: ([^"]+)"\)', scripts)
    )

    assert seeded_password is not None
    assert printed_passwords
    assert seeded_password.group(1) in guide
    for printed_password in printed_passwords:
        assert f"`{printed_password}`" in guide
    assert "self.hasher.verify(hashed_password, password)" in verifier
    assert "Argon2id" in guide
    assert "cannot log in" in guide


def test_central_contracts_cover_current_high_risk_boundaries():
    combined = "\n".join(
        index.read_text(encoding="utf-8").lower()
        for index in CENTRAL_INDEXES
    )

    for required in (
        "user-agent",
        "8 mib",
        "session_token",
        "refresh_token",
        "plan",
        "allowed_origins",
        "internal/email",
        "billing group",
        "hard",
    ):
        assert required in combined
