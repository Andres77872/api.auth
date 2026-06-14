"""Database wrappers for DB-managed transactional email templates.

Trace:
- Email templates editor feature.
- Follows the repository convention: stored procedures own state transitions
  (incl. the single-active-per-code invariant); Python wrappers use
  ``get_connection()`` + positional ``callproc(...)`` + ``handle_db_operation``.

Security posture:
- These rows hold template *structure* only (subject/html/text with ``$name``
  placeholders), never recipient data, tokens, or rendered links.
- Read failures here are non-fatal: ``src.Util.email.templates.resolve_template``
  falls back to the in-code defaults so delivery never depends on this table.
"""

from __future__ import annotations

from typing import Any

from src.Util.db_config import get_connection
from src.Util.db_error_wrapper import handle_db_operation


def _row_to_dict(row: tuple[Any, ...] | None, description) -> dict[str, Any] | None:
    if row is None or not description:
        return None
    return dict(zip([desc[0] for desc in description], row))


def _advance_to_result_set(cur) -> bool:
    if cur.description:
        return True
    while cur.nextset():
        if cur.description:
            return True
    return False


def _drain_remaining_result_sets(cur) -> None:
    while cur.nextset():
        pass


def _callproc_one(
    proc_name: str, args: list[Any], *, context: str, commit: bool = False
) -> dict[str, Any] | None:
    def _operation():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc(proc_name, args)
            result: dict[str, Any] | None = None
            if _advance_to_result_set(cur):
                result = _row_to_dict(cur.fetchone(), cur.description)
            _drain_remaining_result_sets(cur)
            if commit:
                con.commit()
            return result

    return handle_db_operation(_operation, error_context=context)


def _callproc_all(
    proc_name: str, args: list[Any], *, context: str
) -> list[dict[str, Any]]:
    def _operation():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc(proc_name, args)
            rows: list[dict[str, Any] | None] = []
            if _advance_to_result_set(cur):
                description = cur.description
                rows = [_row_to_dict(row, description) for row in cur.fetchall()]
            _drain_remaining_result_sets(cur)
            return [row for row in rows if row is not None]

    return handle_db_operation(_operation, error_context=context, default_return=[])


def get_active_template(template_code: str) -> dict[str, Any] | None:
    """Return the active version row for a code, or None when unseeded."""

    return _callproc_one(
        "sp_email_template_get_active",
        [template_code],
        context=f"get_active_template(template_code={template_code})",
    )


def list_active_templates() -> list[dict[str, Any]]:
    """Return the active version of every seeded code (subject only)."""

    return _callproc_all(
        "sp_email_template_list",
        [],
        context="list_active_templates",
    )


def list_template_versions(template_code: str) -> list[dict[str, Any]]:
    """Return version-history metadata for a code (newest first)."""

    return _callproc_all(
        "sp_email_template_versions",
        [template_code],
        context=f"list_template_versions(template_code={template_code})",
    )


def get_template_version(template_code: str, version: int) -> dict[str, Any] | None:
    """Return the full bodies of one specific version."""

    return _callproc_one(
        "sp_email_template_get_version",
        [template_code, int(version)],
        context=f"get_template_version(template_code={template_code}, version={version})",
    )


def save_and_activate_template(
    *,
    template_id: str,
    template_code: str,
    subject_template: str,
    html_template: str,
    text_template: str,
) -> dict[str, Any] | None:
    """Insert a new version and make it the single active one, atomically."""

    return _callproc_one(
        "sp_email_template_save_and_activate",
        [template_id, template_code, subject_template, html_template, text_template],
        context=f"save_and_activate_template(template_code={template_code})",
        commit=True,
    )


def rollback_template(*, template_code: str, version: int) -> dict[str, Any] | None:
    """Re-activate an existing prior version, atomically single-active."""

    return _callproc_one(
        "sp_email_template_rollback",
        [template_code, int(version)],
        context=f"rollback_template(template_code={template_code}, version={version})",
        commit=True,
    )
