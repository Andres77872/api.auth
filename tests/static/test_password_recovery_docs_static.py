"""RED static docs/schema secret-safety checks for password recovery delta.

Trace: `.dev/sdd/changes/password-recovery-email-validation/tasks.md` task 1.10.
"""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DOCS_AND_SCHEMA_DOCS = [
    *ROOT.glob("docs/**/*.md"),
    *ROOT.glob("schemas/docs/**/*.md"),
]
SCHEMA_SQL = [*ROOT.glob("schemas/**/*.sql")]


def _read(path: Path) -> str:
    return path.read_text(errors="ignore")


def _matching_lines(paths: list[Path], pattern: str) -> list[str]:
    regex = re.compile(pattern, re.IGNORECASE)
    matches: list[str] = []
    for path in paths:
        for number, line in enumerate(_read(path).splitlines(), start=1):
            if regex.search(line):
                matches.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()}")
    return matches


def _without_safe_negations(lines: list[str]) -> list[str]:
    safe_markers = (
        " no ",
        " not ",
        " never ",
        " without ",
        " no longer ",
        " does not ",
        " do not ",
        "must not",
        "won't",
        "not return",
        "not expose",
    )
    unsafe = []
    for line in lines:
        normalized = f" {line.lower()} "
        if any(marker in normalized for marker in safe_markers):
            continue
        unsafe.append(line)
    return unsafe


def test_docs_do_not_present_plaintext_or_temporary_passwords_recovery_codes_or_reset_tokens_as_response_examples():
    forbidden_patterns = [
        r"plain[_ -]?text[_ -]?password",
        r"temporary[_ -]?password",
        r"recovery[_ -]?code",
        r"one[_ -]?time[_ -]?password",
        r"reset[_ -]?token",
        r"reset[_ -]?url",
        r"provider[_ -]?payload",
    ]
    offenders: list[str] = []
    for pattern in forbidden_patterns:
        offenders.extend(_matching_lines(DOCS_AND_SCHEMA_DOCS, pattern))
    offenders = _without_safe_negations(offenders)

    assert offenders == []


def test_docs_do_not_advertise_dead_forced_change_controls_as_live_contract():
    offenders = _matching_lines(
        DOCS_AND_SCHEMA_DOCS,
        r"force_password_reset|must_change_on_login",
    )
    offenders = _without_safe_negations(offenders)

    assert offenders == []


def test_schema_docs_identify_user_email_link_tokens_not_legacy_reset_table_as_live_recovery_storage():
    legacy_docs = _matching_lines(
        DOCS_AND_SCHEMA_DOCS,
        r"user_password_resets",
    )

    assert legacy_docs == []

    modern_mentions = _matching_lines(
        DOCS_AND_SCHEMA_DOCS,
        r"user_email_link_tokens",
    )
    assert modern_mentions, "docs must name user_email_link_tokens as the live hash-only reset store"


def test_schema_sql_no_longer_creates_plaintext_legacy_reset_storage_or_indexes():
    offenders = _matching_lines(
        SCHEMA_SQL,
        r"CREATE TABLE IF NOT EXISTS user_password_resets|idx_user_password_resets|reset_token VARCHAR|tr_validate_password_reset_expiry",
    )

    assert offenders == []


def test_docs_and_schema_examples_do_not_contain_full_reset_urls():
    offenders = _matching_lines(
        DOCS_AND_SCHEMA_DOCS,
        r"https?://\S*(reset|password)[^\s)`'\"]*(token|lookup|secret)=",
    )

    assert offenders == []
