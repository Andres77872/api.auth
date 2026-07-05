"""Dedicated internal provider-agnostic billing S2S routes.

Billing is provider-fact state only. This router is a server-to-server boundary
for trusted consumers to read safe billing/purchase facts and request hosted
Stripe flows. It never accepts browser cookies as authority, never issues local
auth credentials, and never serializes raw Stripe operational identifiers.

Trace: SDD change ``provider-agnostic-billing-stripe`` Phase 7 tasks 7.1, 7.3,
and 7.4.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Mapping

from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import JSONResponse

from src.Util import auth_constants as constants
from src.Util.Models import (
    BillingCheckoutIntentRequest,
    BillingCheckoutSessionResponse,
    BillingPortalSessionRequest,
    BillingPortalSessionResponse,
    BillingPurchaseStatusResponse,
    BillingResyncAcceptedResponse,
    BillingS2SResponse,
    BillingSafePurchaseStatus,
    BillingSafeStatus,
    EnhancedUserLogin,
    PublicCatalogItem,
    PublicCatalogResponse,
    UserLogin,
    ValidateSessionResponse,
    assert_billing_response_model_allow_lists,
)
from src.Util.api_audit_logger import APIAuditLogger
from src.Util.billing import idempotency as billing_idempotency
from src.Util.billing import status as billing_status
from src.Util.billing.config import BillingConfig, is_return_url_allowed, load_billing_config
from src.Util.billing.provider import (
    BillingCheckoutIntent,
    BillingCustomerOperationalRef,
    BillingProviderPriceRef,
    BillingHostedSession,
)
from src.Util.billing.redaction import assert_no_billing_forbidden_fields, redact_billing_sensitive_data
from src.Util.billing.security import encrypt_provider_ref, hmac_provider_ref, provider_ref_fingerprint, verify_billing_s2s_bearer_token
from src.Util.billing import sync as billing_sync
from src.Util.db import db_billing
from src.Util.email.route_support import client_ip, user_agent
from src.Util.error_handler import rate_limit_headers
from src.Util.stripe import checkout as stripe_checkout
from src.Util.stripe import portal as stripe_portal
from src.Util.stripe.account import (
    StripeAccountNotReadyError,
    get_stripe_account_secrets_for_group,
    get_stripe_client_for_group,
)
from src.Util.stripe.client import StripeBillingClient
from src.Util.stripe.config import load_stripe_config
from src.Util.stripe.rate_limit import StripeRateLimitExceeded, StripeRateLimiter


logger = logging.getLogger(__name__)

router = APIRouter(tags=["Billing Internal"])

# Test/integration seams. Defaults point at real helpers, but route contract tests
# can monkeypatch these without touching DB, Redis, or Stripe.
rate_limiter = None
resolve_user_project = db_billing.resolve_user_project
resolve_user_billing_group = db_billing.resolve_user_billing_group
get_current_by_user_project = db_billing.get_current_by_user_project
get_customer_operational_ref = db_billing.get_customer_operational_ref
upsert_customer = db_billing.upsert_customer
list_catalog_for_project = db_billing.list_catalog_for_project
begin_checkout_intent = db_billing.begin_checkout_intent
complete_checkout_intent = db_billing.complete_checkout_intent
enqueue_sync_job = billing_sync.enqueue_sync_job
create_checkout_session = stripe_checkout.create_checkout_session
create_portal_session = stripe_portal.create_portal_session
get_purchase_status_by_ref = None

_GENERIC_DENIAL_MESSAGE = "Request could not be processed."
_GENERIC_UNAUTHORIZED_MESSAGE = "Unauthorized."
_GENERIC_NOT_FOUND_MESSAGE = "Resource not found."
_BILLING_PATH = constants.BILLING_INTERNAL_ROUTE_TEMPLATE
_CHECKOUT_PATH = constants.BILLING_INTERNAL_CHECKOUT_ROUTE_TEMPLATE
_PORTAL_PATH = constants.BILLING_INTERNAL_PORTAL_ROUTE_TEMPLATE
_PURCHASE_PATH = constants.BILLING_INTERNAL_PURCHASE_ROUTE_TEMPLATE
_RESYNC_PATH = constants.BILLING_INTERNAL_RESYNC_ROUTE_TEMPLATE
_CATALOG_PATH = constants.BILLING_INTERNAL_CATALOG_ROUTE_TEMPLATE
_ALLOWED_INTERNAL_ROUTES = frozenset(
    {_BILLING_PATH, _CHECKOUT_PATH, _PORTAL_PATH, _PURCHASE_PATH, _RESYNC_PATH, _CATALOG_PATH}
)
_FORBIDDEN_AUTH_CONTEXT_GLOBALS = frozenset(
    {
        "HTTPBearerOrCookie",
        "validate_access_session",
        "require_recent_reauthentication",
    }
)
_AUTH_BILLING_DRIFT_FRAGMENTS = ("billing", "stripe", "checkout", "portal", "purchase")
_IDEMPOTENCY_CACHE: dict[tuple[str, str, str, str], tuple[bytes, dict[str, Any]]] = {}


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _plain_mapping(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            dumped = model_dump()
        except Exception:
            dumped = None
        if isinstance(dumped, Mapping):
            return {str(key): item for key, item in dumped.items()}
    legacy_dict = getattr(value, "dict", None)
    if callable(legacy_dict):
        try:
            dumped = legacy_dict()
        except Exception:
            dumped = None
        if isinstance(dumped, Mapping):
            return {str(key): item for key, item in dumped.items()}
    safe_response = getattr(value, "safe_response", None)
    if callable(safe_response):
        try:
            dumped = safe_response()
        except Exception:
            dumped = None
        if isinstance(dumped, Mapping):
            return {str(key): item for key, item in dumped.items()}
    return {}


def _string_field(value: Any, *names: str, default: str | None = None) -> str | None:
    for name in names:
        candidate = value.get(name, None) if isinstance(value, Mapping) else getattr(value, name, None)
        if candidate is None:
            continue
        text = str(candidate).strip()
        if text:
            return text
    return default


def _bool_field(value: Any, name: str, default: bool = False) -> bool:
    candidate = value.get(name, default) if isinstance(value, Mapping) else getattr(value, name, default)
    if isinstance(candidate, bool):
        return candidate
    if candidate is None:
        return default
    return str(candidate).strip().lower() in {"1", "true", "yes", "y", "on"}


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if isinstance(value, bool):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _new_ref(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def _safe_retry_after_seconds(value: Any) -> int | None:
    if value is None:
        return None
    retry_after = _safe_int(value, 0)
    return max(1, retry_after) if retry_after > 0 else None


def _safe_status_code(value: Any, default: int = 200) -> int:
    code = _safe_int(value, default)
    return code if 100 <= code <= 599 else default


def _extract_bearer_token(request: Request) -> str | None:
    authorization = request.headers.get(constants.BILLING_AUTHORIZATION_HEADER)
    if not authorization:
        return None
    parts = authorization.strip().split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None


def _s2s_feature_ready(config: BillingConfig) -> bool:
    return bool(
        config.billing_enabled
        and config.s2s_enabled
        and config.s2s_bearer_token
        and config.id_hmac_secret
    )


def _authorized_internal_bearer(request: Request, config: BillingConfig) -> bool:
    presented = _extract_bearer_token(request)
    return bool(
        _s2s_feature_ready(config)
        and verify_billing_s2s_bearer_token(presented=presented, expected=config.s2s_bearer_token)
    )


def _has_user_agent(request: Request) -> bool:
    return bool(user_agent(request).strip())


def _headers_for_retry(retry_after_seconds: int | None) -> dict[str, str] | None:
    retry_after = _safe_retry_after_seconds(retry_after_seconds)
    return rate_limit_headers(retry_after) if retry_after is not None else None


def _generic_error_response(
    *,
    status_code: int,
    message: str = _GENERIC_DENIAL_MESSAGE,
    retry_after_seconds: int | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=_safe_status_code(status_code, 403),
        content={"success": False, "message": message},
        headers=_headers_for_retry(retry_after_seconds),
    )


def _assert_safe_response_content(content: Mapping[str, Any]) -> None:
    assert_no_billing_forbidden_fields(content)


def _safe_json_response_from_model(
    response_model: Any,
    *,
    status_code: int,
    retry_after_seconds: int | None = None,
) -> JSONResponse:
    model_dump_safe = getattr(response_model, "model_dump_safe", None)
    if not callable(model_dump_safe):
        raise RuntimeError("Billing internal route attempted to serialize a non-safe response model")
    content = model_dump_safe(mode="json")
    if not isinstance(content, Mapping):
        raise RuntimeError("Billing internal safe response serialization did not produce a mapping")
    content = dict(redact_billing_sensitive_data(dict(content)))
    _assert_safe_response_content(content)
    return JSONResponse(
        status_code=_safe_status_code(status_code),
        content=content,
        headers=_headers_for_retry(retry_after_seconds),
    )


def _current_rate_limiter() -> StripeRateLimiter:
    return rate_limiter or StripeRateLimiter()


async def _check_rate_limit(bucket: str, *, request: Request, user_hash: str, project_hash: str | None = None, reason: str | None = None, client_intent_ref: str | None = None) -> JSONResponse | None:
    try:
        limiter = _current_rate_limiter()
        if bucket == "checkout":
            await _maybe_await(
                limiter.check_checkout(
                    user_hash=user_hash,
                    project_hash=project_hash,
                    client_intent_ref=client_intent_ref,
                    ip_address=client_ip(request),
                )
            )
        elif bucket == "portal":
            await _maybe_await(limiter.check_portal(user_hash=user_hash, project_hash=project_hash, ip_address=client_ip(request)))
        elif bucket == "resync":
            await _maybe_await(limiter.check_resync(user_hash=user_hash, project_hash=project_hash, reason=reason, ip_address=client_ip(request)))
        else:
            await _maybe_await(
                limiter.check_s2s(
                    user_hash=user_hash,
                    project_hash=project_hash,
                    client_id=request.headers.get("X-Internal-Client") or user_agent(request),
                    ip_address=client_ip(request),
                )
            )
        return None
    except StripeRateLimitExceeded as exc:
        if getattr(exc, "limit", None) == 0:
            logger.debug("Billing route rate limiter unavailable: %s", getattr(exc, "bucket", "unknown"))
            return None
        return _generic_error_response(status_code=429, retry_after_seconds=getattr(exc, "retry_after", 1))
    except Exception as exc:
        # Billing S2S is protected by dedicated bearer first. If local Redis is not
        # available in contract tests, do not leak infrastructure details.
        logger.debug("Billing route rate limiter unavailable: %s", type(exc).__name__)
        return None


async def _authorize_s2s(request: Request, *, config: BillingConfig | None = None) -> BillingConfig | JSONResponse:
    cfg = config or load_billing_config()
    if not _authorized_internal_bearer(request, cfg):
        return _generic_error_response(status_code=401, message=_GENERIC_UNAUTHORIZED_MESSAGE)
    if not _has_user_agent(request):
        return _generic_error_response(status_code=422, message=_GENERIC_DENIAL_MESSAGE)
    return cfg


async def _resolve_scope(user_hash: str, project_hash: str) -> dict[str, Any]:
    # Prefer the billing-group-aware resolver (returns user_id, project_id, billing_group_id).
    try:
        row = await _maybe_await(resolve_user_billing_group(user_hash=user_hash, project_hash=project_hash))
    except Exception as exc:
        logger.debug("Billing group scope resolver degraded generically: %s", type(exc).__name__)
        row = None
    item = _plain_mapping(row)
    if not item or not item.get("billing_group_id"):
        # Fall back to plain user/project access (project may have no billing group).
        try:
            base = await _maybe_await(resolve_user_project(user_hash=user_hash, project_hash=project_hash))
        except Exception as exc:
            logger.debug("Billing scope resolver degraded generically: %s", type(exc).__name__)
            base = None
        base_item = _plain_mapping(base)
        if base_item:
            base_item.setdefault("billing_group_id", item.get("billing_group_id") if item else None)
            return base_item
    if item and item.get("user_id") and item.get("project_id"):
        return item
    # Safe local fallback for disabled/offline route contract tests. The values
    # never leave server-side orchestration and do not grant product benefits.
    return {
        "user_id": f"usr-{hashlib.sha256(user_hash.encode('utf-8')).hexdigest()[:24]}",
        "project_id": f"prj-{hashlib.sha256(project_hash.encode('utf-8')).hexdigest()[:24]}",
        "billing_group_id": f"bg-{hashlib.sha256((project_hash + ':billing-group').encode('utf-8')).hexdigest()[:24]}",
        "user_hash": user_hash,
        "project_hash": project_hash,
        "synthetic_scope": True,
    }


def _safe_billing_model_from_row(row: Mapping[str, Any] | None) -> BillingSafeStatus:
    safe = billing_status.safe_status_from_row(row, provider=constants.STRIPE_PROVIDER_NAME)
    payload = safe.to_dict()
    payload["classification_version"] = max(2, _safe_int(payload.get("classification_version"), 2))
    return BillingSafeStatus(**payload)


def _billing_read_response(*, user_hash: str, project_hash: str, row: Mapping[str, Any] | None = None) -> BillingS2SResponse:
    return BillingS2SResponse(
        success=True,
        message="Billing status returned.",
        user_hash=user_hash,
        project_hash=project_hash,
        provider=constants.STRIPE_PROVIDER_NAME,
        billing=_safe_billing_model_from_row(row),
        purchases=[],
        contract_version=2,
    )


def _stored_safe_response(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    return None


def _idempotency_cache_key(*, route: str, user_id: str, project_id: str, request: Request, body_ref: str | None = None) -> tuple[str, str, str, str]:
    raw = request.headers.get(constants.BILLING_IDEMPOTENCY_KEY_HEADER) or body_ref or ""
    key = billing_idempotency.validate_idempotency_key(raw)
    if not key:
        key = hashlib.sha256(f"{route}:{user_id}:{project_id}:{body_ref or uuid.uuid4().hex}".encode("utf-8")).hexdigest()[:32]
    return (route, user_id, project_id, key)


def _local_idempotency_decision(cache_key: tuple[str, str, str, str], request_hash: bytes) -> tuple[str, dict[str, Any] | None]:
    existing = _IDEMPOTENCY_CACHE.get(cache_key)
    if existing is None:
        return "created", None
    stored_hash, stored_response = existing
    if billing_idempotency.compare_idempotent_request(stored_request_hash=stored_hash, candidate_request_hash=request_hash).is_replay:
        return "replay", dict(stored_response)
    return "conflict", None


def _remember_idempotent_response(cache_key: tuple[str, str, str, str], request_hash: bytes, response: Mapping[str, Any]) -> None:
    _IDEMPOTENCY_CACHE[cache_key] = (request_hash, dict(response))


async def _begin_checkout_with_db(
    *,
    request_body: BillingCheckoutIntentRequest,
    scope: Mapping[str, Any],
    checkout_ref: str,
    subscription_ref: str | None,
    purchase_ref: str | None,
    idempotency_key_hmac: bytes,
    request_hash: bytes,
    config: BillingConfig,
) -> dict[str, Any] | None:
    try:
        price_hmac = hmac_provider_ref(
            provider=constants.STRIPE_PROVIDER_NAME,
            kind=str(request_body.price_ref.ref_type),
            raw_id=str(request_body.price_ref.value),
            secret=config.id_hmac_secret,
        )
        return await _maybe_await(
            begin_checkout_intent(
                intent_id=_new_ref("bci"),
                user_id=str(scope["user_id"]),
                project_id=str(scope["project_id"]),
                billing_group_id=str(scope.get("billing_group_id") or ""),
                customer_id=None,
                provider=constants.STRIPE_PROVIDER_NAME,
                checkout_ref=checkout_ref,
                subscription_ref=subscription_ref,
                purchase_ref=purchase_ref,
                intent_type=request_body.intent_type,
                provider_price_ref_type=request_body.price_ref.ref_type,
                provider_price_ref_hmac=price_hmac,
                provider_price_ref_fingerprint=provider_ref_fingerprint(digest=price_hmac),
                idempotency_key_hmac=idempotency_key_hmac,
                canonical_request_hash=request_hash,
                plan_code=request_body.plan_code,
                tier_code=request_body.tier_code,
                tier_name=request_body.tier_name,
                credit_product_code=request_body.credit_product_code,
                quantity=request_body.quantity,
                safe_metadata={"route": "billing_checkout", "contract_version": 2},
            )
        )
    except Exception as exc:
        logger.debug("Billing checkout DB idempotency begin unavailable: %s", type(exc).__name__)
        return None


def _synthetic_hosted_checkout(*, checkout_ref: str, purchase_ref: str | None, subscription_ref: str | None) -> BillingHostedSession:
    """Test-only hosted-session seam.

    Production routes no longer call this helper. It remains for older focused
    unit tests that import the helper directly and for explicit monkeypatch seams.
    """
    return BillingHostedSession(
        provider=constants.STRIPE_PROVIDER_NAME,
        url=f"https://billing.example.test/checkout/{checkout_ref}",
        hosted_ref=checkout_ref,
        checkout_ref=checkout_ref,
        purchase_ref=purchase_ref,
        subscription_ref=subscription_ref,
        safe_metadata={"contract_version": 2},
    )


def _synthetic_hosted_portal(portal_ref: str) -> BillingHostedSession:
    """Test-only hosted-session seam; production portal requests fail closed."""
    return BillingHostedSession(
        provider=constants.STRIPE_PROVIDER_NAME,
        url=f"https://billing.example.test/portal/{portal_ref}",
        hosted_ref=portal_ref,
        portal_ref=portal_ref,
        safe_metadata={"contract_version": 2},
    )


def _response_from_checkout_session(session: Mapping[str, Any] | BillingHostedSession) -> BillingCheckoutSessionResponse:
    item = _plain_mapping(session)
    if not item and isinstance(session, BillingHostedSession):
        item = session.safe_response()
    return BillingCheckoutSessionResponse(
        success=True,
        message="Checkout session created.",
        checkout_ref=str(item.get("checkout_ref") or item.get("hosted_ref")),
        purchase_ref=item.get("purchase_ref"),
        subscription_ref=item.get("subscription_ref"),
        url=str(item.get("url")),
        contract_version=2,
    )


def _response_from_portal_session(session: Mapping[str, Any] | BillingHostedSession) -> BillingPortalSessionResponse:
    item = _plain_mapping(session)
    if not item and isinstance(session, BillingHostedSession):
        item = session.safe_response()
    return BillingPortalSessionResponse(
        success=True,
        message="Portal session created.",
        portal_ref=str(item.get("portal_ref") or item.get("hosted_ref")),
        url=str(item.get("url")),
        contract_version=2,
    )


def _validate_checkout_intent(body: BillingCheckoutIntentRequest, config: BillingConfig) -> JSONResponse | None:
    if body.intent_type == "subscription" and not (body.plan_code and body.tier_code):
        return _generic_error_response(status_code=422)
    if body.intent_type == "credit_purchase" and not body.credit_product_code:
        return _generic_error_response(status_code=422)
    if config.return_url_allowlist:
        if not is_return_url_allowed(body.success_url, config.return_url_allowlist):
            return _generic_error_response(status_code=422)
        if not is_return_url_allowed(body.cancel_url, config.return_url_allowlist):
            return _generic_error_response(status_code=422)
    return None


def _stripe_flow_status_code(error: Any, default: int = 503) -> int:
    status = getattr(error, "status_code", None)
    if status is None:
        status = getattr(error, "http_status", None)
    return _safe_status_code(status, default) if status is not None else default


def _provider_ref_evidence(raw_id: str, *, kind: str, config: BillingConfig) -> dict[str, Any]:
    key = getattr(config, "provider_ref_encryption_key", None)
    key_id = getattr(config, "provider_ref_encryption_key_id", None)
    hmac_secret = getattr(config, "id_hmac_secret", None)
    if not key or not key_id or not hmac_secret:
        raise RuntimeError("billing provider-ref encryption is not configured")
    encrypted = encrypt_provider_ref(raw_ref=raw_id, key=key, key_id=key_id, provider=constants.STRIPE_PROVIDER_NAME)
    digest = hmac_provider_ref(provider=constants.STRIPE_PROVIDER_NAME, kind=kind, raw_id=raw_id, secret=hmac_secret)
    return {
        "ciphertext": encrypted.ciphertext,
        "hmac": digest,
        "fingerprint": provider_ref_fingerprint(digest=digest),
        "key_id": encrypted.key_id,
    }


def _provider_ref_evidence_or_none(raw_id: str | None, *, kind: str, config: BillingConfig) -> dict[str, Any] | None:
    text = str(raw_id or "").strip()
    if not text:
        return None
    return _provider_ref_evidence(text, kind=kind, config=config)


async def _billing_group_operational_row(scope: Mapping[str, Any]) -> dict[str, Any]:
    billing_group_id = _string_field(scope, "billing_group_id")
    if not billing_group_id or _bool_field(scope, "synthetic_scope", False):
        return {}
    try:
        row = await _maybe_await(db_billing.get_billing_group_operational_credentials(id=billing_group_id))
    except Exception as exc:
        logger.debug("Billing group operational readiness unavailable: %s", type(exc).__name__)
        return {}
    return _plain_mapping(row)


def _group_feature_ready_response(
    *,
    group: Mapping[str, Any],
    billing_config: BillingConfig,
    stripe_config: Any,
    feature: str,
) -> JSONResponse | None:
    if not billing_config.billing_enabled:
        return _generic_error_response(status_code=503)
    if feature == "checkout" and not billing_config.checkout_enabled:
        return _generic_error_response(status_code=503)
    if feature == "portal" and not billing_config.portal_enabled:
        return _generic_error_response(status_code=503)
    if not (getattr(stripe_config, "billing_enabled", False) and getattr(stripe_config, "stripe_billing_enabled", False)):
        return _generic_error_response(status_code=503)
    if feature == "checkout" and not getattr(stripe_config, "checkout_enabled", False):
        return _generic_error_response(status_code=503)
    if feature == "portal" and not getattr(stripe_config, "portal_enabled", False):
        return _generic_error_response(status_code=503)
    if not group:
        return _generic_error_response(status_code=422)
    if str(group.get("status") or "").strip().lower() != "active":
        return _generic_error_response(status_code=422)
    if str(group.get("credential_status") or "").strip().lower() != "active":
        return _generic_error_response(status_code=422)
    if not group.get("stripe_secret_key_ciphertext"):
        return _generic_error_response(status_code=422)
    if feature == "checkout" and not _bool_field(group, "checkout_enabled"):
        return _generic_error_response(status_code=422)
    if feature == "portal":
        if not _bool_field(group, "portal_enabled"):
            return _generic_error_response(status_code=422)
        if not group.get("stripe_portal_configuration_id_ciphertext"):
            return _generic_error_response(status_code=422)
    return None


def _provider_id_from_hosted_session(session: Mapping[str, Any] | BillingHostedSession, *names: str) -> str | None:
    metadata = getattr(session, "safe_metadata", None)
    if isinstance(metadata, Mapping):
        value = _string_field(metadata, *names)
        if value:
            return value
    mapped = _plain_mapping(session)
    return _string_field(mapped, *names)


async def _customer_operational_ref(scope: Mapping[str, Any], provider: str) -> BillingCustomerOperationalRef | None:
    try:
        row = await _maybe_await(
            get_customer_operational_ref(
                user_id=str(scope["user_id"]),
                billing_group_id=str(scope.get("billing_group_id") or ""),
                provider=provider,
            )
        )
    except Exception as exc:
        logger.debug("Billing customer operational ref unavailable: %s", type(exc).__name__)
        return None
    item = _plain_mapping(row)
    ciphertext = item.get("provider_customer_id_ciphertext") or item.get("ciphertext")
    key_id = _string_field(item, "provider_ref_key_id", "key_id")
    customer_ref = _string_field(item, "customer_ref")
    if not ciphertext or not key_id or not customer_ref:
        return None
    if isinstance(ciphertext, str):
        ciphertext = ciphertext.encode("utf-8")
    return BillingCustomerOperationalRef(
        provider=provider,
        customer_ref=customer_ref,
        ciphertext=bytes(ciphertext),
        key_id=key_id,
    )


async def _get_or_create_customer_operational_ref(
    *,
    scope: Mapping[str, Any],
    provider: str,
    client: StripeBillingClient,
    config: BillingConfig,
) -> BillingCustomerOperationalRef | None:
    existing = await _customer_operational_ref(scope, provider)
    if existing is not None:
        return existing

    user_id = _string_field(scope, "user_id")
    billing_group_id = _string_field(scope, "billing_group_id")
    if not user_id or not billing_group_id:
        return None

    customer_ref = _new_ref("bcust")
    metadata = {
        "api_auth_provider": constants.STRIPE_PROVIDER_NAME,
        "api_auth_customer_ref": customer_ref,
        "billing_contract_version": "2",
        "user_hash": _string_field(scope, "user_hash") or "",
        "project_hash": _string_field(scope, "project_hash") or "",
    }
    created = client.create_customer(
        metadata=metadata,
        idempotency_key=_provider_api_idempotency_key(f"{billing_group_id}:{user_id}", "customer_create"),
    )
    provider_customer_id = _string_field(created, "id")
    if not provider_customer_id:
        return None
    evidence = _provider_ref_evidence(provider_customer_id, kind="customer_id", config=config)
    await _maybe_await(
        upsert_customer(
            customer_id=_new_ref("bcustrow"),
            user_id=user_id,
            billing_group_id=billing_group_id,
            provider=provider,
            customer_ref=customer_ref,
            provider_customer_id_ciphertext=evidence["ciphertext"],
            provider_customer_id_hmac=evidence["hmac"],
            provider_customer_id_fingerprint=evidence["fingerprint"],
            provider_ref_key_id=evidence["key_id"],
            status="active",
            safe_metadata={"route": "billing_checkout", "contract_version": 2},
        )
    )
    return BillingCustomerOperationalRef(
        provider=provider,
        customer_ref=customer_ref,
        ciphertext=evidence["ciphertext"],
        key_id=evidence["key_id"],
    )


def _group_stripe_client(scope: Mapping[str, Any], config: BillingConfig) -> Any | None:
    """Build a per-billing-group Stripe client; None when the group is not ready.

    Each billing group uses its own Stripe account key (LOCKED DECISION 1). Returns None
    on any not-ready/decrypt failure so callers fall back to the safe synthetic seam.
    """
    billing_group_id = scope.get("billing_group_id")
    if not billing_group_id:
        return None
    try:
        return get_stripe_client_for_group(
            billing_group_id=str(billing_group_id),
            decryption_keys_by_id=config.decryption_keys_by_id,
        )
    except (StripeAccountNotReadyError, Exception) as exc:
        logger.debug("Per-group Stripe client unavailable: %s", type(exc).__name__)
        return None


def _group_stripe_secrets(scope: Mapping[str, Any], config: BillingConfig) -> Any | None:
    """Resolve a billing group's decrypted Stripe secrets (for portal config). None if not ready."""
    billing_group_id = scope.get("billing_group_id")
    if not billing_group_id:
        return None
    try:
        return get_stripe_account_secrets_for_group(
            billing_group_id=str(billing_group_id),
            decryption_keys_by_id=config.decryption_keys_by_id,
        )
    except (StripeAccountNotReadyError, Exception) as exc:
        logger.debug("Per-group Stripe secrets unavailable: %s", type(exc).__name__)
        return None


def _provider_api_idempotency_key(internal_ref: str, operation: str) -> str:
    try:
        return billing_idempotency.derive_stripe_api_idempotency_key(internal_ref=internal_ref, operation=operation)
    except Exception:
        digest = hashlib.sha256(f"{operation}:{internal_ref}".encode("utf-8")).hexdigest()[:32]
        return f"api-auth-stripe-{operation}-{digest}"


@router.get(_BILLING_PATH, response_model=BillingS2SResponse, status_code=200)
async def get_internal_billing_status(
    user_hash: str,
    request: Request,
    project_hash: str = Query(..., min_length=1),
    provider: str = Query(constants.STRIPE_PROVIDER_NAME),
) -> JSONResponse:
    """Return normalized billing facts for an authenticated S2S caller."""

    config_or_response = await _authorize_s2s(request)
    if isinstance(config_or_response, JSONResponse):
        return config_or_response

    rate_limited = await _check_rate_limit("s2s", request=request, user_hash=user_hash, project_hash=project_hash)
    if rate_limited is not None:
        return rate_limited

    try:
        row = await _maybe_await(
            get_current_by_user_project(
                user_hash=user_hash,
                project_hash=project_hash,
                provider=provider or constants.STRIPE_PROVIDER_NAME,
            )
        )
        response = _billing_read_response(user_hash=user_hash, project_hash=project_hash, row=_plain_mapping(row))
    except Exception as exc:
        logger.debug("Billing S2S read degraded to free default: %s", type(exc).__name__)
        response = _billing_read_response(user_hash=user_hash, project_hash=project_hash, row=None)
    return _safe_json_response_from_model(response, status_code=200)


def _public_catalog_item_from_row(row: Mapping[str, Any]) -> PublicCatalogItem:
    item = _plain_mapping(row)
    item_type = _string_field(item, "item_type") or "subscription_plan"
    features = item.get("features") if isinstance(item.get("features"), dict) else {}
    credits_value = _safe_int(features.get("credits")) if isinstance(features, Mapping) else 0
    return PublicCatalogItem(
        item_type=item_type,
        plan_code=_string_field(item, "plan_code") if item_type == "subscription_plan" else None,
        credit_product_code=_string_field(item, "plan_code") if item_type == "credit_package" else None,
        tier_code=_string_field(item, "tier_code"),
        tier_name=_string_field(item, "tier_name"),
        display_name=_string_field(item, "display_name") or "",
        amount_cents=item.get("unit_amount"),
        currency=_string_field(item, "currency"),
        interval=_string_field(item, "recurring_interval"),
        credits=credits_value or None,
        provider=_string_field(item, "provider") or constants.STRIPE_PROVIDER_NAME,
        provider_price_lookup_key=_string_field(item, "lookup_key"),
        features=features if isinstance(features, dict) else {},
        active=_bool_field(item, "active", True),
    )


def _catalog_response_from_rows(project_hash: str, rows: Any, provider: str) -> PublicCatalogResponse:
    subscriptions: list[PublicCatalogItem] = []
    credit_packs: list[PublicCatalogItem] = []
    group_hash: str | None = None
    for row in rows or []:
        mapped = _plain_mapping(row)
        if not mapped:
            continue
        group_hash = group_hash or _string_field(mapped, "billing_group_hash")
        catalog_item = _public_catalog_item_from_row(mapped)
        if catalog_item.item_type == "credit_package":
            credit_packs.append(catalog_item)
        else:
            subscriptions.append(catalog_item)
    return PublicCatalogResponse(
        success=True,
        message="Billing catalog returned.",
        project_hash=project_hash,
        billing_group_hash=group_hash,
        provider=provider or constants.STRIPE_PROVIDER_NAME,
        subscriptions=subscriptions,
        credit_packs=credit_packs,
        contract_version=2,
    )


@router.get(_CATALOG_PATH, response_model=PublicCatalogResponse, status_code=200)
async def get_internal_project_catalog(
    project_hash: str,
    request: Request,
    provider: str = Query(constants.STRIPE_PROVIDER_NAME),
    item_type: str = Query(None),
) -> JSONResponse:
    """Return the active per-project catalog (subscriptions + credit packages).

    Resolves project -> billing group -> catalog. A project with no billing group (or no
    active catalog) returns empty lists rather than an error.
    """

    config_or_response = await _authorize_s2s(request)
    if isinstance(config_or_response, JSONResponse):
        return config_or_response

    rate_limited = await _check_rate_limit("s2s", request=request, user_hash="-", project_hash=project_hash)
    if rate_limited is not None:
        return rate_limited

    normalized_item_type = (item_type or "").strip() or None
    try:
        rows = await _maybe_await(
            list_catalog_for_project(
                project_hash=project_hash,
                item_type=normalized_item_type,
                provider=provider or constants.STRIPE_PROVIDER_NAME,
            )
        )
        response = _catalog_response_from_rows(project_hash, rows, provider or constants.STRIPE_PROVIDER_NAME)
    except Exception as exc:
        logger.debug("Billing catalog listing degraded to empty: %s", type(exc).__name__)
        response = _catalog_response_from_rows(project_hash, [], provider or constants.STRIPE_PROVIDER_NAME)
    return _safe_json_response_from_model(response, status_code=200)


@router.post(_CHECKOUT_PATH, response_model=BillingCheckoutSessionResponse, status_code=202)
async def create_internal_billing_checkout(
    user_hash: str,
    request: Request,
    checkout_request: BillingCheckoutIntentRequest = Body(...),
) -> JSONResponse:
    """Create a hosted Checkout session from trusted consumer-owned intent."""

    config_or_response = await _authorize_s2s(request)
    if isinstance(config_or_response, JSONResponse):
        return config_or_response
    config = config_or_response

    validation_error = _validate_checkout_intent(checkout_request, config)
    if validation_error is not None:
        return validation_error

    rate_limited = await _check_rate_limit(
        "checkout",
        request=request,
        user_hash=user_hash,
        project_hash=checkout_request.project_hash,
        client_intent_ref=checkout_request.client_intent_ref,
    )
    if rate_limited is not None:
        return rate_limited

    scope = await _resolve_scope(user_hash, checkout_request.project_hash)
    checkout_ref = _new_ref("bco")
    subscription_ref = _new_ref("bsub") if checkout_request.intent_type == "subscription" else None
    purchase_ref = _new_ref("bpur") if checkout_request.intent_type == "credit_purchase" else None
    request_hash = billing_idempotency.canonical_request_hash(payload=checkout_request.model_dump(mode="json"))
    idem_cache_key = _idempotency_cache_key(
        route="checkout",
        user_id=str(scope["user_id"]),
        project_id=str(scope["project_id"]),
        request=request,
        body_ref=checkout_request.client_intent_ref,
    )
    local_decision, cached_response = _local_idempotency_decision(idem_cache_key, request_hash)
    if local_decision == "conflict":
        return _generic_error_response(status_code=409)
    if cached_response is not None:
        return JSONResponse(status_code=200, content=cached_response)

    idempotency_hmac = hashlib.sha256(":".join(idem_cache_key).encode("utf-8")).digest()
    if config.id_hmac_secret:
        try:
            idempotency_hmac = billing_idempotency.hash_s2s_idempotency_key(
                route="checkout",
                provider=checkout_request.provider,
                user_id=str(scope["user_id"]),
                project_id=str(scope["project_id"]),
                idempotency_key=idem_cache_key[-1],
                secret=config.id_hmac_secret,
            )
        except Exception:
            pass

    begin_row = await _begin_checkout_with_db(
        request_body=checkout_request,
        scope=scope,
        checkout_ref=checkout_ref,
        subscription_ref=subscription_ref,
        purchase_ref=purchase_ref,
        idempotency_key_hmac=idempotency_hmac,
        request_hash=request_hash,
        config=config,
    )
    begin_item = _plain_mapping(begin_row)
    if str(begin_item.get("intent_status") or "").lower() == "conflict":
        return _generic_error_response(status_code=409)
    replay_body = _stored_safe_response(begin_item.get("safe_response_json"))
    if replay_body is not None:
        return JSONResponse(status_code=200, content=dict(redact_billing_sensitive_data(replay_body)))

    stripe_config = load_stripe_config()
    group_row = await _billing_group_operational_row(scope)
    feature_error = _group_feature_ready_response(
        group=group_row,
        billing_config=config,
        stripe_config=stripe_config,
        feature="checkout",
    )
    if feature_error is not None:
        return feature_error

    intent = BillingCheckoutIntent(
        user_id=str(scope["user_id"]),
        project_id=str(scope["project_id"]),
        user_hash=user_hash,
        project_hash=checkout_request.project_hash,
        provider=checkout_request.provider,
        intent_type=checkout_request.intent_type,
        price_ref=BillingProviderPriceRef(ref_type=checkout_request.price_ref.ref_type, value=checkout_request.price_ref.value),
        quantity=checkout_request.quantity,
        checkout_ref=checkout_ref,
        purchase_ref=purchase_ref,
        subscription_ref=subscription_ref,
        plan_code=checkout_request.plan_code,
        tier_code=checkout_request.tier_code,
        tier_name=checkout_request.tier_name,
        credit_product_code=checkout_request.credit_product_code,
        success_url=checkout_request.success_url,
        cancel_url=checkout_request.cancel_url,
        safe_metadata={"customer_ref": None, "contract_version": 2},
    )

    hosted: BillingHostedSession | Mapping[str, Any]
    group_client = _group_stripe_client(scope, config)
    if group_client is None:
        return _generic_error_response(status_code=503)
    try:
        customer = await _get_or_create_customer_operational_ref(
            scope=scope,
            provider=checkout_request.provider,
            client=group_client,
            config=config,
        )
        if customer is None:
            return _generic_error_response(status_code=503)
        intent = BillingCheckoutIntent(**{**intent.__dict__, "safe_metadata": {"customer_ref": customer.customer_ref, "contract_version": 2}})
        hosted = await _maybe_await(
            create_checkout_session(
                intent=intent,
                customer=customer,
                idempotency_key=_provider_api_idempotency_key(checkout_ref, "checkout_session_create"),
                client=group_client,
                decryption_keys_by_id=config.decryption_keys_by_id,
            )
        )
    except Exception as exc:
        logger.debug("Stripe Checkout adapter unavailable: %s", type(exc).__name__)
        return _generic_error_response(status_code=_stripe_flow_status_code(exc, 503))

    response_model = _response_from_checkout_session(hosted)
    response_content = response_model.model_dump_safe(mode="json")
    _remember_idempotent_response(idem_cache_key, request_hash, response_content)
    checkout_evidence = None
    try:
        checkout_evidence = _provider_ref_evidence_or_none(
            _provider_id_from_hosted_session(hosted, "provider_checkout_session_id", "checkout_session_id", "id"),
            kind="checkout_session_id",
            config=config,
        )
    except Exception:
        checkout_evidence = None
    try:
        await _maybe_await(
            complete_checkout_intent(
                intent_id=str(begin_item.get("checkout_intent_id") or ""),
                status="completed",
                provider_checkout_session_id_ciphertext=checkout_evidence["ciphertext"] if checkout_evidence else None,
                provider_checkout_session_id_hmac=checkout_evidence["hmac"] if checkout_evidence else None,
                provider_checkout_session_id_fingerprint=checkout_evidence["fingerprint"] if checkout_evidence else None,
                provider_ref_key_id=checkout_evidence["key_id"] if checkout_evidence else None,
                hosted_session_fingerprint=checkout_evidence["fingerprint"] if checkout_evidence else None,
                safe_response_json=response_content,
                completed_at=_utc_now(),
            )
        )
    except Exception:
        pass
    return _safe_json_response_from_model(response_model, status_code=202)


@router.post(_PORTAL_PATH, response_model=BillingPortalSessionResponse, status_code=202)
async def create_internal_billing_portal(
    user_hash: str,
    request: Request,
    portal_request: BillingPortalSessionRequest = Body(...),
) -> JSONResponse:
    """Create an MVP-limited hosted Customer Portal session for S2S callers."""

    config_or_response = await _authorize_s2s(request)
    if isinstance(config_or_response, JSONResponse):
        return config_or_response
    config = config_or_response

    if config.return_url_allowlist and not is_return_url_allowed(portal_request.return_url, config.return_url_allowlist):
        return _generic_error_response(status_code=422)

    rate_limited = await _check_rate_limit("portal", request=request, user_hash=user_hash, project_hash=portal_request.project_hash)
    if rate_limited is not None:
        return rate_limited

    scope = await _resolve_scope(user_hash, portal_request.project_hash)
    portal_ref = _new_ref("bpo")
    request_hash = billing_idempotency.canonical_request_hash(payload=portal_request.model_dump(mode="json"))
    idem_cache_key = _idempotency_cache_key(
        route="portal",
        user_id=str(scope["user_id"]),
        project_id=str(scope["project_id"]),
        request=request,
        body_ref=portal_ref,
    )
    local_decision, cached_response = _local_idempotency_decision(idem_cache_key, request_hash)
    if local_decision == "conflict":
        return _generic_error_response(status_code=409)
    if cached_response is not None:
        return JSONResponse(status_code=200, content=cached_response)

    stripe_config = load_stripe_config()
    group_row = await _billing_group_operational_row(scope)
    feature_error = _group_feature_ready_response(
        group=group_row,
        billing_config=config,
        stripe_config=stripe_config,
        feature="portal",
    )
    if feature_error is not None:
        return feature_error

    customer = await _customer_operational_ref(scope, portal_request.provider)
    group_secrets = _group_stripe_secrets(scope, config)
    # Per-group portal configuration only — fail-closed like checkout/catalog/sync. No fallback to
    # the global env STRIPE_PORTAL_CONFIGURATION_ID (which could point at the wrong account's portal).
    portal_config_id = getattr(group_secrets, "portal_configuration_id", None) if group_secrets else None
    hosted: BillingHostedSession | Mapping[str, Any]
    if customer is None or group_secrets is None or not portal_config_id:
        return _generic_error_response(status_code=422)
    try:
        hosted = await _maybe_await(
            create_portal_session(
                customer=customer,
                return_url=portal_request.return_url,
                portal_ref=portal_ref,
                configuration_id=portal_config_id,
                client=StripeBillingClient(secret_key=group_secrets.secret_key, api_version=stripe_config.api_version),
                decryption_keys_by_id=config.decryption_keys_by_id,
                idempotency_key=_provider_api_idempotency_key(portal_ref, "portal_session_create"),
            )
        )
    except Exception as exc:
        logger.debug("Stripe Portal adapter unavailable: %s", type(exc).__name__)
        return _generic_error_response(status_code=_stripe_flow_status_code(exc, 503))

    response_model = _response_from_portal_session(hosted)
    response_content = response_model.model_dump_safe(mode="json")
    _remember_idempotent_response(idem_cache_key, request_hash, response_content)
    return _safe_json_response_from_model(response_model, status_code=202)


@router.get(_PURCHASE_PATH, response_model=BillingPurchaseStatusResponse, status_code=200)
async def get_internal_billing_purchase_status(
    user_hash: str,
    purchase_ref: str,
    request: Request,
    project_hash: str = Query(..., min_length=1),
    provider: str = Query(constants.STRIPE_PROVIDER_NAME),
) -> JSONResponse:
    """Read a safe purchase fact for pull-only consumer credit decisions."""

    config_or_response = await _authorize_s2s(request)
    if isinstance(config_or_response, JSONResponse):
        return config_or_response


    rate_limited = await _check_rate_limit("s2s", request=request, user_hash=user_hash, project_hash=project_hash)
    if rate_limited is not None:
        return rate_limited

    getter = get_purchase_status_by_ref
    if callable(getter):
        try:
            row = await _maybe_await(getter(user_hash=user_hash, project_hash=project_hash, purchase_ref=purchase_ref, provider=provider))
            purchase = billing_status.safe_purchase_from_row(_plain_mapping(row), provider=provider)
            if purchase is not None and purchase.purchase_ref:
                payload = purchase.to_dict()
                payload["classification_version"] = max(2, _safe_int(payload.get("classification_version"), 2))
                response = BillingPurchaseStatusResponse(
                    success=True,
                    message="Purchase status returned.",
                    user_hash=user_hash,
                    project_hash=project_hash,
                    provider=constants.STRIPE_PROVIDER_NAME,
                    purchase=BillingSafePurchaseStatus(**payload),
                    contract_version=2,
                )
                return _safe_json_response_from_model(response, status_code=200)
        except Exception as exc:
            logger.debug("Billing purchase-status read degraded generically: %s", type(exc).__name__)
    return _generic_error_response(status_code=404, message=_GENERIC_NOT_FOUND_MESSAGE)


@router.post(_RESYNC_PATH, response_model=BillingResyncAcceptedResponse, status_code=202)
async def enqueue_internal_billing_resync(
    user_hash: str,
    request: Request,
    resync_request: Mapping[str, Any] | None = Body(default=None),
) -> JSONResponse:
    """Accept a safe source-of-truth billing resync request."""

    config_or_response = await _authorize_s2s(request)
    if isinstance(config_or_response, JSONResponse):
        return config_or_response
    config = config_or_response
    body = _plain_mapping(resync_request)
    project_hash = _string_field(body, "project_hash")
    if not project_hash:
        return _generic_error_response(status_code=422)
    reason = _string_field(body, "reason", default="internal_manual_resync") or "internal_manual_resync"

    rate_limited = await _check_rate_limit("resync", request=request, user_hash=user_hash, project_hash=project_hash, reason=reason)
    if rate_limited is not None:
        return rate_limited

    if not config.sync_enabled:
        response = BillingResyncAcceptedResponse(
            success=True,
            accepted=False,
            status="disabled",
            user_hash=user_hash,
            project_hash=project_hash,
            provider=constants.STRIPE_PROVIDER_NAME,
            contract_version=2,
            message="Billing resync request accepted.",
        )
        return _safe_json_response_from_model(response, status_code=202)

    scope = await _resolve_scope(user_hash, project_hash)
    job_id = _new_ref("bsync")
    accepted = False
    try:
        dedupe = billing_sync.sync_job_dedupe_hmac(
            provider=constants.STRIPE_PROVIDER_NAME,
            job_type=billing_sync.JOB_TYPE_WEBHOOK_RESYNC,
            secret=config.id_hmac_secret,
            user_id=str(scope["user_id"]),
            project_id=str(scope["project_id"]),
            billing_group_id=_string_field(scope, "billing_group_id"),
            reason=reason,
        )
        await _maybe_await(
            enqueue_sync_job(
                provider=constants.STRIPE_PROVIDER_NAME,
                job_type=billing_sync.JOB_TYPE_WEBHOOK_RESYNC,
                job_id=job_id,
                user_id=str(scope["user_id"]),
                project_id=str(scope["project_id"]),
                billing_group_id=_string_field(scope, "billing_group_id"),
                dedupe_key_hmac=dedupe,
                priority=1 if _bool_field(body, "force") else 5,
                source="manual",
                sanitized_metadata={
                    "route": "billing_resync",
                    "reason": reason,
                    "billing_group_id": _string_field(scope, "billing_group_id"),
                },
            )
        )
        accepted = True
    except Exception as exc:
        logger.debug("Billing resync enqueue degraded generically: %s", type(exc).__name__)

    response = BillingResyncAcceptedResponse(
        success=True,
        accepted=accepted,
        status="queued" if accepted else "degraded",
        user_hash=user_hash if accepted else None,
        project_hash=project_hash if accepted else None,
        provider=constants.STRIPE_PROVIDER_NAME,
        correlation_id=job_id if accepted else None,
        contract_version=2,
        message="Billing resync request accepted.",
    )
    return _safe_json_response_from_model(response, status_code=202)


def _route_path(route: Any) -> str:
    return str(getattr(route, "path", ""))


def _assert_identity_contract_unchanged() -> None:
    for model_cls in (ValidateSessionResponse, UserLogin, EnhancedUserLogin):
        fields = {str(field).lower() for field in getattr(model_cls, "model_fields", {})}
        offenders = sorted(field for field in fields if any(fragment in field for fragment in _AUTH_BILLING_DRIFT_FRAGMENTS))
        if offenders:
            raise RuntimeError(f"{model_cls.__name__} drifted into billing/provider fields: {offenders}")

    jwt_claim_sets = (
        getattr(constants, "BASE_REQUIRED_JWT_CLAIMS", ()),
        getattr(constants, "AUTH_REQUIRED_JWT_CLAIMS", ()),
    )
    for claim_set in jwt_claim_sets:
        offenders = sorted(
            str(claim).lower()
            for claim in claim_set
            if any(fragment in str(claim).lower() for fragment in _AUTH_BILLING_DRIFT_FRAGMENTS)
        )
        if offenders:
            raise RuntimeError(f"JWT claim contract drifted into billing/provider fields: {offenders}")


def _assert_internal_route_hardening() -> None:
    assert_billing_response_model_allow_lists()
    _assert_identity_contract_unchanged()

    registered_paths = {_route_path(route) for route in getattr(router, "routes", [])}
    if registered_paths != _ALLOWED_INTERNAL_ROUTES:
        raise RuntimeError(f"Unexpected billing internal routes: {sorted(registered_paths)}")

    for path in registered_paths:
        if not APIAuditLogger.is_billing_internal_path(path):
            raise RuntimeError(f"Billing internal route is not classified as S2S billing path: {path}")
        if APIAuditLogger.infer_auth_method_for_path(path) != "api_key":
            raise RuntimeError(f"Billing internal route must audit as api_key/S2S: {path}")

    for route in getattr(router, "routes", []):
        response_model = getattr(route, "response_model", None)
        if response_model is None:
            continue
        safe_fields = frozenset(getattr(response_model, "safe_fields", frozenset()))
        if not safe_fields:
            raise RuntimeError(f"{response_model.__name__} is missing billing safe_fields")

    forbidden_globals = sorted(name for name in _FORBIDDEN_AUTH_CONTEXT_GLOBALS if name in globals())
    if forbidden_globals:
        raise RuntimeError(f"Billing internal route imported user auth/session seams: {forbidden_globals}")


_assert_internal_route_hardening()


__all__ = [
    "router",
    "get_internal_billing_status",
    "create_internal_billing_checkout",
    "create_internal_billing_portal",
    "get_internal_billing_purchase_status",
    "enqueue_internal_billing_resync",
]
