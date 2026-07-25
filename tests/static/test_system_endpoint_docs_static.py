"""Static documentation contracts for protected system detail endpoints."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROTECTED_PATHS = ("/system/health", "/system/info")
FORBIDDEN_PUBLIC_CLAIMS = (
    "public system info",
    "system info (public)",
    "basic system information (no auth required)",
    "detailed system health status (no auth required)",
    "worst public status",
)
FORBIDDEN_ROUTE_LINE_MARKERS = (
    "(public)",
    "no auth required",
    "without authentication",
    "unauthenticated",
    "| no |",
)


def _documentation_files() -> list[Path]:
    files = [ROOT / "README.md", ROOT / "src" / "README.md"]
    files.extend(sorted((ROOT / "docs").rglob("*.md")))
    return [path for path in files if path.exists()]


def _curl_commands(text: str) -> list[str]:
    """Return shell curl commands, including backslash continuations."""

    lines = text.splitlines()
    commands: list[str] = []
    index = 0
    while index < len(lines):
        if not lines[index].lstrip().startswith("curl "):
            index += 1
            continue

        command_lines = [lines[index]]
        while command_lines[-1].rstrip().endswith("\\") and index + 1 < len(lines):
            index += 1
            command_lines.append(lines[index])
        commands.append("\n".join(command_lines))
        index += 1
    return commands


def test_docs_never_describe_system_health_or_info_as_public():
    offenders: list[str] = []
    for path in _documentation_files():
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        for claim in FORBIDDEN_PUBLIC_CLAIMS:
            if claim in text:
                offenders.append(f"{path.relative_to(ROOT)} contains {claim!r}")
        for line_number, line in enumerate(text.splitlines(), start=1):
            if not any(route in line for route in PROTECTED_PATHS):
                continue
            for marker in FORBIDDEN_ROUTE_LINE_MARKERS:
                if marker in line:
                    offenders.append(
                        f"{path.relative_to(ROOT)}:{line_number} contains {marker!r}"
                    )

    assert offenders == []


def test_protected_system_curl_examples_include_a_session_transport():
    offenders: list[str] = []
    for path in _documentation_files():
        for command in _curl_commands(path.read_text(encoding="utf-8", errors="ignore")):
            lowered = command.lower()
            if not any(route in lowered for route in PROTECTED_PATHS):
                continue
            has_bearer = "authorization: bearer" in lowered
            has_session_cookie = "cookie:" in lowered and "session_token=" in lowered
            if not (has_bearer or has_session_cookie):
                offenders.append(
                    f"{path.relative_to(ROOT)}: {command.splitlines()[0].strip()}"
                )

    assert offenders == []
