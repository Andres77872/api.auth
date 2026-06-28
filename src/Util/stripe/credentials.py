"""Validate that a billing group's Stripe credentials are correct before they're trusted.

Set/rotate used to store credentials blind; this confirms them first:
  1. offline format checks (key/secret/portal-id prefixes),
  2. a LIVE auth probe — the secret key must authenticate against Stripe,
  3. when a portal configuration id is supplied, that it exists and meets the MVP restricted-portal
     contract.

Fail-closed: if Stripe can't be reached (network / 5xx / unknown) we reject rather than store an
unverified key. Errors never leak key material — all messages are generic and the Stripe client redacts
provider error text.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

from src.Util.billing.config import load_billing_config
from src.Util.billing.security import hmac_provider_ref, provider_ref_fingerprint
from src.Util.error_handler import ErrorCode, ValidationError
from src.Util.stripe.client import StripeAPIError, StripeBillingClient
from src.Util.stripe.config import load_stripe_config
from src.Util.stripe.portal import StripePortalConfigurationError, validate_restricted_portal_configuration


logger = logging.getLogger(__name__)

_PROVIDER = "stripe"
_SECRET_PREFIXES = ("sk_", "rk_")
_WEBHOOK_PREFIX = "whsec_"
_PORTAL_PREFIX = "bpc_"

ClientFactory = Callable[[str], StripeBillingClient]


@dataclass(frozen=True)
class CredentialValidationResult:
    valid: bool
    secret_key_valid: bool = False
    portal_configuration_valid: bool | None = None
    livemode: bool | None = None
    account_fingerprint: str | None = None
    message: str | None = None


def _default_client_factory(secret_key: str) -> StripeBillingClient:
    return StripeBillingClient(secret_key=secret_key, api_version=load_stripe_config().api_version)


def _require_prefix(value: str | None, prefixes: tuple[str, ...] | str, *, field: str, required: bool) -> None:
    text = (value or "").strip()
    if not text:
        if required:
            raise ValidationError(message=f"{field} is required", error_code=ErrorCode.INVALID_INPUT)
        return
    options = (prefixes,) if isinstance(prefixes, str) else tuple(prefixes)
    if not any(text.startswith(prefix) for prefix in options):
        # Never echo the value — only say the format is wrong.
        raise ValidationError(message=f"{field} has an unexpected format", error_code=ErrorCode.INVALID_INPUT)


def _account_fingerprint(account_id: str) -> str | None:
    if not account_id:
        return None
    try:
        hmac_secret = load_billing_config().id_hmac_secret
        if not hmac_secret:
            return None
        digest = hmac_provider_ref(provider=_PROVIDER, kind="account_id", raw_id=account_id, secret=hmac_secret)
        return provider_ref_fingerprint(digest=digest)
    except Exception:
        return None


def validate_stripe_credentials(body: Any, *, client_factory: ClientFactory | None = None) -> CredentialValidationResult:
    """Validate Stripe credentials (format + live auth probe + portal config). Fail-closed.

    ``body`` is a ``StripeAccountCredentialsUpdate`` (``secret_key`` plus optional ``webhook_secret`` /
    ``portal_configuration_id``). Raises ``ValidationError`` (never leaking the key) when invalid; returns
    a ``CredentialValidationResult`` on success.
    """
    secret_key = (getattr(body, "secret_key", None) or "").strip()
    webhook_secret = (getattr(body, "webhook_secret", None) or "").strip() or None
    portal_configuration_id = (getattr(body, "portal_configuration_id", None) or "").strip() or None

    # 1) Offline format checks.
    _require_prefix(secret_key, _SECRET_PREFIXES, field="Stripe secret key", required=True)
    _require_prefix(webhook_secret, _WEBHOOK_PREFIX, field="Stripe webhook secret", required=False)
    _require_prefix(portal_configuration_id, _PORTAL_PREFIX, field="Stripe portal configuration id", required=False)

    factory = client_factory or _default_client_factory
    client = factory(secret_key)

    # 2) Live auth probe — the secret key must authenticate against Stripe.
    try:
        account = client.retrieve_account()
    except StripeAPIError as exc:
        if exc.status_code in (401, 403):
            raise ValidationError(
                message="Stripe secret key is invalid or lacks required access",
                error_code=ErrorCode.INVALID_INPUT,
            ) from exc
        # Fail-closed: any other status / network / unknown — we can't confirm, so reject.
        logger.warning("Stripe credential validation could not reach Stripe: %s", type(exc).__name__)
        raise ValidationError(
            message="Unable to validate Stripe credentials against Stripe; please try again",
            error_code=ErrorCode.INVALID_INPUT,
        ) from exc

    account_map = account if isinstance(account, dict) else {}
    livemode = bool(account_map["livemode"]) if account_map.get("livemode") is not None else None
    account_fingerprint = _account_fingerprint(str(account_map.get("id") or ""))

    # 3) Portal configuration (optional) — must exist and meet the MVP restricted contract.
    portal_valid: bool | None = None
    if portal_configuration_id:
        try:
            configuration = client.retrieve_portal_configuration(portal_configuration_id)
        except StripeAPIError as exc:
            raise ValidationError(
                message="Stripe portal configuration not found or inaccessible",
                error_code=ErrorCode.STRIPE_PORTAL_CONFIGURATION_INVALID,
            ) from exc
        try:
            validate_restricted_portal_configuration(configuration)
        except StripePortalConfigurationError as exc:
            raise ValidationError(
                message="Stripe portal configuration does not meet the required restricted-portal contract",
                error_code=ErrorCode.STRIPE_PORTAL_CONFIGURATION_INVALID,
            ) from exc
        portal_valid = True

    return CredentialValidationResult(
        valid=True,
        secret_key_valid=True,
        portal_configuration_valid=portal_valid,
        livemode=livemode,
        account_fingerprint=account_fingerprint,
        message="Stripe credentials validated",
    )


__all__ = [
    "ClientFactory",
    "CredentialValidationResult",
    "validate_stripe_credentials",
]
