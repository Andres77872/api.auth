"""Database wrappers for provider-agnostic billing stored procedures.

Trace: `.dev/sdd/changes/provider-agnostic-billing-stripe/tasks.md` tasks
`3.5` and `3.6`.

Security posture:
- This module only calls procedures from
  `schemas/stored_procedures/17_billing_provider_facts.sql`.
- Wrapper argument order mirrors SQL exactly. Callers should use keyword
  arguments; do not reorder parameters for convenience.
- Raw provider operational identifiers, signatures, payloads, idempotency keys,
  card/payment details, and provider HMAC/fingerprint values must not appear in
  error contexts or logs.
- Operational ref access returns encrypted ciphertext/key metadata only and is
  intended for authorized server-side provider code, never consumer DTOs.
- Billing remains provider-fact-only. These wrappers never issue local sessions,
  JWTs, cookies, refresh tokens, or API keys.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Mapping, Sequence

from src.Util.db_config import get_connection
from src.Util.db_error_wrapper import handle_db_operation


JsonParam = Mapping[str, Any] | Sequence[Any] | str | None

DEFAULT_BILLING_WEBHOOK_DELIVERY_RETENTION_DAYS = 90
MAX_BILLING_WEBHOOK_DELIVERY_RETENTION_DAYS = 90
DEFAULT_BILLING_RAW_PAYLOAD_RETENTION_DAYS = 30
MAX_BILLING_RAW_PAYLOAD_RETENTION_DAYS = 30

_JSON_RESULT_FIELDS = frozenset(
    {
        "capability_metadata",
        "safe_metadata",
        "sanitized_metadata",
        "safe_response_json",
        "features",
        "metadata",
    }
)


def _json_param(value: JsonParam) -> str | None:
    """Return compact JSON for MySQL JSON params, preserving NULL."""

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
    """Call one stored procedure and return its first result row."""

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
    """Call one stored procedure and return all rows from its first result set."""

    def _operation():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc(proc_name, args)
            result = _fetch_all_dicts(cur)
            if commit:
                con.commit()
            return result

    return handle_db_operation(_operation, error_context=context, default_return=[])


def _validate_retention_window(*, value: int | None, default: int, maximum: int, label: str) -> int:
    try:
        amount = int(value if value is not None else default)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} retention must be an integer") from exc
    if amount < 0 or amount > maximum:
        raise ValueError(f"{label} retention exceeds the configured cap")
    return amount


# =============================================================================
# Scope resolution and free-default reads
# =============================================================================


def resolve_user_project(*, user_hash: str, project_hash: str) -> dict[str, Any] | None:
    """Call `sp_billing_resolve_user_project` without exposing billing state."""

    return _callproc_one(
        "sp_billing_resolve_user_project",
        [user_hash, project_hash],
        context="resolve_user_project(user_hash=[REDACTED], project_hash=[REDACTED])",
    )


def get_current_by_user_project(*, user_hash: str, project_hash: str, provider: str = "stripe") -> dict[str, Any] | None:
    """Call `sp_billing_get_current_by_user_project` for the safe S2S read path."""

    return _callproc_one(
        "sp_billing_get_current_by_user_project",
        [user_hash, project_hash, provider],
        context="get_current_by_user_project(user_hash=[REDACTED], project_hash=[REDACTED])",
    )


def get_session_plan(*, user_id: str, project_id: str, provider: str = "stripe") -> dict[str, Any] | None:
    """Call `sp_billing_get_session_plan` for the identity/session plan projection.

    Hot-path, subscription-only read keyed by internal ids (access already verified by
    validate_session). Returns a narrow safe row (no operational refs); resolves the
    project to its billing group and reads the group-scoped entitlement. A DB failure
    returns None so the auth path degrades to plan state "none" without failing.
    """

    return _callproc_one(
        "sp_billing_get_session_plan",
        [user_id, project_id, provider],
        context=f"get_session_plan(user_id={user_id}, project_id={project_id}, provider={provider})",
    )


def resolve_user_billing_group(*, user_hash: str, project_hash: str) -> dict[str, Any] | None:
    """Call `sp_billing_resolve_user_billing_group` to map a (user, project) to its group."""

    return _callproc_one(
        "sp_billing_resolve_user_billing_group",
        [user_hash, project_hash],
        context="resolve_user_billing_group(user_hash=[REDACTED], project_hash=[REDACTED])",
    )


# =============================================================================
# Checkout idempotency
# =============================================================================


def begin_checkout_intent(
    *,
    intent_id: str,
    user_id: str,
    project_id: str,
    billing_group_id: str,
    customer_id: str | None,
    provider: str,
    checkout_ref: str,
    subscription_ref: str | None,
    purchase_ref: str | None,
    intent_type: str,
    provider_price_ref_type: str,
    provider_price_ref_hmac: bytes,
    provider_price_ref_fingerprint: str,
    idempotency_key_hmac: bytes,
    canonical_request_hash: bytes,
    plan_code: str | None,
    tier_code: str | None,
    tier_name: str | None,
    credit_product_code: str | None,
    quantity: int | None,
    safe_metadata: JsonParam = None,
) -> dict[str, Any] | None:
    """Call `sp_billing_checkout_intent_begin` with exact SQL argument order."""

    return _callproc_one(
        "sp_billing_checkout_intent_begin",
        [
            intent_id,
            user_id,
            project_id,
            billing_group_id,
            customer_id,
            provider,
            checkout_ref,
            subscription_ref,
            purchase_ref,
            intent_type,
            provider_price_ref_type,
            provider_price_ref_hmac,
            provider_price_ref_fingerprint,
            idempotency_key_hmac,
            canonical_request_hash,
            plan_code,
            tier_code,
            tier_name,
            credit_product_code,
            quantity,
            _json_param(safe_metadata),
        ],
        context=f"begin_checkout_intent(user_id={user_id}, billing_group_id={billing_group_id}, checkout_ref={checkout_ref})",
        commit=True,
    )


def complete_checkout_intent(
    *,
    intent_id: str,
    status: str,
    provider_checkout_session_id_ciphertext: bytes | None,
    provider_checkout_session_id_hmac: bytes | None,
    provider_checkout_session_id_fingerprint: str | None,
    provider_ref_key_id: str | None,
    hosted_session_fingerprint: str | None,
    safe_response_json: JsonParam,
    completed_at: datetime | None,
) -> dict[str, Any] | None:
    """Call `sp_billing_checkout_intent_complete` with encrypted provider evidence."""

    return _callproc_one(
        "sp_billing_checkout_intent_complete",
        [
            intent_id,
            status,
            provider_checkout_session_id_ciphertext,
            provider_checkout_session_id_hmac,
            provider_checkout_session_id_fingerprint,
            provider_ref_key_id,
            hosted_session_fingerprint,
            _json_param(safe_response_json),
            completed_at,
        ],
        context=f"complete_checkout_intent(intent_id={intent_id}, status={status})",
        commit=True,
    )


# =============================================================================
# Customers and server-only operational refs
# =============================================================================


def upsert_customer(
    *,
    customer_id: str,
    user_id: str,
    billing_group_id: str,
    provider: str,
    customer_ref: str,
    provider_customer_id_ciphertext: bytes,
    provider_customer_id_hmac: bytes,
    provider_customer_id_fingerprint: str,
    provider_ref_key_id: str,
    status: str | None,
    safe_metadata: JsonParam = None,
) -> dict[str, Any] | None:
    """Call `sp_billing_customer_upsert` with encrypted customer ref only."""

    return _callproc_one(
        "sp_billing_customer_upsert",
        [
            customer_id,
            user_id,
            billing_group_id,
            provider,
            customer_ref,
            provider_customer_id_ciphertext,
            provider_customer_id_hmac,
            provider_customer_id_fingerprint,
            provider_ref_key_id,
            status,
            _json_param(safe_metadata),
        ],
        context=f"upsert_customer(user_id={user_id}, billing_group_id={billing_group_id}, customer_ref={customer_ref})",
        commit=True,
    )


def upsert_billing_customer(**kwargs: Any) -> dict[str, Any] | None:
    """Readable alias over `sp_billing_customer_upsert`."""

    return upsert_customer(**kwargs)


def get_customer_operational_ref(*, user_id: str, billing_group_id: str, provider: str) -> dict[str, Any] | None:
    """Call `sp_billing_get_customer_operational_ref` for server-only provider code.

    The returned ciphertext/key metadata must not be serialized into S2S responses,
    browser responses, audit details, activity details, logs, or metrics.
    """

    return _callproc_one(
        "sp_billing_get_customer_operational_ref",
        [user_id, billing_group_id, provider],
        context=f"get_customer_operational_ref(user_id={user_id}, billing_group_id={billing_group_id}, provider={provider})",
    )


# =============================================================================
# Webhook delivery ledger
# =============================================================================


def record_webhook_delivery(
    *,
    delivery_id: str,
    provider: str,
    billing_group_id: str,
    provider_event_id_hmac: bytes,
    provider_event_id_fingerprint: str,
    event_type: str,
    raw_body_sha256: bytes,
    signature_valid: bool,
    status: str | None,
    sanitized_metadata: JsonParam = None,
) -> dict[str, Any] | None:
    """Call `sp_billing_webhook_delivery_record` for per-group provider idempotency."""

    return _callproc_one(
        "sp_billing_webhook_delivery_record",
        [
            delivery_id,
            provider,
            billing_group_id,
            provider_event_id_hmac,
            provider_event_id_fingerprint,
            event_type,
            raw_body_sha256,
            signature_valid,
            status,
            _json_param(sanitized_metadata),
        ],
        context=f"record_webhook_delivery(provider={provider}, billing_group_id={billing_group_id}, event_type={event_type})",
        commit=True,
    )


def record_billing_webhook_delivery(**kwargs: Any) -> dict[str, Any] | None:
    """Alias over `sp_billing_webhook_delivery_record` for route seams."""

    return record_webhook_delivery(**kwargs)


# =============================================================================
# Subscription and purchase observations
# =============================================================================


def observe_subscription(
    *,
    snapshot_id: str,
    history_id: str | None,
    current_id: str | None,
    subscription_id: str,
    customer_id: str,
    user_id: str,
    billing_group_id: str,
    provider: str,
    subscription_ref: str,
    provider_subscription_id_ciphertext: bytes | None,
    provider_subscription_id_hmac: bytes | None,
    provider_subscription_id_fingerprint: str | None,
    provider_ref_key_id: str | None,
    observed_at: datetime | None,
    sync_source: str,
    normalized_status: str,
    plan_code: str | None,
    tier_code: str | None,
    tier_name: str | None,
    cancel_at_period_end: bool,
    current_period_end: datetime | None,
    trial_end: datetime | None,
    payload_hash: bytes | None,
    is_complete: bool,
    requires_resync: bool,
    stale_after: datetime | None,
    reason: str | None,
    safe_metadata: JsonParam = None,
) -> dict[str, Any] | None:
    """Call `sp_billing_subscription_observe` for current/history writes."""

    return _callproc_one(
        "sp_billing_subscription_observe",
        [
            snapshot_id,
            history_id,
            current_id,
            subscription_id,
            customer_id,
            user_id,
            billing_group_id,
            provider,
            subscription_ref,
            provider_subscription_id_ciphertext,
            provider_subscription_id_hmac,
            provider_subscription_id_fingerprint,
            provider_ref_key_id,
            observed_at,
            sync_source,
            normalized_status,
            plan_code,
            tier_code,
            tier_name,
            cancel_at_period_end,
            current_period_end,
            trial_end,
            payload_hash,
            is_complete,
            requires_resync,
            stale_after,
            reason,
            _json_param(safe_metadata),
        ],
        context=f"observe_subscription(user_id={user_id}, billing_group_id={billing_group_id}, subscription_ref={subscription_ref})",
        commit=True,
    )


def record_purchase_event(
    *,
    purchase_id: str,
    history_id: str | None,
    user_id: str,
    project_id: str,
    billing_group_id: str,
    customer_id: str | None,
    provider: str,
    purchase_ref: str,
    checkout_ref: str | None,
    status: str,
    credit_product_code: str | None,
    quantity: int | None,
    provider_payment_intent_id_ciphertext: bytes | None,
    provider_payment_intent_id_hmac: bytes | None,
    provider_payment_intent_id_fingerprint: str | None,
    provider_charge_id_ciphertext: bytes | None,
    provider_charge_id_hmac: bytes | None,
    provider_charge_id_fingerprint: str | None,
    provider_ref_key_id: str | None,
    observed_at: datetime | None,
    sync_source: str,
    paid_at: datetime | None,
    refunded_at: datetime | None,
    disputed_at: datetime | None,
    stale_after: datetime | None,
    reason: str | None,
    safe_metadata: JsonParam = None,
) -> dict[str, Any] | None:
    """Call `sp_billing_purchase_event_record` without product-owned mutations."""

    return _callproc_one(
        "sp_billing_purchase_event_record",
        [
            purchase_id,
            history_id,
            user_id,
            project_id,
            billing_group_id,
            customer_id,
            provider,
            purchase_ref,
            checkout_ref,
            status,
            credit_product_code,
            quantity,
            provider_payment_intent_id_ciphertext,
            provider_payment_intent_id_hmac,
            provider_payment_intent_id_fingerprint,
            provider_charge_id_ciphertext,
            provider_charge_id_hmac,
            provider_charge_id_fingerprint,
            provider_ref_key_id,
            observed_at,
            sync_source,
            paid_at,
            refunded_at,
            disputed_at,
            stale_after,
            reason,
            _json_param(safe_metadata),
        ],
        context=f"record_purchase_event(user_id={user_id}, project_id={project_id}, purchase_ref={purchase_ref})",
        commit=True,
    )


# =============================================================================
# Sync jobs
# =============================================================================


def enqueue_sync_job(
    *,
    job_id: str,
    provider: str,
    job_type: str,
    user_id: str | None,
    project_id: str | None,
    billing_group_id: str | None = None,
    customer_id: str | None = None,
    subscription_id: str | None = None,
    purchase_id: str | None = None,
    dedupe_key_hmac: bytes,
    priority: int | None,
    not_before: datetime | None,
    source: str,
    sanitized_metadata: JsonParam = None,
) -> dict[str, Any] | None:
    """Call `sp_billing_sync_job_enqueue`."""

    return _callproc_one(
        "sp_billing_sync_job_enqueue",
        [
            job_id,
            provider,
            job_type,
            user_id,
            project_id,
            billing_group_id,
            customer_id,
            subscription_id,
            purchase_id,
            dedupe_key_hmac,
            priority,
            not_before,
            source,
            _json_param(sanitized_metadata),
        ],
        context=f"enqueue_sync_job(provider={provider}, job_type={job_type}, job_id={job_id})",
        commit=True,
    )


def claim_sync_jobs(*, worker_id: str, limit: int, lease_seconds: int) -> list[dict[str, Any]]:
    """Call `sp_billing_sync_job_claim`."""

    return _callproc_all(
        "sp_billing_sync_job_claim",
        [worker_id, limit, lease_seconds],
        context=f"claim_sync_jobs(worker_id={worker_id}, limit={limit})",
        commit=True,
    )


def complete_sync_job(
    *,
    job_id: str,
    status: str,
    retry_after_seconds: int | None,
    last_error_redacted: str | None,
) -> dict[str, Any] | None:
    """Call `sp_billing_sync_job_complete`."""

    return _callproc_one(
        "sp_billing_sync_job_complete",
        [job_id, status, retry_after_seconds, last_error_redacted],
        context=f"complete_sync_job(job_id={job_id}, status={status})",
        commit=True,
    )


# =============================================================================
# Retention
# =============================================================================


def run_retention_purge(
    *,
    webhook_delivery_retention_days: int | None = None,
    raw_payload_retention_days: int | None = None,
) -> dict[str, Any] | None:
    """Call `sp_billing_retention_purge` after validating configured caps.

    SQL purges only bounded webhook delivery rows and encrypted raw-payload
    quarantine ciphertext. Normalized entitlement and purchase histories remain
    preserved indefinitely.
    """

    _validate_retention_window(
        value=webhook_delivery_retention_days,
        default=DEFAULT_BILLING_WEBHOOK_DELIVERY_RETENTION_DAYS,
        maximum=MAX_BILLING_WEBHOOK_DELIVERY_RETENTION_DAYS,
        label="Billing webhook delivery",
    )
    _validate_retention_window(
        value=raw_payload_retention_days,
        default=DEFAULT_BILLING_RAW_PAYLOAD_RETENTION_DAYS,
        maximum=MAX_BILLING_RAW_PAYLOAD_RETENTION_DAYS,
        label="Billing raw payload",
    )

    return _callproc_one(
        "sp_billing_retention_purge",
        [],
        context="run_retention_purge()",
        commit=True,
    )


def run_billing_retention_purge(**kwargs: Any) -> dict[str, Any] | None:
    """Readable alias over `sp_billing_retention_purge`."""

    return run_retention_purge(**kwargs)


def billing_provider_exists(*, provider: str) -> bool:
    """Return whether the provider registry contains the normalized provider code."""

    provider_code = str(provider or "").strip().lower()
    if not provider_code:
        return False

    def _operation() -> bool:
        with get_connection() as con:
            cur = con.cursor()
            cur.execute(
                "SELECT 1 FROM billing_providers WHERE provider_code = %s LIMIT 1",
                (provider_code,),
            )
            return cur.fetchone() is not None

    return bool(handle_db_operation(_operation, error_context=f"billing_provider_exists(provider={provider_code})"))


# =============================================================================
# Billing groups (CRUD + per-account encrypted credentials)
# =============================================================================


def _callproc_rows_and_total(proc_name: str, args: list[Any], *, context: str) -> tuple[list[dict[str, Any]], int]:
    """Call a paginated proc returning a rows result set then a total_count scalar."""

    def _operation() -> tuple[list[dict[str, Any]], int]:
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc(proc_name, args)
            rows = _fetch_all_dicts(cur)
            total = 0
            if cur.description or cur.nextset():
                scalar = _fetch_one_dict(cur)
                if scalar:
                    total = int(scalar.get("total_count") or 0)
            return rows, total

    result = handle_db_operation(_operation, error_context=context, default_return=([], 0))
    return result if isinstance(result, tuple) else ([], 0)


def create_billing_group(*, id: str, billing_group_hash: str, name: str, description: str | None, owner_id: str | None, provider: str, created_by: str | None) -> dict[str, Any] | None:
    return _callproc_one(
        "sp_billing_group_create",
        [id, billing_group_hash, name, description, owner_id, provider, created_by],
        context=f"create_billing_group(billing_group_hash={billing_group_hash})",
        commit=True,
    )


def update_billing_group(*, id: str, name: str | None, description: str | None, status: str | None) -> dict[str, Any] | None:
    return _callproc_one(
        "sp_billing_group_update",
        [id, name, description, status],
        context=f"update_billing_group(id={id})",
        commit=True,
    )


def set_billing_group_capabilities(*, id: str, checkout_enabled: bool | None, portal_enabled: bool | None, provisioning_enabled: bool | None, webhooks_enabled: bool | None) -> dict[str, Any] | None:
    return _callproc_one(
        "sp_billing_group_set_capabilities",
        [id, checkout_enabled, portal_enabled, provisioning_enabled, webhooks_enabled],
        context=f"set_billing_group_capabilities(id={id})",
        commit=True,
    )


def set_billing_group_credentials(
    *,
    id: str,
    stripe_account_label: str | None,
    stripe_account_fingerprint: str | None,
    stripe_secret_key_ciphertext: bytes,
    stripe_secret_key_hmac: bytes | None,
    stripe_secret_key_fingerprint: str | None,
    stripe_webhook_secret_ciphertext: bytes | None,
    stripe_webhook_secret_hmac: bytes | None,
    stripe_webhook_secret_fingerprint: str | None,
    stripe_portal_configuration_id_ciphertext: bytes | None,
    credential_key_id: str,
) -> dict[str, Any] | None:
    """Store encrypted per-group Stripe credentials. Returns fingerprints only."""

    return _callproc_one(
        "sp_billing_group_set_credentials",
        [
            id,
            stripe_account_label,
            stripe_account_fingerprint,
            stripe_secret_key_ciphertext,
            stripe_secret_key_hmac,
            stripe_secret_key_fingerprint,
            stripe_webhook_secret_ciphertext,
            stripe_webhook_secret_hmac,
            stripe_webhook_secret_fingerprint,
            stripe_portal_configuration_id_ciphertext,
            credential_key_id,
        ],
        context=f"set_billing_group_credentials(id={id})",
        commit=True,
    )


def get_billing_group_operational_credentials(*, id: str) -> dict[str, Any] | None:
    """SERVER-ONLY. Returns encrypted credential ciphertext for Stripe replay.

    The returned ciphertext/key metadata must never be serialized into S2S/browser
    responses, audit details, logs, or metrics.
    """

    return _callproc_one(
        "sp_billing_group_get_operational_credentials",
        [id],
        context=f"get_billing_group_operational_credentials(id={id})",
    )


def get_billing_group_by_hash(*, billing_group_hash: str) -> dict[str, Any] | None:
    return _callproc_one(
        "sp_billing_group_get_by_hash",
        [billing_group_hash],
        context=f"get_billing_group_by_hash(billing_group_hash={billing_group_hash})",
    )


def list_billing_groups(*, search: str | None, limit: int, offset: int) -> tuple[list[dict[str, Any]], int]:
    return _callproc_rows_and_total(
        "sp_billing_group_list",
        [search, limit, offset],
        context="list_billing_groups()",
    )


def get_billing_admin_metrics() -> dict[str, Any] | None:
    """Call `sp_billing_admin_metrics` for the admin dashboard aggregate (counts only)."""

    return _callproc_one(
        "sp_billing_admin_metrics",
        [],
        context="get_billing_admin_metrics()",
    )


def delete_billing_group(*, id: str) -> dict[str, Any] | None:
    return _callproc_one(
        "sp_billing_group_delete",
        [id],
        context=f"delete_billing_group(id={id})",
        commit=True,
    )


def resolve_billing_group_by_webhook_secret_hmac(*, provider: str, stripe_webhook_secret_hmac: bytes) -> dict[str, Any] | None:
    return _callproc_one(
        "sp_billing_group_resolve_by_webhook_secret_hmac",
        [provider, stripe_webhook_secret_hmac],
        context=f"resolve_billing_group_by_webhook_secret_hmac(provider={provider})",
    )


def attach_project_to_billing_group(*, id: str, billing_group_id: str, project_id: str, added_by: str | None) -> dict[str, Any] | None:
    return _callproc_one(
        "sp_billing_group_attach_project",
        [id, billing_group_id, project_id, added_by],
        context=f"attach_project_to_billing_group(billing_group_id={billing_group_id}, project_id={project_id})",
        commit=True,
    )


def detach_project_from_billing_group(*, project_id: str, removed_by: str | None) -> dict[str, Any] | None:
    return _callproc_one(
        "sp_billing_group_detach_project",
        [project_id, removed_by],
        context=f"detach_project_from_billing_group(project_id={project_id})",
        commit=True,
    )


def list_billing_group_projects(*, billing_group_id: str) -> list[dict[str, Any]]:
    return _callproc_all(
        "sp_billing_group_list_projects",
        [billing_group_id],
        context=f"list_billing_group_projects(billing_group_id={billing_group_id})",
    )


# =============================================================================
# Catalog items (CRUD + provisioning transitions + listing)
# =============================================================================


def create_catalog_item(
    *,
    id: str,
    catalog_item_hash: str,
    billing_group_id: str,
    provider: str,
    item_type: str,
    plan_code: str,
    tier_code: str | None,
    tier_name: str | None,
    display_name: str,
    currency: str | None,
    unit_amount: int | None,
    recurring_interval: str | None,
    lookup_key: str | None,
    features: JsonParam,
    metadata: JsonParam,
    sort_order: int | None,
    provisioning_idempotency_key_hmac: bytes | None,
    created_by: str | None,
) -> dict[str, Any] | None:
    return _callproc_one(
        "sp_billing_catalog_item_create",
        [
            id,
            catalog_item_hash,
            billing_group_id,
            provider,
            item_type,
            plan_code,
            tier_code,
            tier_name,
            display_name,
            currency,
            unit_amount,
            recurring_interval,
            lookup_key,
            _json_param(features),
            _json_param(metadata),
            sort_order,
            provisioning_idempotency_key_hmac,
            created_by,
        ],
        context=f"create_catalog_item(billing_group_id={billing_group_id}, plan_code={plan_code})",
        commit=True,
    )


def set_catalog_item_provisioned(
    *,
    id: str,
    provider_product_id_ciphertext: bytes | None,
    provider_product_id_hmac: bytes | None,
    provider_product_id_fingerprint: str | None,
    provider_price_id_ciphertext: bytes | None,
    provider_price_id_hmac: bytes | None,
    provider_price_id_fingerprint: str | None,
    provider_ref_key_id: str | None,
    lookup_key: str | None,
    activate: bool = True,
) -> dict[str, Any] | None:
    return _callproc_one(
        "sp_billing_catalog_item_set_provisioned",
        [
            id,
            provider_product_id_ciphertext,
            provider_product_id_hmac,
            provider_product_id_fingerprint,
            provider_price_id_ciphertext,
            provider_price_id_hmac,
            provider_price_id_fingerprint,
            provider_ref_key_id,
            lookup_key,
            activate,
        ],
        context=f"set_catalog_item_provisioned(id={id})",
        commit=True,
    )


def set_catalog_item_failed(*, id: str, provisioning_error_redacted: str | None) -> dict[str, Any] | None:
    return _callproc_one(
        "sp_billing_catalog_item_set_failed",
        [id, provisioning_error_redacted],
        context=f"set_catalog_item_failed(id={id})",
        commit=True,
    )


def set_catalog_item_active(*, id: str, active: bool) -> dict[str, Any] | None:
    return _callproc_one(
        "sp_billing_catalog_item_set_active",
        [id, active],
        context=f"set_catalog_item_active(id={id}, active={active})",
        commit=True,
    )


def archive_catalog_item(*, id: str) -> dict[str, Any] | None:
    return _callproc_one(
        "sp_billing_catalog_item_archive",
        [id],
        context=f"archive_catalog_item(id={id})",
        commit=True,
    )


def update_catalog_item(
    *,
    id: str,
    display_name: str | None,
    tier_name: str | None,
    currency: str | None,
    unit_amount: int | None,
    recurring_interval: str | None,
    features: JsonParam,
    metadata: JsonParam,
    sort_order: int | None,
) -> dict[str, Any] | None:
    return _callproc_one(
        "sp_billing_catalog_item_update",
        [id, display_name, tier_name, currency, unit_amount, recurring_interval, _json_param(features), _json_param(metadata), sort_order],
        context=f"update_catalog_item(id={id})",
        commit=True,
    )


def get_catalog_operational_refs(*, id: str) -> dict[str, Any] | None:
    """SERVER-ONLY. Encrypted product/price refs for Stripe replay (price rotation)."""

    return _callproc_one(
        "sp_billing_catalog_get_operational_refs",
        [id],
        context=f"get_catalog_operational_refs(id={id})",
    )


def get_catalog_item_by_hash(*, catalog_item_hash: str) -> dict[str, Any] | None:
    return _callproc_one(
        "sp_billing_catalog_get_by_hash",
        [catalog_item_hash],
        context=f"get_catalog_item_by_hash(catalog_item_hash={catalog_item_hash})",
    )


def list_catalog_for_group(*, billing_group_id: str, item_type: str | None = None, include_archived: bool = False) -> list[dict[str, Any]]:
    return _callproc_all(
        "sp_billing_catalog_list_for_group",
        [billing_group_id, item_type, include_archived],
        context=f"list_catalog_for_group(billing_group_id={billing_group_id})",
    )


def list_catalog_for_project(*, project_hash: str, item_type: str | None = None, provider: str = "stripe") -> list[dict[str, Any]]:
    return _callproc_all(
        "sp_billing_catalog_list_for_project",
        [project_hash, item_type, provider],
        context=f"list_catalog_for_project(project_hash={project_hash})",
    )


# --------------------------------------------------------------------------- catalog reconcile (pull)


def list_catalog_refs_for_group(*, billing_group_id: str, include_archived: bool = False) -> list[dict[str, Any]]:
    """SERVER-ONLY. Catalog rows with provider-ref fingerprints for Stripe->local reconcile join."""

    return _callproc_all(
        "sp_billing_catalog_list_refs_for_group",
        [billing_group_id, include_archived],
        context=f"list_catalog_refs_for_group(billing_group_id={billing_group_id})",
    )


def adopt_catalog_item_refs(
    *,
    id: str,
    provider_product_id_ciphertext: bytes | None,
    provider_product_id_hmac: bytes | None,
    provider_product_id_fingerprint: str | None,
    provider_price_id_ciphertext: bytes | None,
    provider_price_id_hmac: bytes | None,
    provider_price_id_fingerprint: str | None,
    provider_ref_key_id: str | None,
    lookup_key: str | None,
) -> dict[str, Any] | None:
    """Repair a local row by adopting the existing Stripe product/price refs (reconcile)."""

    return _callproc_one(
        "sp_billing_catalog_item_adopt_refs",
        [
            id,
            provider_product_id_ciphertext,
            provider_product_id_hmac,
            provider_product_id_fingerprint,
            provider_price_id_ciphertext,
            provider_price_id_hmac,
            provider_price_id_fingerprint,
            provider_ref_key_id,
            lookup_key,
        ],
        context=f"adopt_catalog_item_refs(id={id})",
        commit=True,
    )


def import_catalog_item(
    *,
    id: str,
    catalog_item_hash: str,
    billing_group_id: str,
    provider: str,
    item_type: str,
    plan_code: str,
    display_name: str,
    currency: str | None,
    unit_amount: int | None,
    recurring_interval: str | None,
    lookup_key: str | None,
    provider_product_id_ciphertext: bytes | None,
    provider_product_id_hmac: bytes | None,
    provider_product_id_fingerprint: str | None,
    provider_price_id_ciphertext: bytes | None,
    provider_price_id_hmac: bytes | None,
    provider_price_id_fingerprint: str | None,
    provider_ref_key_id: str | None,
    provisioning_idempotency_key_hmac: bytes | None,
) -> dict[str, Any] | None:
    """Idempotently adopt an orphan Stripe product/price as an already-provisioned catalog item."""

    return _callproc_one(
        "sp_billing_catalog_item_import",
        [
            id,
            catalog_item_hash,
            billing_group_id,
            provider,
            item_type,
            plan_code,
            display_name,
            currency,
            unit_amount,
            recurring_interval,
            lookup_key,
            provider_product_id_ciphertext,
            provider_product_id_hmac,
            provider_product_id_fingerprint,
            provider_price_id_ciphertext,
            provider_price_id_hmac,
            provider_price_id_fingerprint,
            provider_ref_key_id,
            provisioning_idempotency_key_hmac,
        ],
        context=f"import_catalog_item(billing_group_id={billing_group_id}, plan_code={plan_code})",
        commit=True,
    )


def set_billing_group_catalog_sync_status(*, id: str, status: str, error_redacted: str | None, synced_at: str | None) -> dict[str, Any] | None:
    return _callproc_one(
        "sp_billing_group_set_catalog_sync_status",
        [id, status, error_redacted, synced_at],
        context=f"set_billing_group_catalog_sync_status(id={id}, status={status})",
        commit=True,
    )


__all__ = [
    "adopt_catalog_item_refs",
    "import_catalog_item",
    "list_catalog_refs_for_group",
    "set_billing_group_catalog_sync_status",
    "archive_catalog_item",
    "attach_project_to_billing_group",
    "billing_provider_exists",
    "begin_checkout_intent",
    "claim_sync_jobs",
    "complete_checkout_intent",
    "complete_sync_job",
    "create_billing_group",
    "create_catalog_item",
    "delete_billing_group",
    "detach_project_from_billing_group",
    "enqueue_sync_job",
    "get_billing_group_by_hash",
    "get_billing_group_operational_credentials",
    "get_catalog_item_by_hash",
    "get_catalog_operational_refs",
    "get_current_by_user_project",
    "get_session_plan",
    "get_customer_operational_ref",
    "list_billing_group_projects",
    "list_billing_groups",
    "list_catalog_for_group",
    "list_catalog_for_project",
    "observe_subscription",
    "resolve_billing_group_by_webhook_secret_hmac",
    "resolve_user_billing_group",
    "record_billing_webhook_delivery",
    "record_purchase_event",
    "record_webhook_delivery",
    "resolve_user_project",
    "run_billing_retention_purge",
    "run_retention_purge",
    "set_billing_group_capabilities",
    "set_billing_group_credentials",
    "set_catalog_item_active",
    "set_catalog_item_failed",
    "set_catalog_item_provisioned",
    "update_billing_group",
    "update_catalog_item",
    "upsert_billing_customer",
    "upsert_customer",
]
