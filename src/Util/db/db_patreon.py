"""Database wrappers for Patreon entitlement stored procedures.

Trace: `.dev/sdd/changes/patreon-account-link/tasks.md` tasks `4.3`,
`8.2`, `8.3`, and `8.4`.

Security posture:
- This module only calls procedures that exist in
  `schemas/stored_procedures/16_patreon_entitlements.sql`.
- Wrapper argument order mirrors each stored procedure exactly. Do not reorder
  parameters for convenience; callers should use keywords.
- Raw Patreon IDs, emails, payloads, signatures, token material, fingerprints,
  hashes, and audit rows must not appear in error contexts or logs. Callers pass
  application-computed hashes/fingerprints and sanitized metadata only, except
  for the server-only outbound proof email recipient and encrypted ciphertext
  parameters required by the SQL contract.
- Patreon remains entitlement/link-only. These wrappers never issue local
  sessions, JWTs, refresh tokens, cookies, or API keys.
"""

from __future__ import annotations

import base64
import hashlib
import json
import uuid
from datetime import datetime
from typing import Any, Mapping, Sequence

from src.Util import auth_constants as constants
from src.Util.db_config import get_connection
from src.Util.db_error_wrapper import handle_db_operation
from src.Util.email.security import encrypt_render_payload
from src.Util.patreon.security import redact_patreon_mapping, sanitize_patreon_log_value


JsonParam = Mapping[str, Any] | Sequence[Any] | str | None

_JSON_RESULT_FIELDS = frozenset(
    {
        "metadata",
        "sanitized_metadata",
        "safe_metadata",
        "tier_hashes_json",
        "currently_entitled_tiers_json",
    }
)


def _json_param(value: JsonParam) -> str | None:
    """Return a compact JSON string for MySQL JSON params, preserving NULL."""

    if value is None or isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _bounded_raw_payload_retention_days(value: int | None) -> int:
    try:
        days = int(value if value is not None else constants.DEFAULT_PATREON_RAW_PAYLOAD_RETENTION_DAYS)
    except (TypeError, ValueError) as exc:
        raise ValueError("Patreon raw payload retention days must be an integer") from exc
    if days < 1 or days > constants.MAX_PATREON_RAW_PAYLOAD_RETENTION_DAYS:
        raise ValueError("Patreon raw payload retention cannot exceed 30 days")
    return days


def _validate_retention_window(*, value: int | None, default: int, maximum: int, label: str) -> int:
    try:
        amount = int(value if value is not None else default)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} retention must be an integer") from exc
    if amount < 0 or amount > maximum:
        raise ValueError(f"{label} retention exceeds the configured cap")
    return amount


def _payload_encryption_key(secret: str | bytes) -> bytes:
    material = secret if isinstance(secret, bytes) else str(secret or "").encode("utf-8")
    if not material.strip():
        raise ValueError("Patreon raw payload quarantine encryption key is required")
    return base64.urlsafe_b64encode(hashlib.sha256(material).digest())


def _raw_payload_bytes(value: bytes | bytearray | memoryview | str) -> bytes:
    if isinstance(value, bytes):
        payload = value
    elif isinstance(value, (bytearray, memoryview)):
        payload = bytes(value)
    elif isinstance(value, str):
        payload = value.encode("utf-8")
    else:
        raise TypeError("Patreon raw payload must be bytes or text")
    if not payload:
        raise ValueError("Patreon raw payload quarantine requires non-empty payload bytes")
    return payload


def _safe_quarantine_source(source: str) -> str:
    normalized = str(source or "").strip().lower()
    if normalized not in {"webhook", "api_pull", "manual"}:
        raise ValueError("Patreon raw payload quarantine source must be webhook, api_pull, or manual")
    return normalized


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
    for key in _JSON_RESULT_FIELDS:
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


def _callproc_rows_and_total(proc_name: str, args: list[Any], *, context: str) -> tuple[list[dict[str, Any]], int]:
    """Call a paginated proc that yields a page result set then a `total_count` scalar.

    Unlike the generic ``_fetch_all_dicts`` helper, this reads the page rows from the
    first result set WITHOUT draining, then advances exactly once to the trailing
    ``SELECT FOUND_ROWS() AS total_count`` set before draining the rest. This is required
    under pymysql, whose ``callproc`` exposes each procedure ``SELECT`` as a separate
    result set; draining first would discard the count. Falls back to the page length
    when the count set is absent.
    """

    def _operation() -> tuple[list[dict[str, Any]], int]:
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc(proc_name, args)
            if not _advance_to_result_set(cur):
                return [], 0
            description = cur.description
            rows = [row for row in (_row_to_dict(item, description) for item in cur.fetchall()) if row is not None]
            total = len(rows)
            if cur.nextset() and cur.description:
                scalar = _row_to_dict(cur.fetchone(), cur.description)
                if scalar and scalar.get("total_count") is not None:
                    total = int(scalar.get("total_count") or 0)
            _drain_remaining_result_sets(cur)
            return rows, total

    result = handle_db_operation(_operation, error_context=context, default_return=([], 0))
    return result if isinstance(result, tuple) else ([], 0)


# =============================================================================
# Proof lifecycle
# =============================================================================


def create_patreon_proof(
    *,
    proof_id: str,
    user_id: str,
    campaign_id: str | None,
    patreon_user_id_hash: bytes | None,
    patreon_user_id_fingerprint: str | None,
    member_id_hash: bytes | None,
    member_id_fingerprint: str | None,
    proof_email_hash: bytes,
    proof_email_masked: str,
    lookup_id: str,
    token_hash: bytes,
    token_fingerprint: str,
    expires_at: datetime,
    email_message_id: str,
    recipient_email: str,
    provider: str | None,
    provider_idempotency_key: str,
    render_payload_ciphertext: bytes,
    created_ip_hash: bytes | None,
    created_user_agent_hash: bytes | None,
    metadata: JsonParam = None,
) -> dict[str, Any] | None:
    """Call `sp_patreon_proof_create` with the SQL parameter order."""

    return _callproc_one(
        "sp_patreon_proof_create",
        [
            proof_id,
            user_id,
            campaign_id,
            patreon_user_id_hash,
            patreon_user_id_fingerprint,
            member_id_hash,
            member_id_fingerprint,
            proof_email_hash,
            proof_email_masked,
            lookup_id,
            token_hash,
            token_fingerprint,
            expires_at,
            email_message_id,
            recipient_email,
            provider,
            provider_idempotency_key,
            render_payload_ciphertext,
            created_ip_hash,
            created_user_agent_hash,
            _json_param(metadata),
        ],
        context=f"create_patreon_proof(user_id={user_id}, proof_id={proof_id})",
        commit=True,
    )


def consume_patreon_proof(
    *,
    lookup_id: str,
    token_hash: bytes,
    consumed_ip_hash: bytes | None,
    consumed_user_agent_hash: bytes | None,
    user_id: str | None = None,
) -> dict[str, Any] | None:
    """Call `sp_patreon_proof_consume` without logging proof token material.

    ``user_id`` binds the atomic consume attempt to the already-authenticated
    local user. The procedure returns only server-side HMAC/fingerprint context
    needed by the confirm route; callers must not serialize those values.
    """

    return _callproc_one(
        "sp_patreon_proof_consume",
        [lookup_id, token_hash, consumed_ip_hash, consumed_user_agent_hash, user_id],
        context="consume_patreon_proof(lookup_id=[REDACTED])",
        commit=True,
    )


# =============================================================================
# Link / unlink / relink / conflict checks
# =============================================================================


def check_patreon_link_conflict(*, user_id: str, provider_sub_hash: bytes) -> dict[str, Any] | None:
    """Call `sp_patreon_link_conflict_check`."""

    return _callproc_one(
        "sp_patreon_link_conflict_check",
        [user_id, provider_sub_hash],
        context=f"check_patreon_link_conflict(user_id={user_id})",
    )


def link_patreon_account(
    *,
    external_account_id: str,
    user_id: str,
    provider_sub_hash: bytes,
    provider_sub_fingerprint: str,
    provider_email_hash: bytes | None,
    provider_email_masked: str | None,
    linked_by: str | None,
    proof_id: str | None,
    campaign_id: str | None,
    membership_id: str | None,
    member_id_hash: bytes | None,
    member_id_fingerprint: str | None,
    metadata: JsonParam = None,
) -> dict[str, Any] | None:
    """Call `sp_patreon_link_account` with provider HMAC authority only."""

    return _callproc_one(
        "sp_patreon_link_account",
        [
            external_account_id,
            user_id,
            provider_sub_hash,
            provider_sub_fingerprint,
            provider_email_hash,
            provider_email_masked,
            linked_by,
            proof_id,
            campaign_id,
            membership_id,
            member_id_hash,
            member_id_fingerprint,
            _json_param(metadata),
        ],
        context=f"link_patreon_account(user_id={user_id}, external_account_id={external_account_id})",
        commit=True,
    )


def relink_patreon_account(
    *,
    user_id: str,
    unlinked_by: str | None,
    reason: str | None,
) -> dict[str, Any] | None:
    """Call `sp_patreon_relink_account`."""

    return _callproc_one(
        "sp_patreon_relink_account",
        [user_id, unlinked_by, reason],
        context=f"relink_patreon_account(user_id={user_id})",
        commit=True,
    )


def unlink_patreon_account(
    *,
    user_id: str,
    unlinked_by: str | None,
    reason: str | None,
    history_id: str | None,
) -> dict[str, Any] | None:
    """Call `sp_patreon_unlink_account`; local auth sessions are untouched by SQL."""

    return _callproc_one(
        "sp_patreon_unlink_account",
        [user_id, unlinked_by, reason, history_id],
        context=f"unlink_patreon_account(user_id={user_id})",
        commit=True,
    )


# =============================================================================
# Membership observations and entitlement snapshot/current/history writes
# =============================================================================


def observe_patreon_membership(
    *,
    membership_id: str,
    user_id: str,
    external_account_id: str,
    campaign_id: str,
    member_id_hash: bytes,
    member_id_fingerprint: str,
    patreon_user_id_hash: bytes,
    patreon_user_id_fingerprint: str,
    status: str | None,
    metadata: JsonParam = None,
) -> dict[str, Any] | None:
    """Call `sp_patreon_membership_observe`."""

    return _callproc_one(
        "sp_patreon_membership_observe",
        [
            membership_id,
            user_id,
            external_account_id,
            campaign_id,
            member_id_hash,
            member_id_fingerprint,
            patreon_user_id_hash,
            patreon_user_id_fingerprint,
            status,
            _json_param(metadata),
        ],
        context=f"observe_patreon_membership(user_id={user_id}, membership_id={membership_id})",
        commit=True,
    )


def upsert_patreon_entitlement_snapshot(
    *,
    snapshot_id: str,
    history_id: str | None,
    current_id: str | None,
    user_id: str,
    external_account_id: str | None,
    membership_id: str,
    observed_at: datetime | None,
    sync_source: str,
    patron_status_normalized: str | None,
    tier_hashes_json: JsonParam,
    last_charge_status_normalized: str | None,
    next_charge_at: datetime | None,
    payload_hash: bytes | None,
    is_complete: bool,
    requires_resync: bool,
    entitlement_status: str | None,
    link_status: str | None,
    plan_code: str | None,
    tier_code: str | None,
    tier_name: str | None,
    next_renewal_at: datetime | None,
    grace_period_until: datetime | None,
    stale_after: datetime | None,
    reason: str | None,
    safe_metadata: JsonParam = None,
) -> dict[str, Any] | None:
    """Call `sp_patreon_entitlement_snapshot_upsert`.

    The SQL procedure appends snapshot/history evidence and upserts the current
    normalized entitlement in one transaction.
    """

    return _callproc_one(
        "sp_patreon_entitlement_snapshot_upsert",
        [
            snapshot_id,
            history_id,
            current_id,
            user_id,
            external_account_id,
            membership_id,
            observed_at,
            sync_source,
            patron_status_normalized,
            _json_param(tier_hashes_json),
            last_charge_status_normalized,
            next_charge_at,
            payload_hash,
            is_complete,
            requires_resync,
            entitlement_status,
            link_status,
            plan_code,
            tier_code,
            tier_name,
            next_renewal_at,
            grace_period_until,
            stale_after,
            reason,
            _json_param(safe_metadata),
        ],
        context=f"upsert_patreon_entitlement_snapshot(user_id={user_id}, snapshot_id={snapshot_id})",
        commit=True,
    )


def get_entitlement_by_user_hash(user_hash: str) -> dict[str, Any] | None:
    """Call `sp_patreon_get_entitlement_by_user_hash` for the S2S read path."""

    return _callproc_one(
        "sp_patreon_get_entitlement_by_user_hash",
        [user_hash],
        context="get_entitlement_by_user_hash(user_hash=[REDACTED])",
    )


def get_patreon_entitlement_by_user_hash(user_hash: str) -> dict[str, Any] | None:
    """Backward-readable alias over `sp_patreon_get_entitlement_by_user_hash`."""

    return get_entitlement_by_user_hash(user_hash)


def get_patreon_link_by_provider_sub_hash(*, provider_sub_hash: bytes) -> dict[str, Any] | None:
    """Resolve an active Patreon external account by provider subject hash.

    This wraps the existing provider-generic `sp_get_user_by_external_account`
    procedure.  Patreon callers must use the returned user only as link and
    entitlement authority, never as a login/session authority.
    """

    return _callproc_one(
        "sp_get_user_by_external_account",
        ["patreon", provider_sub_hash],
        context="get_patreon_link_by_provider_sub_hash(provider=patreon)",
    )


def resolve_patreon_link_by_provider_hash(*, provider_sub_hash: bytes) -> dict[str, Any] | None:
    """Alias for webhook/sync callers resolving linked Patreon authority."""

    return get_patreon_link_by_provider_sub_hash(provider_sub_hash=provider_sub_hash)


# =============================================================================
# Webhook delivery ledger
# =============================================================================


def record_patreon_webhook_delivery(
    *,
    delivery_id: str,
    delivery_hash: bytes,
    event_type: str,
    member_id_hash: bytes | None,
    campaign_id_hash: bytes | None,
    raw_body_sha256: bytes,
    signature_valid: bool,
    status: str | None,
    sanitized_metadata: JsonParam = None,
) -> dict[str, Any] | None:
    """Call `sp_patreon_webhook_delivery_record` for local idempotency."""

    return _callproc_one(
        "sp_patreon_webhook_delivery_record",
        [
            delivery_id,
            delivery_hash,
            event_type,
            member_id_hash,
            campaign_id_hash,
            raw_body_sha256,
            signature_valid,
            status,
            _json_param(sanitized_metadata),
        ],
        context=f"record_patreon_webhook_delivery(event_type={event_type}, status={status})",
        commit=True,
    )


def record_webhook_delivery(**kwargs: Any) -> dict[str, Any] | None:
    """Alias over `sp_patreon_webhook_delivery_record` for route seams."""

    return record_patreon_webhook_delivery(**kwargs)


# =============================================================================
# Sync jobs
# =============================================================================


def enqueue_patreon_sync_job(
    *,
    job_id: str,
    job_type: str,
    campaign_id: str | None,
    member_id_hash: bytes | None,
    user_id: str | None,
    dedupe_key_hash: bytes,
    priority: int | None,
    not_before: datetime | None,
    source: str,
    sanitized_metadata: JsonParam = None,
) -> dict[str, Any] | None:
    """Call `sp_patreon_sync_job_enqueue`."""

    return _callproc_one(
        "sp_patreon_sync_job_enqueue",
        [
            job_id,
            job_type,
            campaign_id,
            member_id_hash,
            user_id,
            dedupe_key_hash,
            priority,
            not_before,
            source,
            _json_param(sanitized_metadata),
        ],
        context=f"enqueue_patreon_sync_job(job_id={job_id}, job_type={job_type}, source={source})",
        commit=True,
    )


def enqueue_sync_job(**kwargs: Any) -> dict[str, Any] | None:
    """Alias over `sp_patreon_sync_job_enqueue` for webhook/sync seams."""

    return enqueue_patreon_sync_job(**kwargs)


def claim_patreon_sync_jobs(*, worker_id: str, limit: int, lease_seconds: int) -> list[dict[str, Any]]:
    """Call `sp_patreon_sync_job_claim`."""

    return _callproc_all(
        "sp_patreon_sync_job_claim",
        [worker_id, limit, lease_seconds],
        context=f"claim_patreon_sync_jobs(worker_id={worker_id}, limit={limit})",
        commit=True,
    )


def claim_sync_jobs(**kwargs: Any) -> list[dict[str, Any]]:
    """Alias over `sp_patreon_sync_job_claim` for worker seams."""

    return claim_patreon_sync_jobs(**kwargs)


def complete_patreon_sync_job(
    *,
    job_id: str,
    status: str,
    retry_after_seconds: int | None,
    last_error_redacted: str | None,
) -> dict[str, Any] | None:
    """Call `sp_patreon_sync_job_complete`.

    Fail/retry outcomes are represented by the SQL `p_status` value; there is no
    separate fail procedure in Phase 2 SQL.
    """

    return _callproc_one(
        "sp_patreon_sync_job_complete",
        [job_id, status, retry_after_seconds, last_error_redacted],
        context=f"complete_patreon_sync_job(job_id={job_id}, status={status})",
        commit=True,
    )


def complete_sync_job(**kwargs: Any) -> dict[str, Any] | None:
    """Alias over `sp_patreon_sync_job_complete` for worker seams."""

    return complete_patreon_sync_job(**kwargs)


# =============================================================================
# ROOT admin read/list surface (dashboard management)
# =============================================================================
#
# These wrappers back the ROOT-only `/admin/patreon/*` list endpoints. They call
# paginated procedures that return only normalized, non-secret columns; callers
# still pass results through the route-level redaction allow-lists as defense in
# depth. Context strings never include raw identifiers.


def list_patreon_entitlements_admin(
    *,
    status: str | None,
    plan_code: str | None,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    """List current Patreon entitlements (paginated) for the ROOT dashboard."""

    return _callproc_rows_and_total(
        "sp_patreon_admin_list_entitlements",
        [status or None, plan_code or None, limit, offset],
        context=f"list_patreon_entitlements_admin(status={status or ''}, limit={limit}, offset={offset})",
    )


def list_patreon_tier_map_admin(
    *,
    active: bool | None,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    """List configured tier-map entries (paginated) for the ROOT dashboard."""

    return _callproc_rows_and_total(
        "sp_patreon_admin_list_tier_map",
        [None if active is None else int(active), limit, offset],
        context=f"list_patreon_tier_map_admin(active={active}, limit={limit}, offset={offset})",
    )


def list_patreon_sync_jobs_admin(
    *,
    status: str | None,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    """List sync jobs (paginated) for the ROOT dashboard."""

    return _callproc_rows_and_total(
        "sp_patreon_admin_list_sync_jobs",
        [status or None, limit, offset],
        context=f"list_patreon_sync_jobs_admin(status={status or ''}, limit={limit}, offset={offset})",
    )


def list_patreon_webhooks_admin(
    *,
    status: str | None,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    """List webhook deliveries (paginated) for the ROOT dashboard."""

    return _callproc_rows_and_total(
        "sp_patreon_admin_list_webhooks",
        [status or None, limit, offset],
        context=f"list_patreon_webhooks_admin(status={status or ''}, limit={limit}, offset={offset})",
    )


# =============================================================================
# Provider token state and raw-payload quarantine
# =============================================================================


def upsert_patreon_provider_token_state(
    *,
    token_state_id: str,
    access_token_ciphertext: bytes | None,
    refresh_token_ciphertext: bytes | None,
    token_fingerprint: str | None,
    encryption_key_id: str | None,
    expires_at: datetime | None,
    status: str | None,
    last_error_redacted: str | None,
    auto_refresh_enabled: bool = False,
) -> dict[str, Any] | None:
    """Call `sp_patreon_provider_token_state_upsert` with encrypted token blobs only.

    The provider-token state table is global/server-only and must be used only
    when creator-token auto-refresh is explicitly enabled.  This wrapper refuses
    silent raw-token persistence by accepting ciphertext parameters only and by
    returning a disabled/no-op result when auto-refresh is off.
    """

    if not auto_refresh_enabled:
        return {"token_state_status": "disabled", "persisted": False}

    safe_key_id = str(encryption_key_id or "").strip()
    if not safe_key_id:
        raise ValueError("Patreon provider-token encryption key id is required when auto-refresh is enabled")

    safe_status = str(status or "disabled").strip().lower()
    if safe_status not in {"disabled", "active", "refresh_failed", "revoked", "expired"}:
        safe_status = "refresh_failed"
    safe_error = sanitize_patreon_log_value(last_error_redacted)[:500] if last_error_redacted else None

    return _callproc_one(
        "sp_patreon_provider_token_state_upsert",
        [
            token_state_id,
            access_token_ciphertext,
            refresh_token_ciphertext,
            token_fingerprint,
            safe_key_id,
            expires_at,
            safe_status,
            safe_error,
        ],
        context=f"upsert_patreon_provider_token_state(token_state_id={token_state_id}, status={status})",
        commit=True,
    )


def upsert_provider_token_state(**kwargs: Any) -> dict[str, Any] | None:
    """Alias for worker/client seams; never accepts raw token values."""

    return upsert_patreon_provider_token_state(**kwargs)


def get_patreon_provider_token_state() -> dict[str, Any] | None:
    """Call `sp_patreon_provider_token_state_get`.

    The SQL procedure intentionally returns non-secret token health metadata only.
    """

    return _callproc_one(
        "sp_patreon_provider_token_state_get",
        [],
        context="get_patreon_provider_token_state()",
    )


def get_patreon_creator_token_health() -> dict[str, Any]:
    """Return non-secret creator-token health metadata.

    The underlying procedure may return a server-only token fingerprint.  Health
    callers do not receive it; task 8.5 owns broader metrics exposure later.
    """

    row = get_patreon_provider_token_state() or {}
    if not row:
        return {"status": "disabled", "configured": False}
    return {
        "status": row.get("status") or "unknown",
        "configured": True,
        "expires_at": row.get("expires_at"),
        "refreshed_at": row.get("refreshed_at"),
        "rotated_at": row.get("rotated_at"),
        "degraded": row.get("status") in {"refresh_failed", "revoked", "expired"},
    }


def record_patreon_creator_token_degraded(
    *,
    auto_refresh_enabled: bool,
    encryption_key_id: str | None = None,
    status: str = "refresh_failed",
    last_error_redacted: str | None = None,
) -> dict[str, Any] | None:
    """Persist a non-secret degraded token state only when auto-refresh is on."""

    return upsert_patreon_provider_token_state(
        token_state_id="patreon-creator-token-state",
        access_token_ciphertext=None,
        refresh_token_ciphertext=None,
        token_fingerprint=None,
        encryption_key_id=encryption_key_id,
        expires_at=None,
        status=status,
        last_error_redacted=last_error_redacted,
        auto_refresh_enabled=auto_refresh_enabled,
    )


def insert_patreon_raw_payload_quarantine(
    *,
    quarantine_id: str,
    payload_hash: bytes,
    source: str,
    payload_ciphertext: bytes,
    encryption_key_id: str,
    capture_reason: str,
    retention_days: int,
    created_by: str | None,
    sanitized_metadata: JsonParam = None,
) -> dict[str, Any] | None:
    """Call `sp_patreon_raw_payload_quarantine_insert` with encrypted payload only.

    This is the low-level server-only insert seam.  Callers must pass encrypted
    ciphertext, never raw provider payload bytes.  The safer high-level helper
    `quarantine_patreon_raw_payload()` applies the disabled-by-default gate and
    encryption before reaching this function.
    """

    safe_retention_days = _bounded_raw_payload_retention_days(retention_days)
    safe_source = _safe_quarantine_source(source)
    if not isinstance(payload_hash, bytes) or len(payload_hash) != 32:
        raise ValueError("Patreon raw payload hash must be 32 bytes")
    if not isinstance(payload_ciphertext, (bytes, bytearray, memoryview)) or not bytes(payload_ciphertext):
        raise ValueError("Patreon raw payload quarantine requires encrypted ciphertext")
    safe_key_id = str(encryption_key_id or "").strip()
    if not safe_key_id:
        raise ValueError("Patreon raw payload quarantine encryption key id is required")
    safe_reason = sanitize_patreon_log_value(capture_reason or "diagnostic_capture")[:128]

    return _callproc_one(
        "sp_patreon_raw_payload_quarantine_insert",
        [
            quarantine_id,
            payload_hash,
            safe_source,
            bytes(payload_ciphertext),
            safe_key_id,
            safe_reason,
            safe_retention_days,
            created_by,
            _json_param(redact_patreon_mapping(sanitized_metadata)),
        ],
        context=f"insert_patreon_raw_payload_quarantine(source={safe_source}, retention_days={safe_retention_days})",
        commit=True,
    )


def quarantine_patreon_raw_payload(
    *,
    raw_payload: bytes | bytearray | memoryview | str,
    source: str,
    capture_enabled: bool = False,
    encryption_key: str | bytes | None = None,
    encryption_key_id: str | None = None,
    retention_days: int | None = None,
    capture_reason: str = "diagnostic_capture",
    created_by: str | None = None,
    sanitized_metadata: JsonParam = None,
) -> dict[str, Any]:
    """Encrypt and quarantine a raw Patreon payload only when explicitly enabled.

    Raw-payload quarantine is disabled by default and has no read/browser/S2S
    surface.  When enabled, only ciphertext and a non-reversible SHA-256 digest
    are persisted, and retention is capped at 30 days.
    """

    if not capture_enabled:
        return {"quarantine_status": "disabled", "persisted": False}

    payload_bytes = _raw_payload_bytes(raw_payload)
    safe_retention_days = _bounded_raw_payload_retention_days(retention_days)
    safe_source = _safe_quarantine_source(source)
    safe_key_id = str(encryption_key_id or "").strip()
    if not safe_key_id:
        return {"quarantine_status": "not_ready", "persisted": False}
    if not encryption_key:
        return {"quarantine_status": "not_ready", "persisted": False}

    payload_ciphertext = encrypt_render_payload(
        {
            "provider": constants.PATREON_PROVIDER_NAME,
            "source": safe_source,
            "payload_b64": base64.b64encode(payload_bytes).decode("ascii"),
        },
        key=_payload_encryption_key(encryption_key),
    )
    result = insert_patreon_raw_payload_quarantine(
        quarantine_id=f"prpq-{uuid.uuid4().hex}",
        payload_hash=hashlib.sha256(payload_bytes).digest(),
        source=safe_source,
        payload_ciphertext=payload_ciphertext,
        encryption_key_id=safe_key_id,
        capture_reason=capture_reason,
        retention_days=safe_retention_days,
        created_by=created_by,
        sanitized_metadata=sanitized_metadata,
    ) or {}
    safe_result = {key: value for key, value in result.items() if key in {"quarantine_id", "quarantine_status"}}
    return {"persisted": bool(result), **safe_result}


def capture_patreon_raw_payload_quarantine(**kwargs: Any) -> dict[str, Any]:
    """Alias for worker/test seams; returns only safe status metadata."""

    return quarantine_patreon_raw_payload(**kwargs)


# =============================================================================
# Retention purge
# =============================================================================


def run_patreon_retention_purge(
    *,
    proof_retention_after_expiry_hours: int | None = None,
    webhook_delivery_retention_days: int | None = None,
    raw_payload_retention_days: int | None = None,
) -> dict[str, Any] | None:
    """Call `sp_patreon_retention_purge`.

    SQL purges only bounded proof/webhook/quarantine artifacts. Link, snapshot,
    entitlement, and unlink history remain preserved indefinitely.
    """

    _validate_retention_window(
        value=proof_retention_after_expiry_hours,
        default=constants.DEFAULT_PATREON_PROOF_RETENTION_AFTER_EXPIRY_HOURS,
        maximum=constants.MAX_PATREON_PROOF_RETENTION_AFTER_EXPIRY_HOURS,
        label="Patreon proof",
    )
    _validate_retention_window(
        value=webhook_delivery_retention_days,
        default=constants.DEFAULT_PATREON_WEBHOOK_DELIVERY_RETENTION_DAYS,
        maximum=constants.MAX_PATREON_WEBHOOK_DELIVERY_RETENTION_DAYS,
        label="Patreon webhook delivery",
    )
    _validate_retention_window(
        value=raw_payload_retention_days,
        default=constants.DEFAULT_PATREON_RAW_PAYLOAD_RETENTION_DAYS,
        maximum=constants.MAX_PATREON_RAW_PAYLOAD_RETENTION_DAYS,
        label="Patreon raw payload",
    )

    return _callproc_one(
        "sp_patreon_retention_purge",
        [],
        context="run_patreon_retention_purge()",
        commit=True,
    )


__all__ = [
    "check_patreon_link_conflict",
    "claim_patreon_sync_jobs",
    "claim_sync_jobs",
    "capture_patreon_raw_payload_quarantine",
    "complete_patreon_sync_job",
    "complete_sync_job",
    "consume_patreon_proof",
    "create_patreon_proof",
    "enqueue_patreon_sync_job",
    "enqueue_sync_job",
    "get_entitlement_by_user_hash",
    "get_patreon_link_by_provider_sub_hash",
    "get_patreon_entitlement_by_user_hash",
    "get_patreon_creator_token_health",
    "get_patreon_provider_token_state",
    "insert_patreon_raw_payload_quarantine",
    "link_patreon_account",
    "list_patreon_entitlements_admin",
    "list_patreon_sync_jobs_admin",
    "list_patreon_tier_map_admin",
    "list_patreon_webhooks_admin",
    "observe_patreon_membership",
    "record_patreon_webhook_delivery",
    "record_webhook_delivery",
    "record_patreon_creator_token_degraded",
    "relink_patreon_account",
    "resolve_patreon_link_by_provider_hash",
    "quarantine_patreon_raw_payload",
    "run_patreon_retention_purge",
    "unlink_patreon_account",
    "upsert_patreon_entitlement_snapshot",
    "upsert_patreon_provider_token_state",
    "upsert_provider_token_state",
]
