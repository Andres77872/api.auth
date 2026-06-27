"""Admin billing management routes (dashboard surface).

Manages the centralized billing catalog source of truth: billing groups, per-account
Stripe credentials (write-only, encrypted), group<->project membership, and the catalog of
subscription plans / credit packages. Creating or repricing a catalog item provisions the
Stripe Product/Price on the group's own account.

This is a cookie/session-authenticated ADMIN surface — distinct from the S2S
``internal_billing`` router. It never exposes raw Stripe secrets or operational ids; only
presence flags and non-secret fingerprints are returned. api.auth stays agnostic of product
meaning: ``features``/``metadata`` are opaque JSON passthrough.
"""

from __future__ import annotations

import json
import logging
import secrets
from typing import Any, Mapping, Optional

from fastapi import APIRouter, Body, Depends, Form, Query
from fastapi.security import HTTPAuthorizationCredentials

from src.Util import auth_constants as constants
from src.Util.Models import (
    AttachProjectToBillingGroupResponse,
    BaseResponse,
    BillingAdminMetrics,
    BillingAdminMetricsResponse,
    BillingCapabilitiesUpdate,
    BillingCredentialsStatus,
    BillingCredentialsStatusResponse,
    BillingGroupDetailsResponse,
    BillingGroupInfo,
    BillingGroupProjectInfo,
    BillingGroupProjectsResponse,
    BillingGroupReadiness,
    BillingGroupResponse,
    CatalogDriftItem,
    CatalogImportCandidate,
    CatalogImportRequest,
    CatalogImportResponse,
    CatalogItemInfo,
    CatalogItemResponse,
    CatalogListResponse,
    CatalogReconcileResponse,
    CatalogReconcileResult,
    CredentialValidationResponse,
    ListBillingGroupsResponse,
    PaginationInfo,
    StripeAccountCredentialsUpdate,
)
from src.Util.Seccurity import HTTPBearerOrCookie
from src.Util.billing.config import load_billing_config
from src.Util.billing.security import encrypt_provider_ref, hmac_provider_ref, provider_ref_fingerprint
from src.Util.db import db_billing, get_project_by_hash, is_root_user, validate_session
from src.Util.db_error_wrapper import handle_db_operation
from src.Util.error_handler import (
    AuthenticationError,
    AuthorizationError,
    ConflictError,
    ErrorCode,
    NotFoundError,
    StripeFlowError,
    ValidationError,
)
from src.Util.stripe.config import load_stripe_config
from src.Util.stripe import provisioning as stripe_provisioning
from src.Util.stripe import catalog_sync as stripe_catalog_sync
from src.Util.stripe.credentials import validate_stripe_credentials


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/billing", tags=["Admin - Billing"])
security = HTTPBearerOrCookie()

_PROVIDER = "stripe"
_SUPPORTED_PROVIDERS = {_PROVIDER}
_VALID_ITEM_TYPES = {"subscription_plan", "credit_package"}


# --------------------------------------------------------------------------- auth gates
async def require_billing_admin(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Require ``admin`` OR ``manage_billing`` permission (mirrors admin_project_groups)."""

    session_data = validate_session(credentials.credentials)
    if not session_data:
        raise AuthenticationError(message="Invalid or expired session", error_code=ErrorCode.SESSION_INVALID)
    perms = session_data.permissions if hasattr(session_data, "permissions") else []
    if "admin" not in perms and "manage_billing" not in perms:
        raise AuthorizationError(
            message="Admin or manage_billing permission required",
            error_code=ErrorCode.INSUFFICIENT_PERMISSIONS,
            details={"required_permissions": ["admin", "manage_billing"]},
        )
    return session_data


async def require_billing_root(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Credential endpoints accept Stripe secrets — restrict to root users only."""

    session_data = await require_billing_admin(credentials)
    if not is_root_user(session_data.user_id):
        raise AuthorizationError(
            message="Root privilege required to manage billing credentials",
            error_code=ErrorCode.INSUFFICIENT_PERMISSIONS,
        )
    return session_data


# --------------------------------------------------------------------------- helpers
def _new_id(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(24)}"


def _new_hash() -> str:
    return secrets.token_hex(32).upper()


def _bool(value: Any) -> bool:
    return bool(value) and str(value).strip().lower() not in {"0", "false", "no", ""}


def _parse_json_object(raw: Optional[str], *, field: str) -> dict[str, Any] | None:
    if raw is None or str(raw).strip() == "":
        return None
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValidationError(message=f"{field} must be a JSON object", error_code=ErrorCode.INVALID_INPUT) from exc
    if not isinstance(parsed, dict):
        raise ValidationError(message=f"{field} must be a JSON object", error_code=ErrorCode.INVALID_INPUT)
    return parsed


def _normalize_provider(provider: str | None) -> str:
    normalized = str(provider or _PROVIDER).strip().lower() or _PROVIDER
    if normalized not in _SUPPORTED_PROVIDERS:
        raise ValidationError(
            message="Unsupported billing provider",
            error_code=ErrorCode.INVALID_ENUM_VALUE,
            details={"supported_providers": sorted(_SUPPORTED_PROVIDERS)},
        )
    return normalized


def _require_provider_seed(provider: str) -> None:
    exists = handle_db_operation(
        lambda: db_billing.billing_provider_exists(provider=provider),
        error_context="check billing provider registry",
    )
    if not exists:
        raise StripeFlowError(
            error_code=ErrorCode.STRIPE_PROVIDER_NOT_CONFIGURED,
            status_code=503,
            details={"provider": provider, "missing_dependency": "billing_provider_registry"},
        )


def _require_group(group_hash: str) -> dict[str, Any]:
    row = handle_db_operation(
        lambda: db_billing.get_billing_group_by_hash(billing_group_hash=group_hash),
        error_context="get billing group",
    )
    if not row:
        raise NotFoundError(message="Billing group not found", error_code=ErrorCode.RESOURCE_NOT_FOUND)
    return row


def _require_catalog_item(catalog_item_hash: str) -> dict[str, Any]:
    row = handle_db_operation(
        lambda: db_billing.get_catalog_item_by_hash(catalog_item_hash=catalog_item_hash),
        error_context="get catalog item",
    )
    if not row:
        raise NotFoundError(message="Catalog item not found", error_code=ErrorCode.RESOURCE_NOT_FOUND)
    return row


def _group_info(row: Mapping[str, Any]) -> BillingGroupInfo:
    return BillingGroupInfo(
        group_hash=row.get("billing_group_hash"),
        name=row.get("name"),
        description=row.get("description"),
        owner_id=row.get("owner_id"),
        provider=row.get("provider") or _PROVIDER,
        status=row.get("status") or "active",
        checkout_enabled=bool(row.get("checkout_enabled")),
        portal_enabled=bool(row.get("portal_enabled")),
        provisioning_enabled=bool(row.get("provisioning_enabled")),
        webhooks_enabled=bool(row.get("webhooks_enabled")),
        credential_status=row.get("credential_status") or "absent",
        has_secret_key=bool(row.get("has_secret_key")),
        has_webhook_secret=bool(row.get("has_webhook_secret")),
        project_count=row.get("project_count"),
        catalog_item_count=row.get("catalog_item_count"),
        last_catalog_synced_at=row.get("last_catalog_synced_at"),
        catalog_sync_status=row.get("catalog_sync_status") or "never",
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def _project_info(row: Mapping[str, Any]) -> BillingGroupProjectInfo:
    return BillingGroupProjectInfo(
        project_hash=row.get("project_hash"),
        project_name=row.get("project_name"),
        project_description=row.get("project_description"),
        status=row.get("status") or "active",
        added_at=row.get("added_at"),
    )


def _catalog_info(row: Mapping[str, Any]) -> CatalogItemInfo:
    return CatalogItemInfo(
        item_hash=row.get("catalog_item_hash"),
        item_type=row.get("item_type"),
        plan_code=row.get("plan_code"),
        tier_code=row.get("tier_code"),
        tier_name=row.get("tier_name"),
        display_name=row.get("display_name"),
        currency=row.get("currency"),
        unit_amount=row.get("unit_amount"),
        recurring_interval=row.get("recurring_interval"),
        lookup_key=row.get("lookup_key"),
        provider=row.get("provider") or _PROVIDER,
        provider_price_fingerprint=row.get("provider_price_id_fingerprint"),
        features=row.get("features") if isinstance(row.get("features"), dict) else {},
        metadata=row.get("metadata") if isinstance(row.get("metadata"), dict) else {},
        sort_order=int(row.get("sort_order") or 0),
        active=bool(row.get("active")),
        provisioning_status=row.get("provisioning_status") or "pending",
        provisioning_error=row.get("provisioning_error_redacted"),
        provisioned_at=row.get("provisioned_at"),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def _credentials_status(row: Mapping[str, Any]) -> BillingCredentialsStatus:
    return BillingCredentialsStatus(
        credential_status=row.get("credential_status") or "absent",
        has_secret_key=bool(row.get("has_secret_key")),
        has_webhook_secret=bool(row.get("has_webhook_secret")),
        secret_key_fingerprint=row.get("stripe_secret_key_fingerprint"),
        webhook_secret_fingerprint=row.get("stripe_webhook_secret_fingerprint"),
        stripe_account_label=row.get("stripe_account_label"),
        stripe_account_fingerprint=row.get("stripe_account_fingerprint"),
        credential_key_id=row.get("credential_key_id"),
        credentials_set_at=row.get("credentials_set_at"),
    )


def _global_billing_gate_missing(*, capability: str) -> list[str]:
    billing_config = load_billing_config()
    stripe_config = load_stripe_config()
    missing: list[str] = []
    if not getattr(billing_config, "billing_enabled", False):
        missing.append("BILLING_ENABLED")
    if not getattr(stripe_config, "stripe_billing_enabled", False):
        missing.append("STRIPE_BILLING_ENABLED")
    if capability == "checkout":
        if not getattr(billing_config, "checkout_enabled", False):
            missing.append("BILLING_CHECKOUT_ENABLED")
        if not getattr(stripe_config, "checkout_enabled", False):
            missing.append("STRIPE_CHECKOUT_ENABLED")
    elif capability == "portal":
        if not getattr(billing_config, "portal_enabled", False):
            missing.append("BILLING_PORTAL_ENABLED")
        if not getattr(stripe_config, "portal_enabled", False):
            missing.append("STRIPE_PORTAL_ENABLED")
    elif capability == "webhooks":
        if not getattr(stripe_config, "webhooks_enabled", False):
            missing.append("STRIPE_WEBHOOKS_ENABLED")
    elif capability == "provisioning":
        pass
    return missing


def _catalog_has_checkout_price_refs(group_id: str) -> bool:
    rows = handle_db_operation(
        lambda: db_billing.list_catalog_for_group(billing_group_id=group_id, include_archived=False),
        error_context="list billing group catalog for capability validation",
        default_return=[],
    )
    for row in rows or []:
        if not row.get("active"):
            continue
        if str(row.get("provisioning_status") or "").strip().lower() != "active":
            continue
        if row.get("provider_price_id_fingerprint"):
            return True
    return False


def _capability_missing_reasons(group: Mapping[str, Any], *, capability: str) -> list[str]:
    missing = _global_billing_gate_missing(capability=capability)
    if str(group.get("status") or "").strip().lower() != "active":
        missing.append("billing_group_active")
    if str(group.get("credential_status") or "").strip().lower() != "active":
        missing.append("billing_group_credentials_active")
    if not group.get("has_secret_key") and not group.get("stripe_secret_key_ciphertext"):
        missing.append("stripe_secret_key")
    if capability == "checkout" and not _catalog_has_checkout_price_refs(str(group.get("id") or "")):
        missing.append("active_catalog_price")
    if capability == "portal":
        operational = handle_db_operation(
            lambda: db_billing.get_billing_group_operational_credentials(id=group["id"]),
            error_context="get billing group operational credentials for portal capability",
            default_return={},
        ) or {}
        if not operational.get("stripe_portal_configuration_id_ciphertext"):
            missing.append("stripe_portal_configuration_id")
    if capability == "webhooks" and not group.get("has_webhook_secret"):
        missing.append("stripe_webhook_secret")
    return list(dict.fromkeys(missing))


def _assert_capability_enable_allowed(group: Mapping[str, Any], *, capability: str) -> None:
    missing = _capability_missing_reasons(group, capability=capability)
    if missing:
        raise ValidationError(
            message=f"Cannot enable billing {capability}; prerequisites are missing",
            error_code=ErrorCode.INVALID_INPUT,
            details={"missing": missing, "capability": capability},
        )


def _readiness_for_group(group: Mapping[str, Any]) -> BillingGroupReadiness:
    missing: list[str] = []
    for capability in ("checkout", "portal", "webhooks"):
        missing.extend(_capability_missing_reasons(group, capability=capability))
    missing = list(dict.fromkeys(missing))
    ready = not missing
    return BillingGroupReadiness(
        ready=ready,
        status="ready" if ready else "not_ready",
        missing=missing,
        capabilities={
            "checkout": bool(group.get("checkout_enabled")),
            "portal": bool(group.get("portal_enabled")),
            "provisioning": bool(group.get("provisioning_enabled")),
            "webhooks": bool(group.get("webhooks_enabled")),
        },
        webhook_endpoint_path=f"{constants.STRIPE_WEBHOOK_ROUTE}/{group.get('billing_group_hash')}",
    )


# --------------------------------------------------------------------------- groups
@router.get("", response_model=ListBillingGroupsResponse)
async def list_groups(
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    search: str = Query(None),
    session_data=Depends(require_billing_admin),
) -> ListBillingGroupsResponse:
    rows, total = handle_db_operation(
        lambda: db_billing.list_billing_groups(search=search, limit=limit, offset=offset),
        error_context="list billing groups",
        default_return=([], 0),
    )
    return ListBillingGroupsResponse(
        success=True,
        billing_groups=[_group_info(r) for r in rows],
        pagination=PaginationInfo(limit=limit, offset=offset, total=total, has_more=offset + limit < total),
    )


@router.post("", response_model=BillingGroupResponse)
async def create_group(
    group_name: str = Form(...),
    description: str = Form(None),
    provider: str = Form(_PROVIDER),
    session_data=Depends(require_billing_admin),
) -> BillingGroupResponse:
    group_id = _new_id("bg")
    group_hash = _new_hash()
    provider_code = _normalize_provider(provider)
    _require_provider_seed(provider_code)
    handle_db_operation(
        lambda: db_billing.create_billing_group(
            id=group_id,
            billing_group_hash=group_hash,
            name=group_name,
            description=description,
            owner_id=session_data.user_id,
            provider=provider_code,
            created_by=session_data.user_id,
        ),
        error_context="create billing group",
    )
    return BillingGroupResponse(success=True, message="Billing group created", billing_group=_group_info(_require_group(group_hash)))


@router.get("/metrics", response_model=BillingAdminMetricsResponse)
async def get_metrics(session_data=Depends(require_billing_admin)) -> BillingAdminMetricsResponse:
    """Aggregate billing counts for the dashboard (groups/credentials/catalog/projects).

    Registered before ``/{group_hash}`` so the literal ``metrics`` path is not captured as a
    group hash. Counts only — agnostic of product meaning, no secrets.
    """

    row = handle_db_operation(
        lambda: db_billing.get_billing_admin_metrics(),
        error_context="get billing admin metrics",
        default_return={},
    )
    return BillingAdminMetricsResponse(success=True, metrics=BillingAdminMetrics(**(row or {})))


@router.get("/{group_hash}", response_model=BillingGroupDetailsResponse)
async def get_group(group_hash: str, session_data=Depends(require_billing_admin)) -> BillingGroupDetailsResponse:
    group = _require_group(group_hash)
    projects = handle_db_operation(
        lambda: db_billing.list_billing_group_projects(billing_group_id=group["id"]),
        error_context="list billing group projects",
        default_return=[],
    )
    catalog = handle_db_operation(
        lambda: db_billing.list_catalog_for_group(billing_group_id=group["id"], include_archived=True),
        error_context="list billing group catalog",
        default_return=[],
    )
    return BillingGroupDetailsResponse(
        success=True,
        billing_group=_group_info(group),
        projects=[_project_info(p) for p in projects],
        catalog=[_catalog_info(c) for c in catalog],
        credentials=_credentials_status(group),
        readiness=_readiness_for_group(group),
    )


@router.put("/{group_hash}", response_model=BillingGroupResponse)
async def update_group(
    group_hash: str,
    group_name: str = Form(None),
    description: str = Form(None),
    status: str = Form(None),
    session_data=Depends(require_billing_admin),
) -> BillingGroupResponse:
    group = _require_group(group_hash)
    handle_db_operation(
        lambda: db_billing.update_billing_group(id=group["id"], name=group_name, description=description, status=status),
        error_context="update billing group",
    )
    return BillingGroupResponse(success=True, message="Billing group updated", billing_group=_group_info(_require_group(group_hash)))


@router.put("/{group_hash}/capabilities", response_model=BillingGroupResponse)
async def update_capabilities(
    group_hash: str,
    body: BillingCapabilitiesUpdate = Body(...),
    session_data=Depends(require_billing_admin),
) -> BillingGroupResponse:
    group = _require_group(group_hash)
    requested = {
        "checkout": body.checkout_enabled,
        "portal": body.portal_enabled,
        "provisioning": body.provisioning_enabled,
        "webhooks": body.webhooks_enabled,
    }
    for capability, enabled in requested.items():
        if enabled is True:
            if capability == "provisioning":
                missing = _global_billing_gate_missing(capability="provisioning")
                if str(group.get("status") or "").strip().lower() != "active":
                    missing.append("billing_group_active")
                if str(group.get("credential_status") or "").strip().lower() != "active":
                    missing.append("billing_group_credentials_active")
                if missing:
                    raise ValidationError(
                        message="Cannot enable billing provisioning; prerequisites are missing",
                        error_code=ErrorCode.INVALID_INPUT,
                        details={"missing": list(dict.fromkeys(missing)), "capability": capability},
                    )
            else:
                _assert_capability_enable_allowed(group, capability=capability)
    handle_db_operation(
        lambda: db_billing.set_billing_group_capabilities(
            id=group["id"],
            checkout_enabled=body.checkout_enabled,
            portal_enabled=body.portal_enabled,
            provisioning_enabled=body.provisioning_enabled,
            webhooks_enabled=body.webhooks_enabled,
        ),
        error_context="update billing group capabilities",
    )
    return BillingGroupResponse(
        success=True,
        message="Billing group capabilities updated",
        billing_group=_group_info(_require_group(group_hash)),
    )


@router.delete("/{group_hash}", response_model=BaseResponse)
async def delete_group(group_hash: str, session_data=Depends(require_billing_admin)) -> BaseResponse:
    group = _require_group(group_hash)
    try:
        handle_db_operation(
            lambda: db_billing.delete_billing_group(id=group["id"]),
            error_context="delete billing group",
        )
    except (ConflictError, NotFoundError, AuthorizationError):
        raise
    except Exception as exc:  # SIGNAL: active subscriptions block deletion
        raise ConflictError(
            message="Cannot delete a billing group with active subscriptions",
            error_code=ErrorCode.CONFLICT,
        ) from exc
    return BaseResponse(success=True, message="Billing group deleted")


# --------------------------------------------------------------------------- projects
@router.get("/{group_hash}/projects", response_model=BillingGroupProjectsResponse)
async def list_group_projects(group_hash: str, session_data=Depends(require_billing_admin)) -> BillingGroupProjectsResponse:
    group = _require_group(group_hash)
    projects = handle_db_operation(
        lambda: db_billing.list_billing_group_projects(billing_group_id=group["id"]),
        error_context="list billing group projects",
        default_return=[],
    )
    return BillingGroupProjectsResponse(success=True, projects=[_project_info(p) for p in projects])


@router.post("/{group_hash}/projects", response_model=AttachProjectToBillingGroupResponse)
async def attach_project(
    group_hash: str,
    project_hash: str = Form(...),
    session_data=Depends(require_billing_admin),
) -> AttachProjectToBillingGroupResponse:
    group = _require_group(group_hash)
    project = handle_db_operation(lambda: get_project_by_hash(project_hash), error_context="resolve project")
    if not project:
        raise NotFoundError(message="Project not found", error_code=ErrorCode.RESOURCE_NOT_FOUND)
    try:
        row = handle_db_operation(
            lambda: db_billing.attach_project_to_billing_group(
                id=_new_id("bgp"), billing_group_id=group["id"], project_id=project.id, added_by=session_data.user_id
            ),
            error_context="attach project to billing group",
        )
    except (ConflictError, NotFoundError):
        raise
    except Exception as exc:  # SIGNAL: project already attached to another group
        raise ConflictError(
            message="Project is already attached to another billing group",
            error_code=ErrorCode.CONFLICT,
        ) from exc
    return AttachProjectToBillingGroupResponse(
        success=True,
        message="Project attached",
        project=_project_info(row) if row else None,
    )


@router.delete("/{group_hash}/projects/{project_hash}", response_model=BaseResponse)
async def detach_project(group_hash: str, project_hash: str, session_data=Depends(require_billing_admin)) -> BaseResponse:
    _require_group(group_hash)
    project = handle_db_operation(lambda: get_project_by_hash(project_hash), error_context="resolve project")
    if not project:
        raise NotFoundError(message="Project not found", error_code=ErrorCode.RESOURCE_NOT_FOUND)
    handle_db_operation(
        lambda: db_billing.detach_project_from_billing_group(project_id=project.id, removed_by=session_data.user_id),
        error_context="detach project from billing group",
    )
    return BaseResponse(success=True, message="Project detached")


# --------------------------------------------------------------------------- credentials (root only)
@router.get("/{group_hash}/credentials", response_model=BillingCredentialsStatusResponse)
async def get_credentials(group_hash: str, session_data=Depends(require_billing_admin)) -> BillingCredentialsStatusResponse:
    group = _require_group(group_hash)
    return BillingCredentialsStatusResponse(success=True, credentials=_credentials_status(group))


def _apply_credentials(group_hash: str, body: StripeAccountCredentialsUpdate) -> BillingCredentialsStatusResponse:
    group = _require_group(group_hash)
    config = load_billing_config()
    key = getattr(config, "provider_ref_encryption_key", None)
    key_id = getattr(config, "provider_ref_encryption_key_id", None)
    hmac_secret = getattr(config, "id_hmac_secret", None)
    if not key or not key_id or not hmac_secret:
        raise ValidationError(
            message="Server billing encryption keys are not configured",
            error_code=ErrorCode.INVALID_INPUT,
        )

    # Confirm the credentials are actually correct before we encrypt + store them: format checks,
    # a live auth probe against Stripe, and (when supplied) the portal config. Fail-closed — raises
    # ValidationError (400) on any failure, never leaking key material.
    validate_stripe_credentials(body)

    def _enc(raw: str, kind: str):
        encrypted = encrypt_provider_ref(raw_ref=raw, key=key, key_id=key_id, provider=_PROVIDER)
        digest = hmac_provider_ref(provider=_PROVIDER, kind=kind, raw_id=raw, secret=hmac_secret)
        return encrypted.ciphertext, digest, provider_ref_fingerprint(digest=digest)

    secret_ct, secret_hmac, secret_fp = _enc(body.secret_key, "account_secret_key")
    webhook_ct = webhook_hmac = webhook_fp = None
    if body.webhook_secret:
        webhook_ct, webhook_hmac, webhook_fp = _enc(body.webhook_secret, "account_webhook_secret")
    portal_ct = None
    if body.portal_configuration_id:
        portal_ct = encrypt_provider_ref(raw_ref=body.portal_configuration_id, key=key, key_id=key_id, provider=_PROVIDER).ciphertext

    handle_db_operation(
        lambda: db_billing.set_billing_group_credentials(
            id=group["id"],
            stripe_account_label=body.stripe_account_label,
            stripe_account_fingerprint=secret_fp,
            stripe_secret_key_ciphertext=secret_ct,
            stripe_secret_key_hmac=secret_hmac,
            stripe_secret_key_fingerprint=secret_fp,
            stripe_webhook_secret_ciphertext=webhook_ct,
            stripe_webhook_secret_hmac=webhook_hmac,
            stripe_webhook_secret_fingerprint=webhook_fp,
            stripe_portal_configuration_id_ciphertext=portal_ct,
            credential_key_id=key_id,
        ),
        error_context="set billing group credentials",
    )
    return BillingCredentialsStatusResponse(
        success=True,
        message="Billing credentials saved",
        credentials=_credentials_status(_require_group(group_hash)),
    )


@router.put("/{group_hash}/credentials", response_model=BillingCredentialsStatusResponse)
async def set_credentials(
    group_hash: str,
    body: StripeAccountCredentialsUpdate = Body(...),
    session_data=Depends(require_billing_root),
) -> BillingCredentialsStatusResponse:
    return _apply_credentials(group_hash, body)


@router.post("/{group_hash}/credentials/rotate", response_model=BillingCredentialsStatusResponse)
async def rotate_credentials(
    group_hash: str,
    body: StripeAccountCredentialsUpdate = Body(...),
    session_data=Depends(require_billing_root),
) -> BillingCredentialsStatusResponse:
    return _apply_credentials(group_hash, body)


@router.post("/{group_hash}/credentials/test", response_model=CredentialValidationResponse)
async def test_credentials(
    group_hash: str,
    body: StripeAccountCredentialsUpdate = Body(...),
    session_data=Depends(require_billing_root),
) -> CredentialValidationResponse:
    """Validate submitted Stripe credentials WITHOUT saving them ('test connection').

    Runs the same format + live auth probe + portal-config validation as set/rotate. Returns
    presence/flags only (valid, livemode, account fingerprint) — never secrets. Invalid credentials
    raise ValidationError (400, redacted).
    """
    _require_group(group_hash)
    result = validate_stripe_credentials(body)
    return CredentialValidationResponse(
        success=True,
        message="Stripe credentials validated",
        valid=result.valid,
        secret_key_valid=result.secret_key_valid,
        portal_configuration_valid=result.portal_configuration_valid,
        livemode=result.livemode,
        account_fingerprint=result.account_fingerprint,
    )


# --------------------------------------------------------------------------- catalog
@router.get("/{group_hash}/catalog", response_model=CatalogListResponse)
async def list_catalog(
    group_hash: str,
    item_type: str = Query(None),
    include_archived: bool = Query(False),
    session_data=Depends(require_billing_admin),
) -> CatalogListResponse:
    group = _require_group(group_hash)
    rows = handle_db_operation(
        lambda: db_billing.list_catalog_for_group(
            billing_group_id=group["id"], item_type=item_type, include_archived=include_archived
        ),
        error_context="list catalog",
        default_return=[],
    )
    return CatalogListResponse(success=True, catalog=[_catalog_info(r) for r in rows])


# --------------------------------------------------------------------------- catalog reconcile (pull from Stripe)


def _reconcile_result(report: stripe_catalog_sync.CatalogReconcileReport) -> CatalogReconcileResult:
    return CatalogReconcileResult(
        gated=report.gated,
        error=report.error,
        in_sync=report.in_sync,
        missing_ref_repaired=report.missing_ref_repaired,
        drift=[
            CatalogDriftItem(
                item_hash=d.item_id,
                plan_code=d.plan_code,
                item_type=d.item_type,
                drift_kind=d.drift_kind,
                local_unit_amount=d.local_unit_amount,
                stripe_unit_amount=d.stripe_unit_amount,
                local_interval=d.local_interval,
                stripe_interval=d.stripe_interval,
                price_fingerprint=d.price_fingerprint,
            )
            for d in report.drift
        ],
        candidates=[
            CatalogImportCandidate(
                item_type=c.item_type,
                plan_code=c.plan_code,
                display_name=c.display_name,
                currency=c.currency,
                unit_amount=c.unit_amount,
                recurring_interval=c.recurring_interval,
                lookup_key=c.lookup_key,
                product_fingerprint=c.product_fingerprint,
                price_fingerprint=c.price_fingerprint,
                plan_code_conflict=c.plan_code_conflict,
            )
            for c in report.candidates
        ],
        synced_at=report.synced_at,
    )


@router.get("/{group_hash}/catalog/reconcile", response_model=CatalogReconcileResponse)
async def reconcile_catalog(group_hash: str, session_data=Depends(require_billing_admin)) -> CatalogReconcileResponse:
    """Read-only reconcile: compare the group's local catalog to its Stripe account (no writes)."""
    group = _require_group(group_hash)
    report = handle_db_operation(
        lambda: stripe_catalog_sync.reconcile_catalog_for_group(billing_group_id=group["id"], write=False),
        error_context="reconcile catalog (read-only)",
    )
    return CatalogReconcileResponse(success=report.error is None, result=_reconcile_result(report))


@router.post("/{group_hash}/catalog/sync", response_model=CatalogReconcileResponse)
async def sync_catalog(group_hash: str, session_data=Depends(require_billing_admin)) -> CatalogReconcileResponse:
    """Reconcile and repair: adopt missing provider refs and record the per-group sync status."""
    group = _require_group(group_hash)
    report = handle_db_operation(
        lambda: stripe_catalog_sync.reconcile_catalog_for_group(billing_group_id=group["id"], write=True),
        error_context="reconcile catalog (sync)",
    )
    return CatalogReconcileResponse(success=report.error is None, result=_reconcile_result(report))


@router.post("/{group_hash}/catalog/import", response_model=CatalogImportResponse)
async def import_catalog(
    group_hash: str,
    body: CatalogImportRequest = Body(...),
    session_data=Depends(require_billing_admin),
) -> CatalogImportResponse:
    """Phase B: adopt selected orphan Stripe prices into the local catalog (idempotent)."""
    group = _require_group(group_hash)
    result = handle_db_operation(
        lambda: stripe_catalog_sync.import_selected_candidates(
            billing_group_id=group["id"],
            selected_price_fingerprints=body.price_fingerprints,
            plan_code_overrides=body.plan_code_overrides,
            new_id=_new_id,
            new_hash=_new_hash,
        ),
        error_context="import catalog candidates",
        default_return={"imported": [], "skipped": [], "conflicts": []},
    )
    result = result or {"imported": [], "skipped": [], "conflicts": []}
    return CatalogImportResponse(
        success=True,
        imported=result.get("imported", []),
        skipped=result.get("skipped", []),
        conflicts=result.get("conflicts", []),
    )


def _maybe_provision(group: Mapping[str, Any], item_id: str, item_type: str, display_name: str,
                     currency: str | None, unit_amount: int | None, recurring_interval: str | None,
                     lookup_key: str | None, features: dict | None) -> None:
    """Provision into Stripe when the group is enabled; otherwise leave the row pending."""

    if not stripe_provisioning.provisioning_allowed(group, stripe_config=load_stripe_config()):
        return
    stripe_provisioning.provision_catalog_item(
        billing_group_id=group["id"],
        catalog_item_id=item_id,
        item_type=item_type,
        display_name=display_name,
        currency=currency,
        unit_amount=unit_amount,
        recurring_interval=recurring_interval,
        lookup_key=lookup_key,
        metadata=features,
    )


@router.post("/{group_hash}/catalog", response_model=CatalogItemResponse)
async def create_catalog_item(
    group_hash: str,
    item_type: str = Form(...),
    plan_code: str = Form(...),
    display_name: str = Form(...),
    tier_code: str = Form(None),
    tier_name: str = Form(None),
    amount_cents: int = Form(None),
    currency: str = Form("usd"),
    recurring_interval: str = Form(None),
    lookup_key: str = Form(None),
    features: str = Form(None),
    metadata: str = Form(None),
    sort_order: int = Form(0),
    session_data=Depends(require_billing_admin),
) -> CatalogItemResponse:
    if item_type not in _VALID_ITEM_TYPES:
        raise ValidationError(message="item_type must be subscription_plan or credit_package", error_code=ErrorCode.INVALID_INPUT)
    group = _require_group(group_hash)
    features_obj = _parse_json_object(features, field="features")
    metadata_obj = _parse_json_object(metadata, field="metadata")
    item_id = _new_id("bcat")
    item_hash = _new_hash()
    handle_db_operation(
        lambda: db_billing.create_catalog_item(
            id=item_id,
            catalog_item_hash=item_hash,
            billing_group_id=group["id"],
            provider=group.get("provider") or _PROVIDER,
            item_type=item_type,
            plan_code=plan_code,
            tier_code=tier_code,
            tier_name=tier_name,
            display_name=display_name,
            currency=currency,
            unit_amount=amount_cents,
            recurring_interval=recurring_interval,
            lookup_key=lookup_key,
            features=features_obj,
            metadata=metadata_obj,
            sort_order=sort_order,
            provisioning_idempotency_key_hmac=None,
            created_by=session_data.user_id,
        ),
        error_context="create catalog item",
    )
    _maybe_provision(group, item_id, item_type, display_name, currency, amount_cents, recurring_interval, lookup_key, features_obj)
    return CatalogItemResponse(success=True, message="Catalog item created", item=_catalog_info(_require_catalog_item(item_hash)))


@router.put("/{group_hash}/catalog/{item_hash}", response_model=CatalogItemResponse)
async def update_catalog_item(
    group_hash: str,
    item_hash: str,
    display_name: str = Form(None),
    tier_name: str = Form(None),
    amount_cents: int = Form(None),
    currency: str = Form(None),
    recurring_interval: str = Form(None),
    features: str = Form(None),
    metadata: str = Form(None),
    sort_order: int = Form(None),
    session_data=Depends(require_billing_admin),
) -> CatalogItemResponse:
    group = _require_group(group_hash)
    item = _require_catalog_item(item_hash)
    features_obj = _parse_json_object(features, field="features")
    metadata_obj = _parse_json_object(metadata, field="metadata")
    handle_db_operation(
        lambda: db_billing.update_catalog_item(
            id=item["id"],
            display_name=display_name,
            tier_name=tier_name,
            currency=currency,
            unit_amount=amount_cents,
            recurring_interval=recurring_interval,
            features=features_obj,
            metadata=metadata_obj,
            sort_order=sort_order,
        ),
        error_context="update catalog item",
    )
    # Stripe prices are immutable: a price change rotates to a new Price on the group account.
    price_changed = amount_cents is not None or currency is not None or recurring_interval is not None
    if price_changed and stripe_provisioning.provisioning_allowed(group, stripe_config=load_stripe_config()):
        refreshed = _require_catalog_item(item_hash)
        stripe_provisioning.reprovision_price(
            billing_group_id=group["id"],
            catalog_item_id=item["id"],
            item_type=refreshed.get("item_type"),
            display_name=refreshed.get("display_name"),
            currency=refreshed.get("currency"),
            unit_amount=refreshed.get("unit_amount"),
            recurring_interval=refreshed.get("recurring_interval"),
            lookup_key=refreshed.get("lookup_key"),
        )
    return CatalogItemResponse(success=True, message="Catalog item updated", item=_catalog_info(_require_catalog_item(item_hash)))


@router.post("/{group_hash}/catalog/{item_hash}/archive", response_model=CatalogItemResponse)
async def archive_catalog_item(
    group_hash: str,
    item_hash: str,
    archived: bool = Form(True),
    session_data=Depends(require_billing_admin),
) -> CatalogItemResponse:
    _require_group(group_hash)
    item = _require_catalog_item(item_hash)
    if archived:
        handle_db_operation(lambda: db_billing.archive_catalog_item(id=item["id"]), error_context="archive catalog item")
    else:
        handle_db_operation(lambda: db_billing.set_catalog_item_active(id=item["id"], active=True), error_context="reactivate catalog item")
    return CatalogItemResponse(success=True, item=_catalog_info(_require_catalog_item(item_hash)))


@router.delete("/{group_hash}/catalog/{item_hash}", response_model=BaseResponse)
async def delete_catalog_item(group_hash: str, item_hash: str, session_data=Depends(require_billing_admin)) -> BaseResponse:
    _require_group(group_hash)
    item = _require_catalog_item(item_hash)
    handle_db_operation(lambda: db_billing.archive_catalog_item(id=item["id"]), error_context="delete catalog item")
    return BaseResponse(success=True, message="Catalog item archived")


__all__ = ["router"]
