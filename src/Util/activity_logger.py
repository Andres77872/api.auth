"""
Activity Logger Utility

Handles activity logging for the multi-project authentication system.
Provides functions to log user activities, system events, and administrative actions.
Uses database activity catalog and stored procedures for consistent logging.
"""

import json
import logging
import re
import time
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Dict, Any, List, Union, Callable
from functools import wraps
from contextvars import ContextVar

from src.Util.db_config import get_connection
from src.Util.uuid_generator import generate_activity_log_id
from src.Util.auth_constants import (
    BILLING_ACTIVITY_CATALOG_RANGE as AUTH_BILLING_ACTIVITY_CATALOG_RANGE,
    BILLING_ACTIVITY_CATALOG_RANGE_END,
    BILLING_ACTIVITY_CATALOG_RANGE_START,
    BILLING_REDACTION_FIELD_NAMES,
    PATREON_ACTIVITY_CATALOG_RANGE as AUTH_PATREON_ACTIVITY_CATALOG_RANGE,
    PATREON_ACTIVITY_CATALOG_RANGE_END,
    PATREON_ACTIVITY_CATALOG_RANGE_START,
    PATREON_REDACTION_FIELD_NAMES,
)

# Configure logging
logger = logging.getLogger(__name__)

# Context variables for request-level data
_request_context: ContextVar[Dict[str, Any]] = ContextVar('request_context', default={})


class ActivityType(Enum):
    """Enum for different types of activities"""
    USER_LOGIN = "user_login"
    USER_LOGOUT = "user_logout"
    USER_REGISTRATION = "user_registration"
    USER_UPDATE = "user_update"
    USER_STATUS_CHANGE = "user_status_change"
    USER_PASSWORD_RESET = "user_password_reset"
    USER_TYPE_CHANGED = "user_type_changed"
    PROJECT_CREATION = "project_creation"
    PROJECT_UPDATE = "project_update"
    PROJECT_DELETE = "project_delete"
    PROJECT_MEMBER_ADD = "project_member_add"
    PROJECT_MEMBER_REMOVE = "project_member_remove"
    PROJECT_MEMBER_REMOVED = "project_member_removed"
    PROJECT_OWNERSHIP_TRANSFERRED = "project_ownership_transferred"
    PROJECT_ARCHIVED = "project_archived"
    PROJECT_UNARCHIVED = "project_unarchived"
    GROUP_CREATION = "group_creation"
    GROUP_UPDATE = "group_update"
    GROUP_DELETE = "group_delete"
    USER_GROUP_ASSIGN = "user_group_assign"
    USER_GROUP_REMOVE = "user_group_remove"
    PERMISSION_GRANT = "permission_grant"
    PERMISSION_REVOKE = "permission_revoke"
    ROLE_REMOVED = "role_removed"
    BULK_ROLE_ASSIGNMENT = "bulk_role_assignment"
    BULK_GROUP_ASSIGNMENT = "bulk_group_assignment"
    BULK_USER_UPDATE = "bulk_user_update"
    BULK_USER_DELETE = "bulk_user_delete"
    ADMIN_ACTION = "admin_action"
    SYSTEM_EVENT = "system_event"
    USER_EMAIL_ADDED = "user_email_added"
    USER_EMAIL_ACTIVATION_REQUESTED = "user_email_activation_requested"
    USER_EMAIL_ACTIVATION_RESENT = "user_email_activation_resent"
    USER_EMAIL_ACTIVATED = "user_email_activated"
    USER_EMAIL_REMOVED = "user_email_removed"
    USER_EMAIL_PRIMARY_CHANGED = "user_email_primary_changed"
    AUTH_EMAIL_LOGIN = "auth_email_login"
    PASSWORD_RESET_REQUESTED = "password_reset_requested"
    PASSWORD_RESET_CONSUMED = "password_reset_consumed"
    ADMIN_PASSWORD_RESET_REQUESTED = "admin_password_reset_requested"
    PASSWORD_CHANGED = "password_changed"
    EMAIL_MESSAGE_ENQUEUED = "email_message_enqueued"
    EMAIL_MESSAGE_SENT = "email_message_sent"
    EMAIL_MESSAGE_DELIVERED = "email_message_delivered"
    EMAIL_MESSAGE_BOUNCED = "email_message_bounced"
    EMAIL_MESSAGE_COMPLAINED = "email_message_complained"
    EMAIL_MESSAGE_DEAD_LETTERED = "email_message_dead_lettered"
    EMAIL_SUPPRESSION_UPDATED = "email_suppression_updated"
    GOOGLE_OAUTH_STARTED = "google_oauth_started"
    GOOGLE_OAUTH_PROVIDER_INIT_REJECTED = "google_oauth_provider_init_rejected"
    GOOGLE_OAUTH_CALLBACK_RECEIVED = "google_oauth_callback_received"
    GOOGLE_OAUTH_STATE_REJECTED = "google_oauth_state_rejected"
    GOOGLE_OAUTH_NONCE_REJECTED = "google_oauth_nonce_rejected"
    GOOGLE_OAUTH_TOKEN_EXCHANGE_FAILED = "google_oauth_token_exchange_failed"
    GOOGLE_OAUTH_ID_TOKEN_REJECTED = "google_oauth_id_token_rejected"
    GOOGLE_OAUTH_LOGIN_SUCCEEDED = "google_oauth_login_succeeded"
    GOOGLE_OAUTH_LOGIN_DENIED = "google_oauth_login_denied"
    GOOGLE_OAUTH_EXTERNAL_ACCOUNT_LINKED = "google_oauth_external_account_linked"
    GOOGLE_OAUTH_EXTERNAL_ACCOUNT_UNLINKED = "google_oauth_external_account_unlinked"
    PATREON_LINK_PROOF_REQUESTED = "patreon_link_proof_requested"
    PATREON_LINK_PROOF_CONSUMED = "patreon_link_proof_consumed"
    PATREON_LINKED = "patreon_linked"
    PATREON_LINK_REJECTED = "patreon_link_rejected"
    PATREON_UNLINKED = "patreon_unlinked"
    PATREON_WEBHOOK_RECEIVED = "patreon_webhook_received"
    PATREON_WEBHOOK_REJECTED = "patreon_webhook_rejected"
    PATREON_WEBHOOK_REPLAY_IGNORED = "patreon_webhook_replay_ignored"
    PATREON_SYNC_STARTED = "patreon_sync_started"
    PATREON_SYNC_COMPLETED = "patreon_sync_completed"
    PATREON_SYNC_FAILED = "patreon_sync_failed"
    PATREON_ENTITLEMENT_CHANGED = "patreon_entitlement_changed"
    PATREON_TIER_MAP_MISS = "patreon_tier_map_miss"
    PATREON_TOKEN_REFRESHED = "patreon_token_refreshed"
    PATREON_TOKEN_REVOKED = "patreon_token_revoked"
    PATREON_RETENTION_PURGED = "patreon_retention_purged"
    BILLING_S2S_READ = "billing_s2s_read"
    BILLING_CHECKOUT_CREATED = "billing_checkout_created"
    BILLING_CHECKOUT_REJECTED = "billing_checkout_rejected"
    BILLING_PORTAL_CREATED = "billing_portal_created"
    BILLING_PORTAL_REJECTED = "billing_portal_rejected"
    STRIPE_WEBHOOK_RECEIVED = "stripe_webhook_received"
    STRIPE_WEBHOOK_REJECTED = "stripe_webhook_rejected"
    STRIPE_WEBHOOK_REPLAY_IGNORED = "stripe_webhook_replay_ignored"
    BILLING_STATUS_CHANGED = "billing_status_changed"
    BILLING_PURCHASE_STATUS_CHANGED = "billing_purchase_status_changed"
    BILLING_SYNC_STARTED = "billing_sync_started"
    BILLING_SYNC_COMPLETED = "billing_sync_completed"
    BILLING_SYNC_FAILED = "billing_sync_failed"
    BILLING_PROVIDER_REF_MISMATCH = "billing_provider_ref_mismatch"
    BILLING_RETENTION_PURGED = "billing_retention_purged"
    BILLING_KEY_ROTATION_COMPLETED = "billing_key_rotation_completed"


EMAIL_ACTIVITY_CATALOG_RANGE = {
    "act-cat-046": ActivityType.USER_EMAIL_ADDED.value,
    "act-cat-047": ActivityType.USER_EMAIL_ACTIVATION_REQUESTED.value,
    "act-cat-048": ActivityType.USER_EMAIL_ACTIVATION_RESENT.value,
    "act-cat-049": ActivityType.USER_EMAIL_ACTIVATED.value,
    "act-cat-050": ActivityType.USER_EMAIL_REMOVED.value,
    "act-cat-051": ActivityType.USER_EMAIL_PRIMARY_CHANGED.value,
    "act-cat-052": ActivityType.AUTH_EMAIL_LOGIN.value,
    "act-cat-053": ActivityType.PASSWORD_RESET_REQUESTED.value,
    "act-cat-054": ActivityType.PASSWORD_RESET_CONSUMED.value,
    "act-cat-055": ActivityType.ADMIN_PASSWORD_RESET_REQUESTED.value,
    "act-cat-056": ActivityType.EMAIL_MESSAGE_ENQUEUED.value,
    "act-cat-057": ActivityType.EMAIL_MESSAGE_SENT.value,
    "act-cat-058": ActivityType.EMAIL_MESSAGE_DELIVERED.value,
    "act-cat-059": ActivityType.EMAIL_MESSAGE_BOUNCED.value,
    "act-cat-060": ActivityType.EMAIL_MESSAGE_COMPLAINED.value,
    "act-cat-061": ActivityType.EMAIL_MESSAGE_DEAD_LETTERED.value,
    "act-cat-062": ActivityType.EMAIL_SUPPRESSION_UPDATED.value,
}

PASSWORD_RECOVERY_ACTIVITY_CATALOG_RANGE = {
    "act-cat-063": ActivityType.PASSWORD_CHANGED.value,
}

GOOGLE_OAUTH_ACTIVITY_CATALOG_RANGE = {
    "act-cat-064": ActivityType.GOOGLE_OAUTH_STARTED.value,
    "act-cat-065": ActivityType.GOOGLE_OAUTH_PROVIDER_INIT_REJECTED.value,
    "act-cat-066": ActivityType.GOOGLE_OAUTH_CALLBACK_RECEIVED.value,
    "act-cat-067": ActivityType.GOOGLE_OAUTH_STATE_REJECTED.value,
    "act-cat-068": ActivityType.GOOGLE_OAUTH_NONCE_REJECTED.value,
    "act-cat-069": ActivityType.GOOGLE_OAUTH_TOKEN_EXCHANGE_FAILED.value,
    "act-cat-070": ActivityType.GOOGLE_OAUTH_ID_TOKEN_REJECTED.value,
    "act-cat-071": ActivityType.GOOGLE_OAUTH_LOGIN_SUCCEEDED.value,
    "act-cat-072": ActivityType.GOOGLE_OAUTH_LOGIN_DENIED.value,
    "act-cat-073": ActivityType.GOOGLE_OAUTH_EXTERNAL_ACCOUNT_LINKED.value,
    "act-cat-074": ActivityType.GOOGLE_OAUTH_EXTERNAL_ACCOUNT_UNLINKED.value,
}

PATREON_ACTIVITY_CATALOG_RANGE = {
    "act-cat-075": ActivityType.PATREON_LINK_PROOF_REQUESTED.value,
    "act-cat-076": ActivityType.PATREON_LINK_PROOF_CONSUMED.value,
    "act-cat-077": ActivityType.PATREON_LINKED.value,
    "act-cat-078": ActivityType.PATREON_LINK_REJECTED.value,
    "act-cat-079": ActivityType.PATREON_UNLINKED.value,
    "act-cat-080": ActivityType.PATREON_WEBHOOK_RECEIVED.value,
    "act-cat-081": ActivityType.PATREON_WEBHOOK_REJECTED.value,
    "act-cat-082": ActivityType.PATREON_WEBHOOK_REPLAY_IGNORED.value,
    "act-cat-083": ActivityType.PATREON_SYNC_STARTED.value,
    "act-cat-084": ActivityType.PATREON_SYNC_COMPLETED.value,
    "act-cat-085": ActivityType.PATREON_SYNC_FAILED.value,
    "act-cat-086": ActivityType.PATREON_ENTITLEMENT_CHANGED.value,
    "act-cat-087": ActivityType.PATREON_TIER_MAP_MISS.value,
    "act-cat-088": ActivityType.PATREON_TOKEN_REFRESHED.value,
    "act-cat-089": ActivityType.PATREON_TOKEN_REVOKED.value,
    "act-cat-090": ActivityType.PATREON_RETENTION_PURGED.value,
}
PATREON_ACTIVITY_TYPES = tuple(PATREON_ACTIVITY_CATALOG_RANGE.values())
PATREON_ACTIVITY_CATALOG_CODE_BY_TYPE = {
    activity_type: catalog_id
    for catalog_id, activity_type in PATREON_ACTIVITY_CATALOG_RANGE.items()
}
PATREON_ACTIVITY_REDACTED_VALUE = "***FILTERED***"
PATREON_ACTIVITY_FORBIDDEN_DETAIL_FIELDS = frozenset(
    field.lower().replace("-", "_") for field in PATREON_REDACTION_FIELD_NAMES
)

BILLING_ACTIVITY_CATALOG_RANGE = {
    "act-cat-091": ActivityType.BILLING_S2S_READ.value,
    "act-cat-092": ActivityType.BILLING_CHECKOUT_CREATED.value,
    "act-cat-093": ActivityType.BILLING_CHECKOUT_REJECTED.value,
    "act-cat-094": ActivityType.BILLING_PORTAL_CREATED.value,
    "act-cat-095": ActivityType.BILLING_PORTAL_REJECTED.value,
    "act-cat-096": ActivityType.STRIPE_WEBHOOK_RECEIVED.value,
    "act-cat-097": ActivityType.STRIPE_WEBHOOK_REJECTED.value,
    "act-cat-098": ActivityType.STRIPE_WEBHOOK_REPLAY_IGNORED.value,
    "act-cat-099": ActivityType.BILLING_STATUS_CHANGED.value,
    "act-cat-100": ActivityType.BILLING_PURCHASE_STATUS_CHANGED.value,
    "act-cat-101": ActivityType.BILLING_SYNC_STARTED.value,
    "act-cat-102": ActivityType.BILLING_SYNC_COMPLETED.value,
    "act-cat-103": ActivityType.BILLING_SYNC_FAILED.value,
    "act-cat-104": ActivityType.BILLING_PROVIDER_REF_MISMATCH.value,
    "act-cat-105": ActivityType.BILLING_RETENTION_PURGED.value,
    "act-cat-106": ActivityType.BILLING_KEY_ROTATION_COMPLETED.value,
}
BILLING_ACTIVITY_TYPES = tuple(BILLING_ACTIVITY_CATALOG_RANGE.values())
BILLING_ACTIVITY_CATALOG_CODE_BY_TYPE = {
    activity_type: catalog_id
    for catalog_id, activity_type in BILLING_ACTIVITY_CATALOG_RANGE.items()
}
BILLING_ACTIVITY_FORBIDDEN_DETAIL_FIELDS = frozenset(
    field.lower().replace("-", "_") for field in BILLING_REDACTION_FIELD_NAMES
)


def is_patreon_activity_type(activity_type: Union[ActivityType, str]) -> bool:
    """Return True when an activity type belongs to the Patreon catalog range."""
    value = activity_type.value if isinstance(activity_type, ActivityType) else str(activity_type)
    return value in PATREON_ACTIVITY_TYPES


def get_patreon_activity_catalog_code(activity_type: Union[ActivityType, str]) -> str:
    """Return the seeded act-cat-075..090 catalog id for a Patreon activity type."""
    value = activity_type.value if isinstance(activity_type, ActivityType) else str(activity_type)
    try:
        return PATREON_ACTIVITY_CATALOG_CODE_BY_TYPE[value]
    except KeyError as exc:
        raise ValueError(f"Unknown Patreon activity type: {value}") from exc


def is_billing_activity_type(activity_type: Union[ActivityType, str]) -> bool:
    """Return True when an activity type belongs to the billing/Stripe catalog range."""

    value = activity_type.value if isinstance(activity_type, ActivityType) else str(activity_type)
    return value in BILLING_ACTIVITY_TYPES


def get_billing_activity_catalog_code(activity_type: Union[ActivityType, str]) -> str:
    """Return the seeded act-cat-091..106 catalog id for a billing/Stripe activity type."""

    value = activity_type.value if isinstance(activity_type, ActivityType) else str(activity_type)
    try:
        return BILLING_ACTIVITY_CATALOG_CODE_BY_TYPE[value]
    except KeyError as exc:
        raise ValueError(f"Unknown billing activity type: {value}") from exc


def _is_patreon_sensitive_detail_field(key: str) -> bool:
    normalized = (key or "").lower().replace("-", "_")
    if normalized in PATREON_ACTIVITY_FORBIDDEN_DETAIL_FIELDS:
        return True
    return any(
        fragment in normalized
        for fragment in (
            "raw_",
            "payload",
            "secret",
            "token",
            "signature",
            "email",
            "fingerprint",
            "hash",
            "provider_sub",
            "campaign_id",
            "tier_id",
            "member_id",
            "user_id_hash",
        )
    )


def _is_billing_sensitive_detail_field(key: str) -> bool:
    normalized = (key or "").lower().replace("-", "_")
    if normalized in BILLING_ACTIVITY_FORBIDDEN_DETAIL_FIELDS:
        return True
    return any(
        fragment in normalized
        for fragment in (
            "raw_",
            "payload",
            "secret",
            "token",
            "signature",
            "fingerprint",
            "hash",
            "hmac",
            "stripe_customer",
            "stripe_subscription",
            "stripe_price",
            "stripe_product",
            "stripe_invoice",
            "stripe_payment",
            "stripe_charge",
            "stripe_checkout",
            "stripe_portal",
            "stripe_event",
            "provider_id",
            "payment_method",
            "receipt_url",
            "client_secret",
            "idempotency",
            "card",
            "last4",
        )
    )


def _sanitize_patreon_activity_text(value: str) -> str:
    """Redact obvious Patreon credential/PII fragments from free text details."""
    sanitized = re.sub(
        r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
        PATREON_ACTIVITY_REDACTED_VALUE,
        value,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(r"Bearer\s+\S+", f"Bearer {PATREON_ACTIVITY_REDACTED_VALUE}", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(
        r"\b(token|secret|signature|payload)\s*[=:]\s*[^\s,;&]+",
        lambda match: f"{match.group(1)}=[REDACTED]",
        sanitized,
        flags=re.IGNORECASE,
    )
    return sanitized


def _sanitize_billing_activity_text(value: str) -> str:
    """Redact obvious billing/Stripe credential and provider-id fragments from details."""

    sanitized = re.sub(
        r"\b(?:cus|sub|price|prod|in|pi|ch|cs|bps|evt)_[A-Za-z0-9_./-]+",
        PATREON_ACTIVITY_REDACTED_VALUE,
        str(value),
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(
        r"\bt=\d{5,},v1=[A-Za-z0-9,_=-]+",
        PATREON_ACTIVITY_REDACTED_VALUE,
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(r"Bearer\s+\S+", f"Bearer {PATREON_ACTIVITY_REDACTED_VALUE}", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(
        r"\b(token|secret|signature|payload|idempotency[_-]?key|client[_-]?secret|receipt_url|last4)\s*[=:]\s*[^\s,;&]+",
        lambda match: f"{match.group(1)}=[REDACTED]",
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(r"\b[a-f0-9]{64}\b", PATREON_ACTIVITY_REDACTED_VALUE, sanitized, flags=re.IGNORECASE)
    return sanitized


def sanitize_patreon_activity_details(details: Union[Dict[str, Any], List[Any], str, Any]) -> Union[Dict[str, Any], List[Any], str, Any]:
    """Return Patreon activity details with server-only fields redacted recursively."""
    if isinstance(details, dict):
        sanitized: Dict[str, Any] = {}
        for key, value in details.items():
            if _is_patreon_sensitive_detail_field(str(key)):
                sanitized[key] = PATREON_ACTIVITY_REDACTED_VALUE
            else:
                sanitized[key] = sanitize_patreon_activity_details(value)
        return sanitized
    if isinstance(details, list):
        return [sanitize_patreon_activity_details(item) for item in details]
    if isinstance(details, str):
        return _sanitize_patreon_activity_text(details)
    return details


def sanitize_billing_activity_details(details: Union[Dict[str, Any], List[Any], str, Any]) -> Union[Dict[str, Any], List[Any], str, Any]:
    """Return billing/Stripe activity details with server-only fields redacted recursively."""

    if isinstance(details, dict):
        sanitized: Dict[str, Any] = {}
        for key, value in details.items():
            if _is_billing_sensitive_detail_field(str(key)):
                sanitized[key] = PATREON_ACTIVITY_REDACTED_VALUE
            else:
                sanitized[key] = sanitize_billing_activity_details(value)
        return sanitized
    if isinstance(details, list):
        return [sanitize_billing_activity_details(item) for item in details]
    if isinstance(details, str):
        return _sanitize_billing_activity_text(details)
    return details


def build_patreon_activity_details(action: str, **details: Any) -> Dict[str, Any]:
    """Build a redacted details payload for Patreon activity emission."""
    payload: Dict[str, Any] = {"action": action}
    payload.update(details)
    return sanitize_patreon_activity_details(payload)


def build_billing_activity_details(action: str, **details: Any) -> Dict[str, Any]:
    """Build a redacted details payload for billing/Stripe activity emission."""

    payload: Dict[str, Any] = {"action": action}
    payload.update(details)
    return sanitize_billing_activity_details(payload)


def assert_email_activity_catalog_alignment(catalog_codes: Optional[Dict[str, str]] = None) -> None:
    """Fail loudly if email ActivityType values drift from act-cat-046..062.

    Tests may pass a SQL-derived mapping. Without an argument, this validates the
    enum side only so route/worker code can guard imports before emitting events.
    """
    enum_values = {item.value for item in ActivityType}
    expected_values = set(EMAIL_ACTIVITY_CATALOG_RANGE.values())
    missing_enum_values = expected_values - enum_values
    if missing_enum_values:
        raise RuntimeError(f"Missing email ActivityType values: {sorted(missing_enum_values)}")

    if catalog_codes is not None:
        missing_catalog_ids = set(EMAIL_ACTIVITY_CATALOG_RANGE) - set(catalog_codes)
        mismatched_values = {
            catalog_id: expected
            for catalog_id, expected in EMAIL_ACTIVITY_CATALOG_RANGE.items()
            if catalog_codes.get(catalog_id) != expected
        }
        if missing_catalog_ids or mismatched_values:
            raise RuntimeError(
                "Email activity catalog drift: "
                f"missing={sorted(missing_catalog_ids)} mismatched={mismatched_values}"
            )


def assert_password_recovery_activity_catalog_alignment(catalog_codes: Optional[Dict[str, str]] = None) -> None:
    """Fail loudly if password-recovery ActivityType values drift from SQL."""

    enum_values = {item.value for item in ActivityType}
    expected_values = set(PASSWORD_RECOVERY_ACTIVITY_CATALOG_RANGE.values())
    missing_enum_values = expected_values - enum_values
    if missing_enum_values:
        raise RuntimeError(f"Missing password-recovery ActivityType values: {sorted(missing_enum_values)}")

    if catalog_codes is not None:
        missing_catalog_ids = set(PASSWORD_RECOVERY_ACTIVITY_CATALOG_RANGE) - set(catalog_codes)
        mismatched_values = {
            catalog_id: expected
            for catalog_id, expected in PASSWORD_RECOVERY_ACTIVITY_CATALOG_RANGE.items()
            if catalog_codes.get(catalog_id) != expected
        }
        if missing_catalog_ids or mismatched_values:
            raise RuntimeError(
                "Password-recovery activity catalog drift: "
                f"missing={sorted(missing_catalog_ids)} mismatched={mismatched_values}"
            )


def assert_google_oauth_activity_catalog_alignment(catalog_codes: Optional[Dict[str, str]] = None) -> None:
    """Fail loudly if Google OAuth ActivityType values drift from act-cat-064..074."""

    enum_values = {item.value for item in ActivityType}
    expected_values = set(GOOGLE_OAUTH_ACTIVITY_CATALOG_RANGE.values())
    missing_enum_values = expected_values - enum_values
    if missing_enum_values:
        raise RuntimeError(f"Missing Google OAuth ActivityType values: {sorted(missing_enum_values)}")

    reserved_numbers = {
        int(catalog_id.rsplit("-", 1)[1])
        for catalog_id in GOOGLE_OAUTH_ACTIVITY_CATALOG_RANGE
    }
    if reserved_numbers != set(range(64, 75)):
        raise RuntimeError(
            "Google OAuth activity catalog drift: "
            f"reserved_range={sorted(reserved_numbers)} expected={list(range(64, 75))}"
        )

    if catalog_codes is not None:
        missing_catalog_ids = set(GOOGLE_OAUTH_ACTIVITY_CATALOG_RANGE) - set(catalog_codes)
        mismatched_values = {
            catalog_id: expected
            for catalog_id, expected in GOOGLE_OAUTH_ACTIVITY_CATALOG_RANGE.items()
            if catalog_codes.get(catalog_id) != expected
        }
        if missing_catalog_ids or mismatched_values:
            raise RuntimeError(
                "Google OAuth activity catalog drift: "
                f"missing={sorted(missing_catalog_ids)} mismatched={mismatched_values}"
            )


def assert_patreon_activity_catalog_alignment(catalog_codes: Optional[Dict[str, str]] = None) -> None:
    """Fail loudly if Patreon ActivityType values drift from act-cat-075..090."""

    if PATREON_ACTIVITY_CATALOG_RANGE != dict(AUTH_PATREON_ACTIVITY_CATALOG_RANGE):
        raise RuntimeError(
            "Patreon activity catalog drift: "
            f"activity_logger={PATREON_ACTIVITY_CATALOG_RANGE} auth_constants={AUTH_PATREON_ACTIVITY_CATALOG_RANGE}"
        )

    enum_values = {item.value for item in ActivityType}
    expected_values = set(PATREON_ACTIVITY_CATALOG_RANGE.values())
    missing_enum_values = expected_values - enum_values
    if missing_enum_values:
        raise RuntimeError(f"Missing Patreon ActivityType values: {sorted(missing_enum_values)}")

    reserved_numbers = {
        int(catalog_id.rsplit("-", 1)[1])
        for catalog_id in PATREON_ACTIVITY_CATALOG_RANGE
    }
    expected_range = set(range(PATREON_ACTIVITY_CATALOG_RANGE_START, PATREON_ACTIVITY_CATALOG_RANGE_END + 1))
    if reserved_numbers != expected_range:
        raise RuntimeError(
            "Patreon activity catalog drift: "
            f"reserved_range={sorted(reserved_numbers)} expected={sorted(expected_range)}"
        )

    if catalog_codes is not None:
        missing_catalog_ids = set(PATREON_ACTIVITY_CATALOG_RANGE) - set(catalog_codes)
        mismatched_values = {
            catalog_id: expected
            for catalog_id, expected in PATREON_ACTIVITY_CATALOG_RANGE.items()
            if catalog_codes.get(catalog_id) != expected
        }
        if missing_catalog_ids or mismatched_values:
            raise RuntimeError(
                "Patreon activity catalog drift: "
                f"missing={sorted(missing_catalog_ids)} mismatched={mismatched_values}"
            )


def assert_billing_activity_catalog_alignment(catalog_codes: Optional[Dict[str, str]] = None) -> None:
    """Fail loudly if billing/Stripe ActivityType values drift from act-cat-091..106."""

    if BILLING_ACTIVITY_CATALOG_RANGE != dict(AUTH_BILLING_ACTIVITY_CATALOG_RANGE):
        raise RuntimeError(
            "Billing activity catalog drift: "
            f"activity_logger={BILLING_ACTIVITY_CATALOG_RANGE} auth_constants={AUTH_BILLING_ACTIVITY_CATALOG_RANGE}"
        )

    enum_values = {item.value for item in ActivityType}
    expected_values = set(BILLING_ACTIVITY_CATALOG_RANGE.values())
    missing_enum_values = expected_values - enum_values
    if missing_enum_values:
        raise RuntimeError(f"Missing billing ActivityType values: {sorted(missing_enum_values)}")

    reserved_numbers = {
        int(catalog_id.rsplit("-", 1)[1])
        for catalog_id in BILLING_ACTIVITY_CATALOG_RANGE
    }
    expected_range = set(range(BILLING_ACTIVITY_CATALOG_RANGE_START, BILLING_ACTIVITY_CATALOG_RANGE_END + 1))
    if reserved_numbers != expected_range:
        raise RuntimeError(
            "Billing activity catalog drift: "
            f"reserved_range={sorted(reserved_numbers)} expected={sorted(expected_range)}"
        )

    occupied_ranges = {
        "email": {int(catalog_id.rsplit("-", 1)[1]) for catalog_id in EMAIL_ACTIVITY_CATALOG_RANGE},
        "password": {int(catalog_id.rsplit("-", 1)[1]) for catalog_id in PASSWORD_RECOVERY_ACTIVITY_CATALOG_RANGE},
        "google": {int(catalog_id.rsplit("-", 1)[1]) for catalog_id in GOOGLE_OAUTH_ACTIVITY_CATALOG_RANGE},
        "patreon": {int(catalog_id.rsplit("-", 1)[1]) for catalog_id in PATREON_ACTIVITY_CATALOG_RANGE},
    }
    overlaps = {
        name: sorted(reserved_numbers & numbers)
        for name, numbers in occupied_ranges.items()
        if reserved_numbers & numbers
    }
    if overlaps:
        raise RuntimeError(f"Billing activity catalog overlaps existing ranges: {overlaps}")

    if catalog_codes is not None:
        missing_catalog_ids = set(BILLING_ACTIVITY_CATALOG_RANGE) - set(catalog_codes)
        mismatched_values = {
            catalog_id: expected
            for catalog_id, expected in BILLING_ACTIVITY_CATALOG_RANGE.items()
            if catalog_codes.get(catalog_id) != expected
        }
        if missing_catalog_ids or mismatched_values:
            raise RuntimeError(
                "Billing activity catalog drift: "
                f"missing={sorted(missing_catalog_ids)} mismatched={mismatched_values}"
            )


class ActivityLogger:
    """
    Activity logging system for tracking user and system activities
    """

    @staticmethod
    def log_activity(
            user_id: Optional[str],
            activity_type: str,
            details: Union[Dict[str, Any], str],
            project_id: Optional[str] = None,
            user_group_id: Optional[str] = None,
            target_user_id: Optional[str] = None,
            ip_address: Optional[str] = None,
            user_agent: Optional[str] = None,
            metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Log an activity to the database using stored procedure
        
        Args:
            user_id: ID of the user performing the action
            activity_type: Type of activity (use ActivityType enum values or catalog codes)
            details: Additional details about the activity (dict or string)
            project_id: Project ID if applicable
            user_group_id: User group ID if applicable
            target_user_id: Target user ID if applicable
            ip_address: IP address of the user
            user_agent: User agent string
            metadata: Additional metadata as JSON
            
        Returns:
            Success status
        """
        t0 = time.monotonic()
        try:
            with get_connection() as con:
                cur = con.cursor()

                activity_id = generate_activity_log_id()
                
                # Convert details to string if dict
                details_str = json.dumps(details) if isinstance(details, dict) else str(details)
                
                # Convert metadata to JSON string if provided
                metadata_json = json.dumps(metadata) if metadata else None

                # Call stored procedure to log activity
                cur.callproc('sp_log_activity', [
                    activity_id,
                    user_id,
                    activity_type,
                    details_str,
                    project_id,
                    user_group_id,
                    target_user_id,
                    ip_address,
                    user_agent,
                    metadata_json
                ])

                con.commit()
                logger.info(f"AUTH_PERF|activity_log|{(time.monotonic() - t0) * 1000:.3f}")
                return True

        except Exception as e:
            logger.info(f"AUTH_PERF|activity_log|{(time.monotonic() - t0) * 1000:.3f}")
            logger.error(f"Failed to log activity: {str(e)}")
            return False

    @staticmethod
    def get_recent_activity(
            limit: int = 50,
            offset: int = 0,
            user_id: Optional[str] = None,
            project_id: Optional[str] = None,
            activity_type: Optional[str] = None,
            days: int = 30,
            search: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get recent activities with filtering using stored procedure
        
        Args:
            limit: Maximum number of results
            offset: Number of results to skip
            user_id: Filter by specific user
            project_id: Filter by specific project
            activity_type: Filter by activity type
            days: Number of days to look back
            search: Free-text search across activity_type, details, and username
            
        Returns:
            List of activity entries with catalog information
        """
        try:
            with get_connection() as con:
                cur = con.cursor()

                # Call stored procedure to get activity logs
                cur.callproc('sp_get_activity_logs', [
                    limit,
                    offset,
                    user_id,
                    project_id,
                    activity_type,
                    days,
                    search,
                ])

                # Fetch results from the stored procedure
                # In pymysql, callproc returns the result, use fetchall directly
                results = cur.fetchall()

                activities = []
                for row in results:
                    activity = {
                        "id": row[0],
                        "user_id": row[1],
                        "activity_type": row[2],
                        "details": row[3],
                        "project_id": row[4],
                        "user_group_id": row[5],
                        "target_user_id": row[6],
                        "ip_address": row[7],
                        "user_agent": row[8],
                        "metadata": row[9],
                        "severity_level": row[10],
                        "created_at": row[11],
                        "username": row[12],
                        "user_hash": row[13],
                        "project_name": row[14],
                        "project_hash": row[15],
                        "target_username": row[16],
                        "target_user_hash": row[17],
                        "user_group_name": row[18],
                        "activity_name": row[19],
                        "activity_category": row[20],
                        "activity_description": row[21]
                    }
                    activities.append(activity)

                return activities

        except Exception as e:
            logger.error(f"Failed to get recent activity: {str(e)}")
            return []

    @staticmethod
    def count_activity_logs(
            user_id: Optional[str] = None,
            project_id: Optional[str] = None,
            activity_type: Optional[str] = None,
            days: int = 30,
            search: Optional[str] = None,
    ) -> int:
        """
        Count activity logs with filtering using stored procedure
        
        Args:
            user_id: Filter by specific user
            project_id: Filter by specific project
            activity_type: Filter by activity type
            days: Number of days to look back
            search: Free-text search across activity_type, details, and username
            
        Returns:
            Count of matching activities
        """
        try:
            with get_connection() as con:
                cur = con.cursor()

                # Call stored procedure to count activity logs
                cur.callproc('sp_count_activity_logs', [
                    user_id,
                    project_id,
                    activity_type,
                    days,
                    search,
                ])

                # Fetch result from stored procedure
                row = cur.fetchone()
                return row[0] if row else 0

        except Exception as e:
            logger.error(f"Failed to count activity logs: {str(e)}")
            return 0

    @staticmethod
    def get_activity_by_id(activity_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a single activity log entry by ID with enriched fields.

        Args:
            activity_id: Activity log ID

        Returns:
            Activity entry dictionary with catalog information, or None
        """
        try:
            with get_connection() as con:
                cur = con.cursor()

                cur.execute("""
                    SELECT 
                        al.id,
                        al.user_id,
                        al.activity_type,
                        al.details,
                        al.project_id,
                        al.user_group_id,
                        al.target_user_id,
                        al.ip_address,
                        al.user_agent,
                        al.metadata,
                        al.severity_level,
                        al.created_at,
                        u.username,
                        u.user_hash,
                        p.project_name,
                        p.project_hash,
                        tu.username as target_username,
                        tu.user_hash as target_user_hash,
                        ug.group_name as user_group_name,
                        ac.activity_name,
                        ac.activity_category,
                        ac.activity_description
                    FROM activity_logs al
                    LEFT JOIN users u ON al.user_id = u.id
                    LEFT JOIN projects p ON al.project_id = p.id
                    LEFT JOIN users tu ON al.target_user_id = tu.id
                    LEFT JOIN user_groups ug ON al.user_group_id = ug.id
                    LEFT JOIN activity_catalog ac ON al.activity_catalog_id = ac.id
                    WHERE al.id = %s
                """, (activity_id,))

                row = cur.fetchone()
                if not row:
                    return None

                return {
                    "id": row[0],
                    "user_id": row[1],
                    "activity_type": row[2],
                    "details": row[3],
                    "project_id": row[4],
                    "user_group_id": row[5],
                    "target_user_id": row[6],
                    "ip_address": row[7],
                    "user_agent": row[8],
                    "metadata": row[9],
                    "severity_level": row[10],
                    "created_at": row[11],
                    "username": row[12],
                    "user_hash": row[13],
                    "project_name": row[14],
                    "project_hash": row[15],
                    "target_username": row[16],
                    "target_user_hash": row[17],
                    "user_group_name": row[18],
                    "activity_name": row[19],
                    "activity_category": row[20],
                    "activity_description": row[21],
                }

        except Exception as e:
            logger.error(f"Failed to get activity by id: {str(e)}")
            return None

    @staticmethod
    def get_activity_catalog(category: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get activity catalog entries
        
        Args:
            category: Optional category filter
            
        Returns:
            List of activity catalog entries
        """
        try:
            with get_connection() as con:
                cur = con.cursor()

                # Call stored procedure to get catalog
                cur.callproc('sp_get_activity_catalog', [category])

                # Fetch results from stored procedure
                results = cur.fetchall()

                catalog = []
                for row in results:
                    entry = {
                        "id": row[0],
                        "activity_code": row[1],
                        "activity_name": row[2],
                        "activity_description": row[3],
                        "activity_category": row[4],
                        "severity_level": row[5],
                        "requires_audit": row[6],
                        "is_active": row[7]
                    }
                    catalog.append(entry)

                return catalog

        except Exception as e:
            logger.error(f"Failed to get activity catalog: {str(e)}")
            return []

    @staticmethod
    def get_activity_by_code(activity_code: str) -> Optional[Dict[str, Any]]:
        """
        Get activity catalog entry by code
        
        Args:
            activity_code: Activity code to lookup
            
        Returns:
            Activity catalog entry or None
        """
        try:
            with get_connection() as con:
                cur = con.cursor()

                # Call stored procedure
                cur.callproc('sp_get_activity_by_code', [activity_code])

                # Fetch result
                row = cur.fetchone()
                if row:
                    return {
                        "id": row[0],
                        "activity_code": row[1],
                        "activity_name": row[2],
                        "activity_description": row[3],
                        "activity_category": row[4],
                        "severity_level": row[5],
                        "requires_audit": row[6],
                        "is_active": row[7]
                    }

                return None

        except Exception as e:
            logger.error(f"Failed to get activity by code: {str(e)}")
            return None

    @staticmethod
    def get_activity_stats(project_id: Optional[str] = None, days: int = 30) -> List[Dict[str, Any]]:
        """
        Get activity statistics by category
        
        Args:
            project_id: Optional project filter
            days: Number of days to look back
            
        Returns:
            List of activity statistics
        """
        try:
            with get_connection() as con:
                cur = con.cursor()

                # Call stored procedure
                cur.callproc('sp_get_activity_stats', [project_id, days])

                # Fetch results
                results = cur.fetchall()

                stats = []
                for row in results:
                    stat = {
                        "activity_category": row[0],
                        "severity_level": row[1],
                        "activity_count": row[2],
                        "unique_users": row[3]
                    }
                    stats.append(stat)

                return stats

        except Exception as e:
            logger.error(f"Failed to get activity stats: {str(e)}")
            return []

    @staticmethod
    def log_user_login(user_id: str, project_id: Optional[str] = None, ip_address: Optional[str] = None,
                       user_agent: Optional[str] = None) -> bool:
        """Log user login activity"""
        return ActivityLogger.log_activity(
            user_id=user_id,
            activity_type=ActivityType.USER_LOGIN.value,
            details={"action": "login", "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")},
            project_id=project_id,
            ip_address=ip_address,
            user_agent=user_agent
        )

    @staticmethod
    def log_user_logout(user_id: str, project_id: Optional[str] = None, ip_address: Optional[str] = None) -> bool:
        """Log user logout activity"""
        return ActivityLogger.log_activity(
            user_id=user_id,
            activity_type=ActivityType.USER_LOGOUT.value,
            details={"action": "logout", "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")},
            project_id=project_id,
            ip_address=ip_address
        )

    @staticmethod
    def log_user_registration(user_id: str, project_id: Optional[str] = None, ip_address: Optional[str] = None) -> bool:
        """Log user registration activity"""
        return ActivityLogger.log_activity(
            user_id=user_id,
            activity_type=ActivityType.USER_REGISTRATION.value,
            details={"action": "registration", "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")},
            project_id=project_id,
            ip_address=ip_address
        )

    @staticmethod
    def log_admin_action(user_id: str, action: str, details: Dict[str, Any], project_id: Optional[str] = None,
                         target_user_id: Optional[str] = None) -> bool:
        """Log administrative actions"""
        return ActivityLogger.log_activity(
            user_id=user_id,
            activity_type=ActivityType.ADMIN_ACTION.value,
            details={"action": action, "details": details, "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")},
            project_id=project_id,
            target_user_id=target_user_id
        )

    # ========== Comprehensive Activity Logging Methods ==========
    # One-liner methods for all ActivityType events

    @staticmethod
    def log_user_update(user_id: str, target_user_id: str, changes: Dict[str, Any], **kwargs) -> bool:
        """Log user profile update"""
        return ActivityLogger.log_activity(
            user_id=user_id,
            activity_type=ActivityType.USER_UPDATE.value,
            details={"changes": changes},
            target_user_id=target_user_id,
            **ActivityLogger._get_request_context(),
            **kwargs
        )

    @staticmethod
    def log_user_status_change(user_id: str, target_user_id: str, new_status: str, **kwargs) -> bool:
        """Log user status change"""
        return ActivityLogger.log_activity(
            user_id=user_id,
            activity_type=ActivityType.USER_STATUS_CHANGE.value,
            details={"new_status": new_status},
            target_user_id=target_user_id,
            **ActivityLogger._get_request_context(),
            **kwargs
        )

    @staticmethod
    def log_user_password_reset(user_id: str, target_user_id: str, **kwargs) -> bool:
        """Log password reset"""
        return ActivityLogger.log_activity(
            user_id=user_id,
            activity_type=ActivityType.USER_PASSWORD_RESET.value,
            details="Password reset",
            target_user_id=target_user_id,
            **ActivityLogger._get_request_context(),
            **kwargs
        )

    @staticmethod
    def log_user_type_changed(user_id: str, target_user_id: str, old_type: str, new_type: str, **kwargs) -> bool:
        """Log user type change"""
        return ActivityLogger.log_activity(
            user_id=user_id,
            activity_type=ActivityType.USER_TYPE_CHANGED.value,
            details={"old_type": old_type, "new_type": new_type},
            target_user_id=target_user_id,
            **ActivityLogger._get_request_context(),
            **kwargs
        )

    @staticmethod
    def log_project_creation(user_id: str, project_id: str, project_name: str, **kwargs) -> bool:
        """Log project creation"""
        return ActivityLogger.log_activity(
            user_id=user_id,
            activity_type=ActivityType.PROJECT_CREATION.value,
            details={"project_name": project_name},
            project_id=project_id,
            **ActivityLogger._get_request_context(),
            **kwargs
        )

    @staticmethod
    def log_project_update(user_id: str, project_id: str, changes: Dict[str, Any], **kwargs) -> bool:
        """Log project update"""
        return ActivityLogger.log_activity(
            user_id=user_id,
            activity_type=ActivityType.PROJECT_UPDATE.value,
            details={"changes": changes},
            project_id=project_id,
            **ActivityLogger._get_request_context(),
            **kwargs
        )

    @staticmethod
    def log_project_delete(user_id: str, project_id: str, project_name: str, **kwargs) -> bool:
        """Log project deletion"""
        return ActivityLogger.log_activity(
            user_id=user_id,
            activity_type=ActivityType.PROJECT_DELETE.value,
            details={"project_name": project_name},
            project_id=project_id,
            **ActivityLogger._get_request_context(),
            **kwargs
        )

    @staticmethod
    def log_project_member_add(user_id: str, project_id: str, target_user_id: str, **kwargs) -> bool:
        """Log adding member to project"""
        return ActivityLogger.log_activity(
            user_id=user_id,
            activity_type=ActivityType.PROJECT_MEMBER_ADD.value,
            details="Added member to project",
            project_id=project_id,
            target_user_id=target_user_id,
            **ActivityLogger._get_request_context(),
            **kwargs
        )

    @staticmethod
    def log_project_member_remove(user_id: str, project_id: str, target_user_id: str, **kwargs) -> bool:
        """Log removing member from project"""
        return ActivityLogger.log_activity(
            user_id=user_id,
            activity_type=ActivityType.PROJECT_MEMBER_REMOVE.value,
            details="Removed member from project",
            project_id=project_id,
            target_user_id=target_user_id,
            **ActivityLogger._get_request_context(),
            **kwargs
        )

    @staticmethod
    def log_project_member_removed(user_id: str, project_id: str, target_user_id: str, **kwargs) -> bool:
        """Log member removed from project (alternative)"""
        return ActivityLogger.log_activity(
            user_id=user_id,
            activity_type=ActivityType.PROJECT_MEMBER_REMOVED.value,
            details="Member removed from project",
            project_id=project_id,
            target_user_id=target_user_id,
            **ActivityLogger._get_request_context(),
            **kwargs
        )

    @staticmethod
    def log_project_ownership_transferred(user_id: str, project_id: str, target_user_id: str, **kwargs) -> bool:
        """Log project ownership transfer"""
        return ActivityLogger.log_activity(
            user_id=user_id,
            activity_type=ActivityType.PROJECT_OWNERSHIP_TRANSFERRED.value,
            details="Project ownership transferred",
            project_id=project_id,
            target_user_id=target_user_id,
            **ActivityLogger._get_request_context(),
            **kwargs
        )

    @staticmethod
    def log_project_archived(user_id: str, project_id: str, **kwargs) -> bool:
        """Log project archival"""
        return ActivityLogger.log_activity(
            user_id=user_id,
            activity_type=ActivityType.PROJECT_ARCHIVED.value,
            details="Project archived",
            project_id=project_id,
            **ActivityLogger._get_request_context(),
            **kwargs
        )

    @staticmethod
    def log_project_unarchived(user_id: str, project_id: str, **kwargs) -> bool:
        """Log project unarchival"""
        return ActivityLogger.log_activity(
            user_id=user_id,
            activity_type=ActivityType.PROJECT_UNARCHIVED.value,
            details="Project unarchived",
            project_id=project_id,
            **ActivityLogger._get_request_context(),
            **kwargs
        )

    @staticmethod
    def log_group_creation(user_id: str, user_group_id: str, group_name: str, **kwargs) -> bool:
        """Log user group creation"""
        return ActivityLogger.log_activity(
            user_id=user_id,
            activity_type=ActivityType.GROUP_CREATION.value,
            details={"group_name": group_name},
            user_group_id=user_group_id,
            **ActivityLogger._get_request_context(),
            **kwargs
        )

    @staticmethod
    def log_group_update(user_id: str, user_group_id: str, changes: Dict[str, Any], **kwargs) -> bool:
        """Log user group update"""
        return ActivityLogger.log_activity(
            user_id=user_id,
            activity_type=ActivityType.GROUP_UPDATE.value,
            details={"changes": changes},
            user_group_id=user_group_id,
            **ActivityLogger._get_request_context(),
            **kwargs
        )

    @staticmethod
    def log_group_delete(user_id: str, user_group_id: str, group_name: str, **kwargs) -> bool:
        """Log user group deletion"""
        return ActivityLogger.log_activity(
            user_id=user_id,
            activity_type=ActivityType.GROUP_DELETE.value,
            details={"group_name": group_name},
            user_group_id=user_group_id,
            **ActivityLogger._get_request_context(),
            **kwargs
        )

    @staticmethod
    def log_user_group_assign(user_id: str, target_user_id: str, user_group_id: str, **kwargs) -> bool:
        """Log user assignment to group"""
        return ActivityLogger.log_activity(
            user_id=user_id,
            activity_type=ActivityType.USER_GROUP_ASSIGN.value,
            details="User assigned to group",
            user_group_id=user_group_id,
            target_user_id=target_user_id,
            **ActivityLogger._get_request_context(),
            **kwargs
        )

    @staticmethod
    def log_user_group_remove(user_id: str, target_user_id: str, user_group_id: str, **kwargs) -> bool:
        """Log user removal from group"""
        return ActivityLogger.log_activity(
            user_id=user_id,
            activity_type=ActivityType.USER_GROUP_REMOVE.value,
            details="User removed from group",
            user_group_id=user_group_id,
            target_user_id=target_user_id,
            **ActivityLogger._get_request_context(),
            **kwargs
        )

    @staticmethod
    def log_permission_grant(user_id: str, target_user_id: str, permission: str, project_id: Optional[str] = None, **kwargs) -> bool:
        """Log permission grant"""
        return ActivityLogger.log_activity(
            user_id=user_id,
            activity_type=ActivityType.PERMISSION_GRANT.value,
            details={"permission": permission},
            project_id=project_id,
            target_user_id=target_user_id,
            **ActivityLogger._get_request_context(),
            **kwargs
        )

    @staticmethod
    def log_permission_revoke(user_id: str, target_user_id: str, permission: str, project_id: Optional[str] = None, **kwargs) -> bool:
        """Log permission revocation"""
        return ActivityLogger.log_activity(
            user_id=user_id,
            activity_type=ActivityType.PERMISSION_REVOKE.value,
            details={"permission": permission},
            project_id=project_id,
            target_user_id=target_user_id,
            **ActivityLogger._get_request_context(),
            **kwargs
        )

    @staticmethod
    def log_role_removed(user_id: str, target_user_id: str, role: str, project_id: Optional[str] = None, **kwargs) -> bool:
        """Log role removal"""
        return ActivityLogger.log_activity(
            user_id=user_id,
            activity_type=ActivityType.ROLE_REMOVED.value,
            details={"role": role},
            project_id=project_id,
            target_user_id=target_user_id,
            **ActivityLogger._get_request_context(),
            **kwargs
        )

    @staticmethod
    def log_bulk_role_assignment(user_id: str, count: int, project_id: Optional[str] = None, **kwargs) -> bool:
        """Log bulk role assignment"""
        return ActivityLogger.log_activity(
            user_id=user_id,
            activity_type=ActivityType.BULK_ROLE_ASSIGNMENT.value,
            details={"count": count},
            project_id=project_id,
            **ActivityLogger._get_request_context(),
            **kwargs
        )

    @staticmethod
    def log_bulk_group_assignment(user_id: str, count: int, user_group_id: Optional[str] = None, **kwargs) -> bool:
        """Log bulk group assignment"""
        return ActivityLogger.log_activity(
            user_id=user_id,
            activity_type=ActivityType.BULK_GROUP_ASSIGNMENT.value,
            details={"count": count},
            user_group_id=user_group_id,
            **ActivityLogger._get_request_context(),
            **kwargs
        )

    @staticmethod
    def log_bulk_user_update(user_id: str, count: int, **kwargs) -> bool:
        """Log bulk user update"""
        return ActivityLogger.log_activity(
            user_id=user_id,
            activity_type=ActivityType.BULK_USER_UPDATE.value,
            details={"count": count},
            **ActivityLogger._get_request_context(),
            **kwargs
        )

    @staticmethod
    def log_bulk_user_delete(user_id: str, count: int, **kwargs) -> bool:
        """Log bulk user deletion"""
        return ActivityLogger.log_activity(
            user_id=user_id,
            activity_type=ActivityType.BULK_USER_DELETE.value,
            details={"count": count},
            **ActivityLogger._get_request_context(),
            **kwargs
        )

    @staticmethod
    def log_system_event(event: str, details: Union[Dict[str, Any], str], **kwargs) -> bool:
        """Log system event"""
        return ActivityLogger.log_activity(
            user_id=None,
            activity_type=ActivityType.SYSTEM_EVENT.value,
            details={"event": event, "details": details} if isinstance(details, str) else details,
            **kwargs
        )

    @staticmethod
    def log_patreon_activity(
            activity_type: Union[ActivityType, str],
            details: Union[Dict[str, Any], str],
            user_id: Optional[str] = None,
            **kwargs
    ) -> bool:
        """Log a Patreon activity using only the seeded act-cat-075..090 values."""
        value = activity_type.value if isinstance(activity_type, ActivityType) else str(activity_type)
        if not is_patreon_activity_type(value):
            raise ValueError(f"Unknown Patreon activity type: {value}")

        return ActivityLogger.log_activity(
            user_id=user_id,
            activity_type=value,
            details=sanitize_patreon_activity_details(details),
            **ActivityLogger._get_request_context(),
            **kwargs,
        )

    @staticmethod
    def log_billing_activity(
            activity_type: Union[ActivityType, str],
            details: Union[Dict[str, Any], str],
            user_id: Optional[str] = None,
            **kwargs
    ) -> bool:
        """Log a billing/Stripe activity using only seeded act-cat-091..106 values."""
        value = activity_type.value if isinstance(activity_type, ActivityType) else str(activity_type)
        if not is_billing_activity_type(value):
            raise ValueError(f"Unknown billing activity type: {value}")

        return ActivityLogger.log_activity(
            user_id=user_id,
            activity_type=value,
            details=sanitize_billing_activity_details(details),
            **ActivityLogger._get_request_context(),
            **kwargs,
        )

    # ========== Context Management ==========

    @staticmethod
    def _get_request_context() -> Dict[str, Any]:
        """Get current request context (IP, user agent)"""
        return _request_context.get()

    @staticmethod
    def set_request_context(ip_address: Optional[str] = None, user_agent: Optional[str] = None):
        """Set request context for current request"""
        context = {}
        if ip_address:
            context['ip_address'] = ip_address
        if user_agent:
            context['user_agent'] = user_agent
        _request_context.set(context)

    @staticmethod
    def clear_request_context():
        """Clear request context"""
        _request_context.set({})


# Global activity logger instance
activity_logger = ActivityLogger()


# Convenience functions
def log_activity(user_id: Optional[str], activity_type: str, details: Union[Dict[str, Any], str], **kwargs) -> bool:
    """Convenience function for logging activities"""
    return activity_logger.log_activity(user_id, activity_type, details, **kwargs)


def log_billing_activity(
        activity_type: Union[ActivityType, str],
        details: Union[Dict[str, Any], str],
        user_id: Optional[str] = None,
        **kwargs
) -> bool:
    """Convenience function for logging redacted billing/Stripe activities."""
    return activity_logger.log_billing_activity(activity_type, details, user_id=user_id, **kwargs)


def log_patreon_activity(activity_type: Union[ActivityType, str], details: Union[Dict[str, Any], str], **kwargs) -> bool:
    """Convenience function for logging redacted Patreon activities."""
    return activity_logger.log_patreon_activity(activity_type, details, **kwargs)


def get_recent_activity(limit: int = 50, **kwargs) -> List[Dict[str, Any]]:
    """Convenience function for getting recent activities"""
    return activity_logger.get_recent_activity(limit, **kwargs)


def count_activity_logs(**kwargs) -> int:
    """Convenience function for counting activity logs"""
    return activity_logger.count_activity_logs(**kwargs)


def get_activity_by_id(activity_id: str) -> Optional[Dict[str, Any]]:
    """Convenience function for getting a single activity by ID"""
    return activity_logger.get_activity_by_id(activity_id)


def get_activity_catalog(category: Optional[str] = None) -> List[Dict[str, Any]]:
    """Convenience function for getting activity catalog"""
    return activity_logger.get_activity_catalog(category)


def get_activity_by_code(activity_code: str) -> Optional[Dict[str, Any]]:
    """Convenience function for getting activity by code"""
    return activity_logger.get_activity_by_code(activity_code)


def get_activity_stats(project_id: Optional[str] = None, days: int = 30) -> List[Dict[str, Any]]:
    """Convenience function for getting activity statistics"""
    return activity_logger.get_activity_stats(project_id, days)


def get_recent_security_events(p_hours: int = 24, p_limit: int = 100) -> List[Dict[str, Any]]:
    """Convenience function for getting recent security events from activity_logs"""
    try:
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc('sp_get_recent_security_events', [p_hours, p_limit])

            columns = [
                'id', 'user_id', 'activity_type', 'details', 'ip_address',
                'severity_level', 'created_at', 'username', 'activity_name',
                'activity_description',
            ]

            results = cur.fetchall()
            events = []
            for row in results:
                event = {}
                for i, col in enumerate(columns):
                    event[col] = row[i] if i < len(row) else None
                events.append(event)

            return events

    except Exception as e:
        logger.error(f"Failed to get recent security events: {str(e)}")
        return []


# ========== Context Manager for Auto-Logging ==========

class LogActivity:
    """
    Context manager for automatic activity logging
    
    Usage:
        with LogActivity(user_id, ActivityType.USER_UPDATE, target_user_id=target_id) as log:
            # Perform operation
            result = update_user(data)
            # Add details to log
            log.add_details({"updated_fields": ["email", "name"]})
    """
    
    def __init__(self, user_id: str, activity_type: ActivityType, 
                 auto_log: bool = True, **kwargs):
        self.user_id = user_id
        self.activity_type = activity_type
        self.auto_log = auto_log
        self.kwargs = kwargs
        self.details = {}
        self.logged = False
        
    def add_details(self, details: Union[Dict[str, Any], str]):
        """Add details to the log"""
        if isinstance(details, dict):
            self.details.update(details)
        else:
            self.details['info'] = details
            
    def __enter__(self):
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.auto_log and not self.logged and exc_type is None:
            self.log()
        return False
        
    def log(self):
        """Manually trigger logging"""
        if not self.logged:
            ActivityLogger.log_activity(
                user_id=self.user_id,
                activity_type=self.activity_type.value,
                details=self.details if self.details else "Operation completed",
                **ActivityLogger._get_request_context(),
                **self.kwargs
            )
            self.logged = True


# ========== Decorator for Endpoint Auto-Logging ==========

def log_endpoint_activity(activity_type: ActivityType, 
                          extract_details: Optional[Callable] = None):
    """
    Decorator for automatic endpoint activity logging
    
    Args:
        activity_type: Type of activity to log
        extract_details: Optional function to extract details from args/kwargs
        
    Usage:
        @log_endpoint_activity(ActivityType.USER_UPDATE)
        async def update_user_endpoint(user_hash: str, data: dict, current_user=Depends(...)):
            # Your endpoint logic
            return result
            
        @log_endpoint_activity(
            ActivityType.PROJECT_CREATION,
            extract_details=lambda *args, **kwargs: {"project": kwargs.get("project_name")}
        )
        async def create_project_endpoint(project_name: str, current_user=Depends(...)):
            # Your endpoint logic
            return result
    """
    def decorator(func: Callable):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            # Extract user_id from kwargs (assumes FastAPI dependency injection)
            current_user = kwargs.get('current_user') or kwargs.get('credentials')
            user_id = None
            
            if current_user:
                # Handle different user object types
                if isinstance(current_user, dict):
                    user_id = current_user.get('user_id') or current_user.get('id')
                elif hasattr(current_user, 'id'):
                    user_id = current_user.id
                elif hasattr(current_user, 'user_id'):
                    user_id = current_user.user_id
            
            # Execute the function
            try:
                result = await func(*args, **kwargs)
                
                # Extract details if function provided
                details = {}
                if extract_details:
                    try:
                        details = extract_details(*args, **kwargs)
                    except Exception as e:
                        logger.warning(f"Failed to extract details for logging: {e}")
                        details = {"error": "Failed to extract details"}
                
                # Log the activity
                if user_id:
                    ActivityLogger.log_activity(
                        user_id=user_id,
                        activity_type=activity_type.value,
                        details=details if details else "Endpoint executed successfully",
                        **ActivityLogger._get_request_context()
                    )
                
                return result
                
            except Exception as e:
                # Log failed attempts too
                if user_id:
                    ActivityLogger.log_activity(
                        user_id=user_id,
                        activity_type=activity_type.value,
                        details={"error": str(e), "status": "failed"},
                        **ActivityLogger._get_request_context()
                    )
                raise
                
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            # For synchronous functions
            current_user = kwargs.get('current_user') or kwargs.get('credentials')
            user_id = None
            
            if current_user:
                if isinstance(current_user, dict):
                    user_id = current_user.get('user_id') or current_user.get('id')
                elif hasattr(current_user, 'id'):
                    user_id = current_user.id
                elif hasattr(current_user, 'user_id'):
                    user_id = current_user.user_id
            
            try:
                result = func(*args, **kwargs)
                
                details = {}
                if extract_details:
                    try:
                        details = extract_details(*args, **kwargs)
                    except Exception as e:
                        logger.warning(f"Failed to extract details for logging: {e}")
                        details = {"error": "Failed to extract details"}
                
                if user_id:
                    ActivityLogger.log_activity(
                        user_id=user_id,
                        activity_type=activity_type.value,
                        details=details if details else "Operation completed successfully",
                        **ActivityLogger._get_request_context()
                    )
                
                return result
                
            except Exception as e:
                if user_id:
                    ActivityLogger.log_activity(
                        user_id=user_id,
                        activity_type=activity_type.value,
                        details={"error": str(e), "status": "failed"},
                        **ActivityLogger._get_request_context()
                    )
                raise
        
        # Return appropriate wrapper based on function type
        import inspect
        if inspect.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
            
    return decorator


# ========== Request Context Helpers ==========

def set_request_context(ip_address: Optional[str] = None, user_agent: Optional[str] = None):
    """Set request context - call this in middleware or at request start"""
    ActivityLogger.set_request_context(ip_address, user_agent)


def clear_request_context():
    """Clear request context - call this at request end"""
    ActivityLogger.clear_request_context()
