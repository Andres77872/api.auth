"""Database wrappers for Google external account stored procedures.

Trace: `.dev/sdd/changes/google-oauth-login/tasks.md` task 5.7.

Security posture:
- Callers pass application-computed HMAC hashes and masked snapshots only.
- No Google token material is accepted by these wrappers.
- Error contexts avoid raw provider subject, email, and provider-init data.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Mapping

from src.Util.db_config import get_connection
from src.Util.db_error_wrapper import handle_db_operation


def _json_param(value: Mapping[str, Any] | list[Any] | str | None) -> str | None:
    if value is None or isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


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


def _row_to_dict(row: tuple[Any, ...] | None, description) -> dict[str, Any] | None:
    if row is None or not description:
        return None
    columns = [desc[0] for desc in description]
    result = dict(zip(columns, row))
    if "metadata" in result:
        result["metadata"] = _decode_json_field(result["metadata"])
    return result


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


def _fetch_one_dict(cur) -> dict[str, Any] | None:
    if not _advance_to_result_set(cur):
        return None
    description = cur.description
    row = cur.fetchone()
    result = _row_to_dict(row, description)
    _drain_remaining_result_sets(cur)
    return result


def _callproc_one(proc_name: str, args: list[Any], *, context: str, commit: bool = False) -> dict[str, Any] | None:
    def _operation():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc(proc_name, args)
            result = _fetch_one_dict(cur)
            if commit:
                con.commit()
            return result

    return handle_db_operation(_operation, error_context=context)


def get_user_by_external_account(
    *,
    provider: str,
    provider_sub_hash: bytes,
    identity_namespace: str | None = None,
) -> dict[str, Any] | None:
    """Resolve an active external account to its local user.

    With ``identity_namespace`` the lookup keys on ``(namespace, subject HMAC)``; without
    it the historical provider-keyed procedure is used (Patreon and older callers).
    """

    if identity_namespace:
        return _callproc_one(
            "sp_get_user_by_external_identity",
            [identity_namespace, provider_sub_hash],
            context=f"get_user_by_external_identity(provider={provider})",
        )
    return _callproc_one(
        "sp_get_user_by_external_account",
        [provider, provider_sub_hash],
        context=f"get_user_by_external_account(provider={provider})",
    )


def link_external_account(
    *,
    external_account_id: str,
    user_id: str,
    provider: str,
    provider_sub_hash: bytes,
    provider_sub_fingerprint: str,
    provider_email_hash: bytes | None = None,
    provider_email_masked: str | None = None,
    provider_email_verified_at_link: bool = False,
    linked_by: str | None = None,
    metadata: Mapping[str, Any] | list[Any] | str | None = None,
    identity_namespace: str | None = None,
    connection_id: str | None = None,
) -> dict[str, Any] | None:
    """Link an external account to an existing active consumer."""

    if identity_namespace:
        return _callproc_one(
            "sp_link_external_identity",
            [
                external_account_id,
                user_id,
                provider,
                identity_namespace,
                connection_id,
                provider_sub_hash,
                provider_sub_fingerprint,
                provider_email_hash,
                provider_email_masked,
                provider_email_verified_at_link,
                linked_by,
                _json_param(metadata),
            ],
            context=f"link_external_identity(user_id={user_id}, provider={provider})",
            commit=True,
        )
    return _callproc_one(
        "sp_link_external_account",
        [
            external_account_id,
            user_id,
            provider,
            provider_sub_hash,
            provider_sub_fingerprint,
            provider_email_hash,
            provider_email_masked,
            provider_email_verified_at_link,
            linked_by,
            _json_param(metadata),
        ],
        context=f"link_external_account(user_id={user_id}, provider={provider})",
        commit=True,
    )


def unlink_external_account(
    *,
    user_id: str,
    provider: str,
    unlinked_by: str | None,
    reason: str | None = None,
    identity_namespace: str | None = None,
) -> dict[str, Any] | None:
    """Soft-unlink a user's active external account.

    Returns a falsy value when nothing was linked, so callers can answer "not linked".
    """

    if identity_namespace:
        result = _callproc_one(
            "sp_unlink_external_identity",
            [user_id, provider, identity_namespace, unlinked_by, reason],
            context=f"unlink_external_identity(user_id={user_id}, provider={provider})",
            commit=True,
        )
        return result if result and int(result.get("unlinked") or 0) > 0 else None
    return _callproc_one(
        "sp_unlink_external_account",
        [user_id, provider, unlinked_by, reason],
        context=f"unlink_external_account(user_id={user_id}, provider={provider})",
        commit=True,
    )


def touch_external_account_last_seen(
    *,
    provider: str,
    provider_sub_hash: bytes,
    provider_email_hash: bytes | None = None,
    provider_email_masked: str | None = None,
    provider_email_verified_at_link: bool | None = None,
    identity_namespace: str | None = None,
) -> dict[str, Any] | None:
    """Refresh last-seen and masked snapshots for a linked external account."""

    if identity_namespace:
        return _callproc_one(
            "sp_touch_external_identity_last_seen",
            [
                identity_namespace,
                provider_sub_hash,
                provider_email_hash,
                provider_email_masked,
                provider_email_verified_at_link,
            ],
            context=f"touch_external_identity_last_seen(provider={provider})",
            commit=True,
        )
    return _callproc_one(
        "sp_touch_external_account_last_seen",
        [
            provider,
            provider_sub_hash,
            provider_email_hash,
            provider_email_masked,
            provider_email_verified_at_link,
        ],
        context=f"touch_external_account_last_seen(provider={provider})",
        commit=True,
    )


def create_consumer_user_from_external_account(
    *,
    user_id: str,
    user_hash: str,
    username: str,
    password_hash: str,
    external_account_id: str,
    provider: str,
    provider_sub_hash: bytes,
    provider_sub_fingerprint: str,
    provider_email_hash: bytes | None = None,
    provider_email_masked: str | None = None,
    provider_email_verified_at_link: bool = False,
    user_email_id: str | None = None,
    email_normalized: str | None = None,
    group_member_id: str | None = None,
    user_group_id: str | None = None,
    created_by: str | None = None,
    metadata: Mapping[str, Any] | list[Any] | str | None = None,
    identity_namespace: str | None = None,
    connection_id: str | None = None,
    binding_id: str | None = None,
) -> dict[str, Any] | None:
    """Create a local consumer and link an external account transactionally.

    If email fields are supplied, the local email row is created as pending; provider
    email verification never activates local email authority here. When ``binding_id``
    is given, the stored procedure reads the provisioning policy and the group from the
    binding row inside the same transaction and ignores ``user_group_id``.
    """

    if identity_namespace:
        return _callproc_one(
            "sp_create_consumer_user_from_external_identity",
            [
                user_id,
                user_hash,
                username,
                password_hash,
                external_account_id,
                provider,
                identity_namespace,
                connection_id,
                binding_id,
                provider_sub_hash,
                provider_sub_fingerprint,
                provider_email_hash,
                provider_email_masked,
                provider_email_verified_at_link,
                user_email_id,
                email_normalized,
                group_member_id,
                user_group_id,
                created_by,
                _json_param(metadata),
            ],
            context=f"create_consumer_user_from_external_identity(user_id={user_id}, provider={provider})",
            commit=True,
        )
    return _callproc_one(
        "sp_create_consumer_user_from_external_account",
        [
            user_id,
            user_hash,
            username,
            password_hash,
            external_account_id,
            provider,
            provider_sub_hash,
            provider_sub_fingerprint,
            provider_email_hash,
            provider_email_masked,
            provider_email_verified_at_link,
            user_email_id,
            email_normalized,
            group_member_id,
            user_group_id,
            created_by,
            _json_param(metadata),
        ],
        context=f"create_consumer_user_from_external_account(user_id={user_id}, provider={provider})",
        commit=True,
    )


def list_external_accounts_for_user(*, user_id: str) -> list[dict[str, Any]]:
    """Linked external identities of one user: masked/fingerprint fields only."""

    def _operation():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc("sp_list_external_accounts_for_user", [user_id])
            rows: list[dict[str, Any]] = []
            if _advance_to_result_set(cur):
                description = cur.description
                for row in cur.fetchall() or []:
                    item = _row_to_dict(row, description)
                    if item:
                        rows.append(item)
            _drain_remaining_result_sets(cur)
            return rows

    return handle_db_operation(_operation, error_context=f"list_external_accounts_for_user(user_id={user_id})")


__all__ = [
    "get_user_by_external_account",
    "link_external_account",
    "unlink_external_account",
    "touch_external_account_last_seen",
    "create_consumer_user_from_external_account",
    "list_external_accounts_for_user",
]
