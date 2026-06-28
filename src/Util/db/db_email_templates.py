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

import json
from typing import Any

from src.Util.db_config import get_connection
from src.Util.db_error_wrapper import handle_db_operation


def _row_to_dict(row: tuple[Any, ...] | None, description) -> dict[str, Any] | None:
    if row is None or not description:
        return None
    result = dict(zip([desc[0] for desc in description], row))
    for key in ("allowed_variables", "required_variables"):
        if key in result:
            result[key] = _decode_json_field(result[key])
    return result


def _decode_json_field(value: Any) -> Any:
    if isinstance(value, (dict, list)) or value is None:
        return value
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="ignore")
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _json_list(value: list[str] | tuple[str, ...]) -> str:
    return json.dumps(list(value), sort_keys=True, separators=(",", ":"))


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
    """Return catalog metadata plus the active version row when one exists."""

    return _callproc_one(
        "sp_email_template_get_active",
        [template_code],
        context=f"get_active_template(template_code={template_code})",
    )


def list_active_templates() -> list[dict[str, Any]]:
    """Return catalog metadata plus active-version summaries for every code."""

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


def create_dynamic_template(
    *,
    template_id: str,
    template_code: str,
    purpose: str,
    allowed_variables: list[str] | tuple[str, ...],
    required_variables: list[str] | tuple[str, ...],
    subject_template: str,
    html_template: str,
    text_template: str,
) -> dict[str, Any] | None:
    """Create a dynamic internal template catalog row plus version 1 atomically."""

    return _callproc_one(
        "sp_email_template_create_dynamic",
        [
            template_id,
            template_code,
            purpose,
            _json_list(tuple(allowed_variables)),
            _json_list(tuple(required_variables)),
            subject_template,
            html_template,
            text_template,
        ],
        context=f"create_dynamic_template(template_code={template_code})",
        commit=True,
    )


def disable_template(*, template_code: str, disabled_by: str | None) -> dict[str, Any] | None:
    """Disable a template code without deleting version history."""

    return _callproc_one(
        "sp_email_template_disable",
        [template_code, disabled_by],
        context=f"disable_template(template_code={template_code})",
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


__all__ = [
    "create_dynamic_template",
    "disable_template",
    "get_active_template",
    "get_template_version",
    "list_active_templates",
    "list_template_versions",
    "rollback_template",
    "save_and_activate_template",
]
