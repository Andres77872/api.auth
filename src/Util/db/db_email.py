"""Database wrappers for transactional auth email stored procedures.

Trace:
- SDD `email-activation` task 4.10.
- Design decision: stored procedures own lifecycle state transitions; Python
  wrappers follow the existing `get_connection()` + positional `callproc(...)` +
  `handle_db_operation(...)` convention used by the repository.

Security posture:
- Do not log plaintext recipients, token secrets, full links, provider payloads,
  or raw idempotency keys in error contexts.
- Admin/delivery log helpers expose only hash + masked recipient fields.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Mapping

from src.Util.db_config import get_connection
from src.Util.db_error_wrapper import handle_db_operation


GENERIC_PUBLIC_REPLAY_BODY = {
    "success": True,
    "message": "If the request can be processed, it has been accepted.",
}


def _json_param(value: Mapping[str, Any] | list[Any] | str | None) -> str:
    if value is None:
        return json.dumps(GENERIC_PUBLIC_REPLAY_BODY, sort_keys=True, separators=(",", ":"))
    if isinstance(value, str):
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
    for key in ("replay_body", "response_metadata", "metadata"):
        if key in result:
            result[key] = _decode_json_field(result[key])
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


def _fetch_all_dicts(cur) -> list[dict[str, Any]]:
    if not _advance_to_result_set(cur):
        return []
    description = cur.description
    rows = cur.fetchall()
    results = [_row_to_dict(row, description) for row in rows]
    _drain_remaining_result_sets(cur)
    return [row for row in results if row is not None]


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


def _callproc_all(proc_name: str, args: list[Any], *, context: str, commit: bool = False) -> list[dict[str, Any]]:
    def _operation():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc(proc_name, args)
            result = _fetch_all_dicts(cur)
            if commit:
                con.commit()
            return result

    return handle_db_operation(_operation, error_context=context, default_return=[])


# =============================================================================
# User email lifecycle and activation tokens
# =============================================================================


def add_user_email_and_enqueue(
    *,
    user_email_id: str,
    user_id: str,
    email_normalized: str,
    email_hash: bytes,
    email_masked: str,
    token_id: str,
    lookup_id: str,
    token_hash: bytes,
    token_fingerprint: str,
    token_expires_at: datetime,
    email_message_id: str,
    provider: str,
    provider_idempotency_key: str,
    render_payload_ciphertext: bytes,
    created_by: str | None,
    created_ip_hash: bytes | None,
    idempotency_id: str | None = None,
    idempotency_scope: str | None = None,
    idempotency_key_hash: bytes | None = None,
    idempotency_request_hash: bytes | None = None,
    idempotency_expires_at: datetime | None = None,
) -> dict[str, Any] | None:
    return _callproc_one(
        "sp_user_email_add_and_enqueue",
        [
            user_email_id,
            user_id,
            email_normalized,
            email_hash,
            email_masked,
            token_id,
            lookup_id,
            token_hash,
            token_fingerprint,
            token_expires_at,
            email_message_id,
            provider,
            provider_idempotency_key,
            render_payload_ciphertext,
            created_by,
            created_ip_hash,
            idempotency_id,
            idempotency_scope,
            idempotency_key_hash,
            idempotency_request_hash,
            idempotency_expires_at,
        ],
        context=f"add_user_email_and_enqueue(user_id={user_id}, user_email_id={user_email_id})",
        commit=True,
    )


def resend_user_email_activation(
    *,
    user_id: str,
    user_email_id: str,
    token_id: str,
    lookup_id: str,
    token_hash: bytes,
    token_fingerprint: str,
    token_expires_at: datetime,
    email_message_id: str,
    provider: str,
    provider_idempotency_key: str,
    render_payload_ciphertext: bytes,
    created_ip_hash: bytes | None,
    idempotency_id: str | None = None,
    idempotency_scope: str | None = None,
    idempotency_key_hash: bytes | None = None,
    idempotency_request_hash: bytes | None = None,
    idempotency_expires_at: datetime | None = None,
    cooldown_seconds: int | None = None,
) -> dict[str, Any] | None:
    return _callproc_one(
        "sp_user_email_resend_and_enqueue",
        [
            user_id,
            user_email_id,
            token_id,
            lookup_id,
            token_hash,
            token_fingerprint,
            token_expires_at,
            email_message_id,
            provider,
            provider_idempotency_key,
            render_payload_ciphertext,
            created_ip_hash,
            idempotency_id,
            idempotency_scope,
            idempotency_key_hash,
            idempotency_request_hash,
            idempotency_expires_at,
            cooldown_seconds,
        ],
        context=f"resend_user_email_activation(user_id={user_id}, user_email_id={user_email_id})",
        commit=True,
    )


def consume_email_activation_token(
    *,
    lookup_id: str,
    token_hash: bytes,
    consumed_ip_hash: bytes | None,
    consumed_user_agent_hash: bytes | None,
) -> dict[str, Any] | None:
    return _callproc_one(
        "sp_consume_email_activation_token",
        [lookup_id, token_hash, consumed_ip_hash, consumed_user_agent_hash],
        context="consume_email_activation_token(lookup_id=[REDACTED])",
        commit=True,
    )


def remove_user_email(*, user_id: str, user_email_id: str, removed_by: str | None) -> dict[str, Any] | None:
    return _callproc_one(
        "sp_user_email_remove",
        [user_id, user_email_id, removed_by],
        context=f"remove_user_email(user_id={user_id}, user_email_id={user_email_id})",
        commit=True,
    )


def set_primary_user_email(*, user_id: str, user_email_id: str) -> dict[str, Any] | None:
    return _callproc_one(
        "sp_user_email_set_primary",
        [user_id, user_email_id],
        context=f"set_primary_user_email(user_id={user_id}, user_email_id={user_email_id})",
        commit=True,
    )


def list_user_emails(user_id: str) -> list[dict[str, Any]]:
    return _callproc_all(
        "sp_user_email_list_for_user",
        [user_id],
        context=f"list_user_emails(user_id={user_id})",
    )


def list_admin_user_emails(target_user_id: str) -> list[dict[str, Any]]:
    return _callproc_all(
        "sp_admin_user_email_list",
        [target_user_id],
        context=f"list_admin_user_emails(target_user_id={target_user_id})",
    )


# =============================================================================
# Password reset link enqueue / consume
# =============================================================================


def enqueue_password_reset_link(
    *,
    identifier: str,
    token_id: str,
    lookup_id: str,
    token_hash: bytes,
    token_fingerprint: str,
    token_expires_at: datetime,
    email_message_id: str,
    provider: str,
    provider_idempotency_key: str,
    render_payload_ciphertext: bytes,
    created_ip_hash: bytes | None,
    idempotency_id: str | None = None,
    idempotency_scope: str | None = None,
    idempotency_key_hash: bytes | None = None,
    idempotency_request_hash: bytes | None = None,
    idempotency_expires_at: datetime | None = None,
) -> dict[str, Any] | None:
    return _callproc_one(
        "sp_password_reset_link_enqueue",
        [
            identifier,
            token_id,
            lookup_id,
            token_hash,
            token_fingerprint,
            token_expires_at,
            email_message_id,
            provider,
            provider_idempotency_key,
            render_payload_ciphertext,
            created_ip_hash,
            idempotency_id,
            idempotency_scope,
            idempotency_key_hash,
            idempotency_request_hash,
            idempotency_expires_at,
        ],
        context="enqueue_password_reset_link(identifier=[REDACTED])",
        commit=True,
    )


def enqueue_admin_password_reset_link(
    *,
    target_user_id: str,
    created_by: str,
    token_id: str,
    lookup_id: str,
    token_hash: bytes,
    token_fingerprint: str,
    token_expires_at: datetime,
    email_message_id: str,
    provider: str,
    provider_idempotency_key: str,
    render_payload_ciphertext: bytes,
    created_ip_hash: bytes | None,
) -> dict[str, Any] | None:
    return _callproc_one(
        "sp_admin_password_reset_link_enqueue",
        [
            target_user_id,
            created_by,
            token_id,
            lookup_id,
            token_hash,
            token_fingerprint,
            token_expires_at,
            email_message_id,
            provider,
            provider_idempotency_key,
            render_payload_ciphertext,
            created_ip_hash,
        ],
        context=f"enqueue_admin_password_reset_link(target_user_id={target_user_id})",
        commit=True,
    )


def consume_password_reset_token(
    *,
    lookup_id: str,
    token_hash: bytes,
    new_password_hash: str,
    consumed_ip_hash: bytes | None,
    consumed_user_agent_hash: bytes | None,
) -> dict[str, Any] | None:
    return _callproc_one(
        "sp_consume_password_reset_token",
        [lookup_id, token_hash, new_password_hash, consumed_ip_hash, consumed_user_agent_hash],
        context="consume_password_reset_token(lookup_id=[REDACTED])",
        commit=True,
    )


# =============================================================================
# Outbox worker and provider webhook wrappers
# =============================================================================


def claim_email_messages(*, worker_id: str, limit: int, lease_seconds: int) -> list[dict[str, Any]]:
    return _callproc_all(
        "sp_claim_email_messages",
        [worker_id, limit, lease_seconds],
        context=f"claim_email_messages(worker_id={worker_id}, limit={limit})",
        commit=True,
    )


def finalize_email_message(
    *,
    email_message_id: str,
    status: str,
    provider_message_id: str | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    retry_after_seconds: int | None = None,
) -> dict[str, Any] | None:
    return _callproc_one(
        "sp_finalize_email_message",
        [email_message_id, status, provider_message_id, error_code, error_message, retry_after_seconds],
        context=f"finalize_email_message(email_message_id={email_message_id}, status={status})",
        commit=True,
    )


def record_email_delivery_attempt(
    *,
    attempt_id: str,
    email_message_id: str,
    attempt_no: int,
    provider: str,
    status: str,
    provider_message_id: str | None = None,
    provider_event_id: str | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    response_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    return _callproc_one(
        "sp_record_email_delivery_attempt",
        [
            attempt_id,
            email_message_id,
            attempt_no,
            provider,
            status,
            provider_message_id,
            provider_event_id,
            error_code,
            error_message,
            _json_param(response_metadata or {}),
        ],
        context=f"record_email_delivery_attempt(email_message_id={email_message_id}, attempt_no={attempt_no})",
        commit=True,
    )


def apply_email_provider_event(
    *,
    delivery_attempt_id: str | None,
    email_message_id: str | None,
    provider: str,
    provider_message_id: str | None,
    provider_event_id: str | None,
    event_type: str,
    recipient_hash: bytes | None,
    suppression_id: str | None,
    response_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    return _callproc_one(
        "sp_apply_email_provider_event",
        [
            delivery_attempt_id,
            email_message_id,
            provider,
            provider_message_id,
            provider_event_id,
            event_type,
            recipient_hash,
            suppression_id,
            _json_param(response_metadata or {}),
        ],
        context=f"apply_email_provider_event(provider={provider}, event_type={event_type})",
        commit=True,
    )


# =============================================================================
# Durable idempotency wrappers
# =============================================================================


def begin_email_idempotency(
    *,
    idempotency_id: str,
    scope: str,
    key_hash: bytes,
    request_hash: bytes,
    user_id: str | None,
    recipient_hash: bytes | None,
    expires_at: datetime,
    replay_body: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    return _callproc_one(
        "sp_email_idempotency_begin",
        [idempotency_id, scope, key_hash, request_hash, user_id, recipient_hash, expires_at, _json_param(replay_body)],
        context=f"begin_email_idempotency(scope={scope}, idempotency_id={idempotency_id})",
        commit=True,
    )


def complete_email_idempotency(
    *,
    scope: str,
    key_hash: bytes,
    email_message_id: str | None,
    replay_status_code: int = 202,
    replay_body: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    return _callproc_one(
        "sp_email_idempotency_complete",
        [scope, key_hash, email_message_id, replay_status_code, _json_param(replay_body)],
        context=f"complete_email_idempotency(scope={scope}, email_message_id={email_message_id})",
        commit=True,
    )


def get_email_idempotency(*, scope: str, key_hash: bytes) -> dict[str, Any] | None:
    return _callproc_one(
        "sp_email_idempotency_get",
        [scope, key_hash],
        context=f"get_email_idempotency(scope={scope})",
    )


# =============================================================================
# Retention, anonymization, migration inventory
# =============================================================================


def backfill_legacy_user_emails() -> dict[str, Any] | None:
    return _callproc_one(
        "sp_backfill_legacy_user_emails",
        [],
        context="backfill_legacy_user_emails()",
        commit=True,
    )


def run_email_retention_purge() -> dict[str, Any] | None:
    return _callproc_one(
        "sp_email_retention_purge",
        [],
        context="run_email_retention_purge()",
        commit=True,
    )


def anonymize_user_email_data(user_id: str) -> dict[str, Any] | None:
    return _callproc_one(
        "sp_anonymize_user_email_data",
        [user_id],
        context=f"anonymize_user_email_data(user_id={user_id})",
        commit=True,
    )


# =============================================================================
# Admin logs, suppression checks, and health queries
# =============================================================================


def list_email_delivery_logs(
    *,
    limit: int = 50,
    offset: int = 0,
    status: str | None = None,
    purpose: str | None = None,
    provider: str | None = None,
) -> list[dict[str, Any]]:
    """Return delivery log rows without plaintext recipient/body/template vars."""

    def _operation():
        clauses = []
        params: list[Any] = []
        if status:
            clauses.append("em.status = %s")
            params.append(status)
        if purpose:
            clauses.append("em.purpose = %s")
            params.append(purpose)
        if provider:
            clauses.append("em.provider = %s")
            params.append(provider)

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"""
            SELECT em.id,
                   em.user_id,
                   em.user_email_id,
                   em.purpose,
                   em.template_code,
                   HEX(em.recipient_hash) AS recipient_hash,
                   em.recipient_masked,
                   em.provider,
                   em.provider_message_id,
                   em.status,
                   em.priority,
                   em.attempt_count,
                   em.max_attempts,
                   em.next_attempt_at,
                   em.sent_at,
                   em.terminal_at,
                   em.last_error_code,
                   em.created_at,
                   em.updated_at
            FROM email_messages em
            {where_sql}
            ORDER BY em.created_at DESC
            LIMIT %s OFFSET %s
        """
        params.extend([int(limit), int(offset)])
        with get_connection() as con:
            cur = con.cursor()
            cur.execute(query, params)
            return _fetch_all_dicts(cur)

    return handle_db_operation(
        _operation,
        error_context=f"list_email_delivery_logs(limit={limit}, offset={offset})",
        default_return=[],
    )


def is_recipient_suppressed(recipient_hash: bytes) -> bool:
    def _operation():
        with get_connection() as con:
            cur = con.cursor()
            cur.execute(
                """
                SELECT 1
                FROM email_suppressions
                WHERE email_hash = %s
                  AND is_active = TRUE
                LIMIT 1
                """,
                [recipient_hash],
            )
            return cur.fetchone() is not None

    return handle_db_operation(
        _operation,
        error_context="is_recipient_suppressed(recipient_hash=[REDACTED])",
        default_return=False,
    )


def get_email_outbox_health() -> dict[str, Any]:
    """Return outbox status counts for future system health surfaces."""

    def _operation():
        with get_connection() as con:
            cur = con.cursor()
            cur.execute(
                """
                SELECT COALESCE(SUM(status = 'pending'), 0) AS pending_count,
                       COALESCE(SUM(status = 'processing'), 0) AS processing_count,
                       COALESCE(SUM(status = 'retry'), 0) AS retry_count,
                       COALESCE(SUM(status = 'dead'), 0) AS dead_count,
                       COALESCE(SUM(status = 'sent'), 0) AS sent_count,
                       COALESCE(SUM(status IN ('delivered','bounced','complained','suppressed','cancelled')), 0) AS terminal_count,
                       TIMESTAMPDIFF(
                           SECOND,
                           MIN(CASE WHEN status IN ('pending','retry') THEN created_at ELSE NULL END),
                           NOW()
                       ) AS oldest_pending_age_seconds
                FROM email_messages
                """
            )
            return _fetch_one_dict(cur) or {
                "pending_count": 0,
                "processing_count": 0,
                "retry_count": 0,
                "dead_count": 0,
                "sent_count": 0,
                "terminal_count": 0,
                "oldest_pending_age_seconds": None,
            }

    return handle_db_operation(
        _operation,
        error_context="get_email_outbox_health()",
        default_return={
            "pending_count": 0,
            "processing_count": 0,
            "retry_count": 0,
            "dead_count": 0,
            "sent_count": 0,
            "terminal_count": 0,
            "oldest_pending_age_seconds": None,
        },
    )


def get_email_delivery_attempts(email_message_id: str) -> list[dict[str, Any]]:
    def _operation():
        with get_connection() as con:
            cur = con.cursor()
            cur.execute(
                """
                SELECT id,
                       email_message_id,
                       attempt_no,
                       provider,
                       status,
                       provider_message_id,
                       provider_event_id,
                       error_code,
                       error_message,
                       response_metadata,
                       created_at
                FROM email_delivery_attempts
                WHERE email_message_id = %s
                ORDER BY attempt_no ASC, created_at ASC
                """,
                [email_message_id],
            )
            return _fetch_all_dicts(cur)

    return handle_db_operation(
        _operation,
        error_context=f"get_email_delivery_attempts(email_message_id={email_message_id})",
        default_return=[],
    )


__all__ = [
    "GENERIC_PUBLIC_REPLAY_BODY",
    "add_user_email_and_enqueue",
    "anonymize_user_email_data",
    "apply_email_provider_event",
    "backfill_legacy_user_emails",
    "begin_email_idempotency",
    "claim_email_messages",
    "complete_email_idempotency",
    "consume_email_activation_token",
    "consume_password_reset_token",
    "enqueue_admin_password_reset_link",
    "enqueue_password_reset_link",
    "finalize_email_message",
    "get_email_delivery_attempts",
    "get_email_idempotency",
    "get_email_outbox_health",
    "is_recipient_suppressed",
    "list_admin_user_emails",
    "list_email_delivery_logs",
    "list_user_emails",
    "record_email_delivery_attempt",
    "remove_user_email",
    "resend_user_email_activation",
    "run_email_retention_purge",
    "set_primary_user_email",
]
