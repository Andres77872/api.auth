"""Admin billing management routes (dashboard surface).

Manages the centralized billing catalog source of truth: billing groups, per-account
Stripe credentials (write-only, encrypted), group<->project membership, and the catalog of
subscription plans / credit packages. Creating or repricing a catalog item provisions the
Stripe Product/Price on the group's own account.

This is an ADMIN surface authenticated with a user access token (Bearer header or
``session_token`` cookie) carrying the ``admin`` or ``manage_billing`` permission; writing
Stripe credentials additionally requires a root user. It is distinct from the S2S
``internal_billing`` router. It never exposes raw Stripe secrets or operational ids; only
presence flags and non-secret fingerprints are returned. api.auth stays agnostic of product
meaning: ``features``/``metadata`` are opaque JSON passthrough.
"""

from __future__ import annotations

import json
import logging
import secrets
from typing import Annotated, Any, Mapping, Optional

from fastapi import APIRouter, Body, Depends, Form, Path, Query
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
from src.Util.admin_scope import AdminScope, require_admin_scope, require_project_in_scope, resolve_admin_scope
from src.Util.billing.config import load_billing_config
from src.Util.billing.security import decrypt_provider_ref, encrypt_provider_ref, hmac_provider_ref, provider_ref_fingerprint
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


# --------------------------------------------------------------------------- OpenAPI documentation
_GroupHash = Annotated[str, Path(description="`group_hash` of the billing group.")]
_ItemHash = Annotated[str, Path(description="`item_hash` of the catalog item.")]

_AUTH_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"description": "Missing, invalid, or expired access token."},
    403: {
        "description": (
            "The caller is not a root or admin user, the session has neither the `admin` nor the "
            "`manage_billing` permission, or (admin users) the billing group or project is outside "
            "the caller's scope."
        )
    },
}
_ROOT_AUTH_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"description": "Missing, invalid, or expired access token."},
    403: {"description": "The caller is not a root user (or lacks the `admin`/`manage_billing` permission)."},
}
_GROUP_404: dict[int | str, dict[str, Any]] = {404: {"description": "No billing group with this `group_hash`."}}
_ITEM_404: dict[int | str, dict[str, Any]] = {
    404: {"description": "Unknown billing group, or no catalog item with this `item_hash` in that group."}
}


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


async def require_billing_scope(session_data=Depends(require_billing_admin)) -> AdminScope:
    """Billing admin scope: root manages every group, admin users only groups they fully own.

    Consumers have no billing scope even when their global role grants ``admin`` or
    ``manage_billing``: a billing group spans projects and carries a Stripe account, so
    only root and project-assigned admin users may manage one.
    """

    return require_admin_scope(resolve_admin_scope(session_data.user_id))


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


def _group_projects(group: Mapping[str, Any]) -> list[dict[str, Any]]:
    return handle_db_operation(
        lambda: db_billing.list_billing_group_projects(billing_group_id=group["id"]),
        error_context="list billing group projects",
    ) or []


def _group_in_scope(group: Mapping[str, Any], scope: AdminScope) -> bool:
    """Whether ``scope`` fully owns ``group``.

    Root owns every group. An admin user owns a group when every active project attached
    to it is one of its assigned projects; a group with no projects only when the admin
    created it. A group shared with a project the admin does not administer is out of
    scope, so one project's admin cannot change the plans or Stripe account of another's.
    """

    if scope.is_root:
        return True
    projects = _group_projects(group)
    if not projects:
        return str(group.get("owner_id") or "") == scope.user_id
    return scope.allows_all_projects(project.get("project_id") for project in projects)


def _require_scoped_group(group_hash: str, scope: AdminScope) -> dict[str, Any]:
    """Load a billing group the caller fully owns; 404 before 403, as elsewhere."""

    group = _require_group(group_hash)
    if not _group_in_scope(group, scope):
        raise AuthorizationError(
            message="Access denied: billing group not in your administrative scope",
            error_code=ErrorCode.ACCESS_DENIED,
        )
    return group


def _scoped_groups(scope: AdminScope, *, search: str | None) -> list[dict[str, Any]]:
    """Every billing group matching ``search`` that ``scope`` fully owns, newest first."""

    page_size = 500
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        page, total = handle_db_operation(
            lambda: db_billing.list_billing_groups(search=search, limit=page_size, offset=offset),
            error_context="list billing groups",
            default_return=([], 0),
        )
        rows.extend(page)
        offset += page_size
        if len(page) < page_size or offset >= total:
            break
    return [row for row in rows if _group_in_scope(row, scope)]


def _scoped_metrics(groups: list[Mapping[str, Any]]) -> BillingAdminMetrics:
    """``sp_billing_admin_metrics`` restricted to ``groups`` (same counting rules)."""

    counts: dict[str, int] = {}

    def bump(name: str, amount: int = 1) -> None:
        counts[name] = counts.get(name, 0) + amount

    for group in groups:
        bump("groups_total")
        status = str(group.get("status") or "")
        credential_status = str(group.get("credential_status") or "")
        if status in {"active", "suspended", "archived"}:
            bump(f"groups_{status}")
        if credential_status in {"active", "absent", "rotating", "revoked"}:
            bump(f"credentials_{credential_status}")
        has_webhook_secret = bool(group.get("has_webhook_secret"))
        if credential_status == "active" and has_webhook_secret:
            bump("groups_with_webhook_secret")
        if status == "active" and credential_status == "active" and bool(group.get("webhooks_enabled")) and not has_webhook_secret:
            bump("webhook_secret_missing_active_groups")
        bump("projects_mapped", len(_group_projects(group)))
        catalog = handle_db_operation(
            lambda: db_billing.list_catalog_for_group(billing_group_id=group["id"], include_archived=True),
            error_context="list billing group catalog",
        ) or []
        for item in catalog:
            provisioning_status = str(item.get("provisioning_status") or "")
            if provisioning_status in {"active", "pending", "failed", "archived"}:
                bump(f"catalog_{provisioning_status}")
            if provisioning_status != "archived":
                if item.get("item_type") == "subscription_plan":
                    bump("subscription_plans")
                elif item.get("item_type") == "credit_package":
                    bump("credit_packages")
    return BillingAdminMetrics(**counts)


def _require_catalog_item(catalog_item_hash: str, *, group: Mapping[str, Any]) -> dict[str, Any]:
    """Load a catalog item of ``group``; an item of another group is reported as not found.

    Item routes act with the path group's Stripe credentials, so an item of another group
    must never be updated, re-provisioned, or archived through this group's path.
    """
    row = handle_db_operation(
        lambda: db_billing.get_catalog_item_by_hash(catalog_item_hash=catalog_item_hash),
        error_context="get catalog item",
    )
    if not row or str(row.get("billing_group_id") or "") != str(group.get("id") or ""):
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
@router.get("", response_model=ListBillingGroupsResponse, responses=_AUTH_RESPONSES)
async def list_groups(
    limit: int = Query(50, ge=1, le=1000, description="Page size (1-1000)."),
    offset: int = Query(0, ge=0, description="Number of groups to skip."),
    search: str = Query(None, description="Substring to match against the group name or `group_hash`."),
    scope: AdminScope = Depends(require_billing_scope),
) -> ListBillingGroupsResponse:
    """List billing groups, newest first, with optional search and offset pagination.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or `session_token` cookie)
    of a root or admin user whose session has the `admin` or `manage_billing` permission;
    consumers get `403` whatever their global role grants. Root sees every group. Admin
    users see only the groups they fully own: every active project attached to the group
    is one of their assigned projects, or the group has no projects and they created it.

    **Responses:**
    - `200`: `billing_groups` plus `pagination`. Each row carries the same group fields as
      `GET /admin/billing/{group_hash}`, including the four capability flags,
      `has_webhook_secret`, `catalog_sync_status`, and `last_catalog_synced_at`.
    - A database failure returns an empty list instead of an error.
    """
    if scope.is_root:
        rows, total = handle_db_operation(
            lambda: db_billing.list_billing_groups(search=search, limit=limit, offset=offset),
            error_context="list billing groups",
            default_return=([], 0),
        )
    else:
        owned = _scoped_groups(scope, search=search)
        rows, total = owned[offset:offset + limit], len(owned)
    return ListBillingGroupsResponse(
        success=True,
        billing_groups=[_group_info(r) for r in rows],
        pagination=PaginationInfo(limit=limit, offset=offset, total=total, has_more=offset + limit < total),
    )


@router.post(
    "",
    response_model=BillingGroupResponse,
    responses={
        **_AUTH_RESPONSES,
        400: {"description": "`provider` is not `stripe`, or the form failed validation."},
        503: {"description": "The `stripe` provider is missing from the billing provider registry (schema not seeded)."},
    },
)
async def create_group(
    group_name: str = Form(..., description="Display name of the group (up to 120 characters)."),
    description: str = Form(None, description="Optional free-text description."),
    provider: str = Form(_PROVIDER, description="Billing provider. Only `stripe` is supported."),
    scope: AdminScope = Depends(require_billing_scope),
) -> BillingGroupResponse:
    """Create a billing group owned by the caller, with no Stripe credentials and every capability off.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or `session_token` cookie)
    of a root or admin user whose session has the `admin` or `manage_billing` permission;
    consumers get `403`. An admin user keeps managing the new group only while every
    project attached to it is one of its assigned projects.

    **Request:** form fields (`application/x-www-form-urlencoded` or `multipart/form-data`).

    **Responses:** `200` with the new group (`status` `active`, `credential_status` `absent`).
    Next steps are setting credentials (root only), attaching projects, building the catalog,
    and enabling capabilities.
    """
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
            owner_id=scope.user_id,
            provider=provider_code,
            created_by=scope.user_id,
        ),
        error_context="create billing group",
    )
    return BillingGroupResponse(success=True, message="Billing group created", billing_group=_group_info(_require_group(group_hash)))


@router.get("/metrics", response_model=BillingAdminMetricsResponse, responses=_AUTH_RESPONSES)
async def get_metrics(scope: AdminScope = Depends(require_billing_scope)) -> BillingAdminMetricsResponse:
    """Return aggregate billing counts for the admin dashboard.

    Counts cover groups by status, credential states, catalog items by type and provisioning
    state, mapped projects, and webhook-secret coverage. No secrets or per-user data.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or `session_token` cookie)
    of a root or admin user whose session has the `admin` or `manage_billing` permission;
    consumers get `403`. Root gets platform-wide counts; admin users get counts over the
    groups they fully own (the groups `GET /admin/billing` lists for them).

    **Responses:** `200` with `metrics`. A database failure returns all-zero counts instead of
    an error.
    \f
    Registered before ``/{group_hash}`` so the literal ``metrics`` path is not captured as a
    group hash. Counts only — agnostic of product meaning, no secrets.
    """

    if not scope.is_root:
        return BillingAdminMetricsResponse(success=True, metrics=_scoped_metrics(_scoped_groups(scope, search=None)))
    row = handle_db_operation(
        lambda: db_billing.get_billing_admin_metrics(),
        error_context="get billing admin metrics",
        default_return={},
    )
    return BillingAdminMetricsResponse(success=True, metrics=BillingAdminMetrics(**(row or {})))


@router.get("/{group_hash}", response_model=BillingGroupDetailsResponse, responses={**_AUTH_RESPONSES, **_GROUP_404})
async def get_group(group_hash: _GroupHash, scope: AdminScope = Depends(require_billing_scope)) -> BillingGroupDetailsResponse:
    """Return one billing group with its projects, full catalog, credential status, and readiness.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or `session_token` cookie)
    of a root or admin user whose session has the `admin` or `manage_billing` permission;
    consumers get `403`. Admin users only reach groups they fully own (every active project
    attached is one of their assigned projects, or an empty group they created); other
    groups return `403`.

    **Responses:** `200` with:
    - `projects`: currently attached projects; `catalog`: every item, archived ones included.
    - `credentials`: presence flags and fingerprints only, never secret values.
    - `readiness`: `missing` lists unmet prerequisites for checkout, portal, and webhooks,
      as global flag names (for example `BILLING_ENABLED`, `STRIPE_WEBHOOKS_ENABLED`) and group
      prerequisites (`billing_group_active`, `billing_group_credentials_active`,
      `stripe_secret_key`, `active_catalog_price`, `stripe_portal_configuration_id`,
      `stripe_webhook_secret`). `webhook_endpoint_path` is the per-group Stripe webhook path
      to register in the group's Stripe account.
    - `billing_group.catalog_sync_status` and `last_catalog_synced_at` record the last
      `POST .../catalog/sync`: `never` until the first sync, then `ok` or `drift`.
    """
    group = _require_scoped_group(group_hash, scope)
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


@router.put("/{group_hash}", response_model=BillingGroupResponse, responses={**_AUTH_RESPONSES, **_GROUP_404})
async def update_group(
    group_hash: _GroupHash,
    group_name: str = Form(None, description="New display name (up to 120 characters)."),
    description: str = Form(None, description="New description."),
    status: str = Form(None, description="`active`, `suspended`, or `archived`."),
    scope: AdminScope = Depends(require_billing_scope),
) -> BillingGroupResponse:
    """Update a billing group's name, description, or status.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or `session_token` cookie)
    of a root or admin user whose session has the `admin` or `manage_billing` permission;
    consumers get `403`. Admin users only reach groups they fully own (every active project
    attached is one of their assigned projects, or an empty group they created); other
    groups return `403`.

    **Request:** form fields; omitted or empty fields keep their current value, so a
    description cannot be cleared. `status` is not validated here: a value other than
    `active`, `suspended`, or `archived` fails in the database with `500`. While a group is
    not `active`, the database forces all four capability flags off.

    **Responses:** `200` with the updated group.
    """
    group = _require_scoped_group(group_hash, scope)
    handle_db_operation(
        lambda: db_billing.update_billing_group(id=group["id"], name=group_name, description=description, status=status),
        error_context="update billing group",
    )
    return BillingGroupResponse(success=True, message="Billing group updated", billing_group=_group_info(_require_group(group_hash)))


@router.put(
    "/{group_hash}/capabilities",
    response_model=BillingGroupResponse,
    responses={
        **_AUTH_RESPONSES,
        **_GROUP_404,
        400: {
            "description": (
                "A prerequisite for a capability being turned on is missing (`details.missing`, "
                "`details.capability`), or the body failed validation."
            )
        },
    },
)
async def update_capabilities(
    group_hash: _GroupHash,
    body: BillingCapabilitiesUpdate = Body(
        ..., description="Capability flags to change; omitted or null flags keep their current value."
    ),
    scope: AdminScope = Depends(require_billing_scope),
) -> BillingGroupResponse:
    """Turn a billing group's checkout, portal, provisioning, and webhooks capabilities on or off.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or `session_token` cookie)
    of a root or admin user whose session has the `admin` or `manage_billing` permission;
    consumers get `403`. Admin users only reach groups they fully own (every active project
    attached is one of their assigned projects, or an empty group they created); other
    groups return `403`.

    **Request:** JSON. Turning a flag off is always allowed. Turning one on checks, for that
    capability only:
    - every capability: `BILLING_ENABLED` and `STRIPE_BILLING_ENABLED` on, group `status`
      `active`, `credential_status` `active`;
    - checkout: `BILLING_CHECKOUT_ENABLED` and `STRIPE_CHECKOUT_ENABLED` on, a stored secret
      key, and at least one active, provisioned catalog price;
    - portal: `BILLING_PORTAL_ENABLED` and `STRIPE_PORTAL_ENABLED` on, a stored secret key, and
      a stored portal configuration id;
    - webhooks: `STRIPE_WEBHOOKS_ENABLED` on, a stored secret key, and a stored webhook secret.

    **Responses:** `200` with the updated group. The database also forces every flag off
    while the group or its credentials are not `active`.
    """
    group = _require_scoped_group(group_hash, scope)
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


@router.delete(
    "/{group_hash}",
    response_model=BaseResponse,
    responses={
        **_AUTH_RESPONSES,
        **_GROUP_404,
        409: {
            "description": (
                "The group has a subscription in `trialing`, `active`, `past_due`, `unpaid`, or "
                "`paused` status. Any other database failure during the delete is also reported as 409."
            )
        },
    },
)
async def delete_group(group_hash: _GroupHash, scope: AdminScope = Depends(require_billing_scope)) -> BaseResponse:
    """Permanently delete a billing group.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or `session_token` cookie)
    of a root or admin user whose session has the `admin` or `manage_billing` permission;
    consumers get `403`. Admin users only reach groups they fully own (every active project
    attached is one of their assigned projects, or an empty group they created); other
    groups return `403`.

    **Responses:** `200` when deleted. The delete cascades to the group's project mappings,
    catalog items, Stripe customers, subscription and purchase history, checkout intents, and
    webhook delivery records. Nothing is changed in the Stripe account.
    """
    group = _require_scoped_group(group_hash, scope)
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
            error_code=ErrorCode.STATE_CONFLICT,
        ) from exc
    return BaseResponse(success=True, message="Billing group deleted")


# --------------------------------------------------------------------------- projects
@router.get("/{group_hash}/projects", response_model=BillingGroupProjectsResponse, responses={**_AUTH_RESPONSES, **_GROUP_404})
async def list_group_projects(group_hash: _GroupHash, scope: AdminScope = Depends(require_billing_scope)) -> BillingGroupProjectsResponse:
    """List the projects currently attached to a billing group, most recently attached first.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or `session_token` cookie)
    of a root or admin user whose session has the `admin` or `manage_billing` permission;
    consumers get `403`. Admin users only reach groups they fully own (every active project
    attached is one of their assigned projects, or an empty group they created); other
    groups return `403`.

    **Responses:** `200` with `projects`; detached projects are omitted. A database failure
    returns an empty list.
    """
    group = _require_scoped_group(group_hash, scope)
    projects = handle_db_operation(
        lambda: db_billing.list_billing_group_projects(billing_group_id=group["id"]),
        error_context="list billing group projects",
        default_return=[],
    )
    return BillingGroupProjectsResponse(success=True, projects=[_project_info(p) for p in projects])


@router.post(
    "/{group_hash}/projects",
    response_model=AttachProjectToBillingGroupResponse,
    responses={
        **_AUTH_RESPONSES,
        404: {"description": "Unknown billing group or project."},
        409: {
            "description": (
                "The project is actively attached to another billing group. Any other database "
                "failure is also reported as 409."
            )
        },
    },
)
async def attach_project(
    group_hash: _GroupHash,
    project_hash: str = Form(..., description="`project_hash` of the project to attach."),
    scope: AdminScope = Depends(require_billing_scope),
) -> AttachProjectToBillingGroupResponse:
    """Attach a project to a billing group.

    The project's users then resolve to this group's Stripe account and catalog for status,
    catalog, Checkout, and Portal calls.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or `session_token` cookie)
    of a root or admin user whose session has the `admin` or `manage_billing` permission;
    consumers get `403`. Admin users only reach groups they fully own (every active project
    attached is one of their assigned projects, or an empty group they created); other
    groups return `403`.

    **Request:** form field `project_hash`. A project belongs to at most one group at a time.
    Re-attaching it to the same group, or attaching a previously detached project, succeeds.
    Admin users may only attach projects they are assigned to administer.

    **Responses:** `200` with the attached project; `403` project outside the admin's scope.
    """
    group = _require_scoped_group(group_hash, scope)
    project = handle_db_operation(lambda: get_project_by_hash(project_hash), error_context="resolve project")
    if not project:
        raise NotFoundError(message="Project not found", error_code=ErrorCode.RESOURCE_NOT_FOUND)
    require_project_in_scope(scope, project)
    try:
        row = handle_db_operation(
            lambda: db_billing.attach_project_to_billing_group(
                id=_new_id("bgp"), billing_group_id=group["id"], project_id=project.id, added_by=scope.user_id
            ),
            error_context="attach project to billing group",
        )
    except (ConflictError, NotFoundError):
        raise
    except Exception as exc:  # SIGNAL: project already attached to another group
        raise ConflictError(
            message="Project is already attached to another billing group",
            error_code=ErrorCode.STATE_CONFLICT,
        ) from exc
    return AttachProjectToBillingGroupResponse(
        success=True,
        message="Project attached",
        project=_project_info(row) if row else None,
    )


@router.delete(
    "/{group_hash}/projects/{project_hash}",
    response_model=BaseResponse,
    responses={**_AUTH_RESPONSES, 404: {"description": "Unknown billing group or project."}},
)
async def detach_project(
    group_hash: _GroupHash,
    project_hash: Annotated[str, Path(description="`project_hash` of the project to detach.")],
    scope: AdminScope = Depends(require_billing_scope),
) -> BaseResponse:
    """Detach a project from its billing group.

    The mapping is kept with status `removed`; the project's users then fall back to the
    free default in billing reads.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or `session_token` cookie)
    of a root or admin user whose session has the `admin` or `manage_billing` permission;
    consumers get `403`. Admin users only reach groups they fully own (every active project
    attached is one of their assigned projects, or an empty group they created); other
    groups return `403`.

    **Responses:** `200`, also when the project had no active mapping. The project is
    detached from whichever group currently holds it: `group_hash` is only checked for
    existence and scope, not matched against the project's group. `403` when an admin user
    does not administer the project.
    """
    _require_scoped_group(group_hash, scope)
    project = handle_db_operation(lambda: get_project_by_hash(project_hash), error_context="resolve project")
    if not project:
        raise NotFoundError(message="Project not found", error_code=ErrorCode.RESOURCE_NOT_FOUND)
    require_project_in_scope(scope, project)
    handle_db_operation(
        lambda: db_billing.detach_project_from_billing_group(project_id=project.id, removed_by=scope.user_id),
        error_context="detach project from billing group",
    )
    return BaseResponse(success=True, message="Project detached")


# --------------------------------------------------------------------------- credentials (writes are root only)
@router.get("/{group_hash}/credentials", response_model=BillingCredentialsStatusResponse, responses={**_AUTH_RESPONSES, **_GROUP_404})
async def get_credentials(group_hash: _GroupHash, scope: AdminScope = Depends(require_billing_scope)) -> BillingCredentialsStatusResponse:
    """Return the status of a billing group's Stripe credentials without any secret values.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or `session_token` cookie)
    of a root or admin user whose session has the `admin` or `manage_billing` permission;
    consumers get `403`. Admin users only reach groups they fully own (every active project
    attached is one of their assigned projects, or an empty group they created); other
    groups return `403`. Reading the status does not require root.

    **Responses:** `200` with `credential_status`, `has_secret_key`, `has_webhook_secret`,
    key fingerprints, `stripe_account_label`, `credential_key_id`, and `credentials_set_at`.
    `stripe_account_fingerprint` is a fingerprint of the Stripe account id the secret key
    authenticated as when the credentials were last saved; credentials saved before this was
    fixed hold the secret-key fingerprint until they are saved again.
    """
    group = _require_scoped_group(group_hash, scope)
    return BillingCredentialsStatusResponse(success=True, credentials=_credentials_status(group))


_OPTIONAL_CREDENTIAL_COLUMNS = {
    "webhook_secret": "stripe_webhook_secret_ciphertext",
    "portal_configuration_id": "stripe_portal_configuration_id_ciphertext",
}


def _kept_or_sent(sent: str | None, stored: str | None) -> str | None:
    """Omitted/null keeps the stored value; an empty string clears it."""
    if sent is None:
        return stored
    return sent.strip() or None


def _stored_optional_credentials(group: Mapping[str, Any], *, omitted: list[str], config: Any) -> dict[str, str | None]:
    """Decrypt the stored optional secrets a save omitted, so they can be kept under the active key.

    The whole credential set shares one ``credential_key_id``, so a kept value is re-encrypted
    rather than left as old ciphertext. Fails closed when a stored value cannot be decrypted.
    """
    if not omitted or str(group.get("credential_status") or "absent") == "absent":
        return {}
    row = handle_db_operation(
        lambda: db_billing.get_billing_group_operational_credentials(id=group["id"]),
        error_context="get billing group credentials",
    ) or {}
    stored: dict[str, str | None] = {}
    for field in omitted:
        ciphertext = row.get(_OPTIONAL_CREDENTIAL_COLUMNS[field])
        if ciphertext is None or (isinstance(ciphertext, (bytes, bytearray, memoryview)) and len(bytes(ciphertext)) == 0):
            continue
        try:
            stored[field] = decrypt_provider_ref(
                ciphertext=ciphertext,
                key_id=row.get("credential_key_id"),
                keys_by_id=getattr(config, "decryption_keys_by_id", {}) or {},
            )
        except Exception as exc:
            raise ValidationError(
                message=(
                    f"The stored {field} cannot be decrypted with the configured keys; "
                    "send it again, or send an empty string to clear it"
                ),
                error_code=ErrorCode.INVALID_INPUT,
            ) from exc
    return stored


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

    stored = _stored_optional_credentials(
        group,
        omitted=[field for field in _OPTIONAL_CREDENTIAL_COLUMNS if getattr(body, field) is None],
        config=config,
    )
    webhook_secret = _kept_or_sent(body.webhook_secret, stored.get("webhook_secret"))
    portal_configuration_id = _kept_or_sent(body.portal_configuration_id, stored.get("portal_configuration_id"))
    account_label = _kept_or_sent(body.stripe_account_label, group.get("stripe_account_label"))
    effective = body.model_copy(update={"webhook_secret": webhook_secret, "portal_configuration_id": portal_configuration_id})

    # Confirm the credentials are actually correct before we encrypt + store them: format checks,
    # a live auth probe against Stripe, and the portal config that will be stored (sent or kept).
    # Fail-closed — raises ValidationError (400) on any failure, never leaking key material.
    validation = validate_stripe_credentials(effective)

    def _enc(raw: str, kind: str):
        encrypted = encrypt_provider_ref(raw_ref=raw, key=key, key_id=key_id, provider=_PROVIDER)
        digest = hmac_provider_ref(provider=_PROVIDER, kind=kind, raw_id=raw, secret=hmac_secret)
        return encrypted.ciphertext, digest, provider_ref_fingerprint(digest=digest)

    secret_ct, secret_hmac, secret_fp = _enc(body.secret_key, "account_secret_key")
    webhook_ct = webhook_hmac = webhook_fp = None
    if webhook_secret:
        webhook_ct, webhook_hmac, webhook_fp = _enc(webhook_secret, "account_webhook_secret")
    portal_ct = None
    if portal_configuration_id:
        portal_ct = encrypt_provider_ref(raw_ref=portal_configuration_id, key=key, key_id=key_id, provider=_PROVIDER).ciphertext

    handle_db_operation(
        lambda: db_billing.set_billing_group_credentials(
            id=group["id"],
            stripe_account_label=account_label,
            stripe_account_fingerprint=validation.account_fingerprint,
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


_CREDENTIALS_WRITE_RESPONSES: dict[int | str, dict[str, Any]] = {
    **_ROOT_AUTH_RESPONSES,
    **_GROUP_404,
    400: {
        "description": (
            "Credentials failed validation or could not be verified with Stripe (redacted message), "
            "the server's billing encryption keys are not configured, or the body failed validation."
        )
    },
}
_CREDENTIALS_TEST_RESPONSES: dict[int | str, dict[str, Any]] = {
    **_ROOT_AUTH_RESPONSES,
    **_GROUP_404,
    400: {
        "description": (
            "Credentials failed validation or could not be verified with Stripe (redacted message), "
            "or the body failed validation."
        )
    },
}
_CREDENTIALS_BODY_DESCRIPTION = (
    "Write-only Stripe credentials: `secret_key` (`sk_`/`rk_`, required), optional `webhook_secret` "
    "(`whsec_`), `portal_configuration_id` (`bpc_`), and `stripe_account_label`. An omitted or null "
    "optional field keeps its stored value; an empty string clears it."
)


@router.put("/{group_hash}/credentials", response_model=BillingCredentialsStatusResponse, responses=_CREDENTIALS_WRITE_RESPONSES)
async def set_credentials(
    group_hash: _GroupHash,
    body: StripeAccountCredentialsUpdate = Body(..., description=_CREDENTIALS_BODY_DESCRIPTION),
    session_data=Depends(require_billing_root),
) -> BillingCredentialsStatusResponse:
    """Verify a billing group's Stripe credentials with Stripe, then store them encrypted and mark them `active`.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or `session_token` cookie)
    of a root user; other admins get `403`.

    **Request:** JSON (never form, so secrets stay out of form logs). `secret_key` is always
    replaced. For `webhook_secret`, `portal_configuration_id`, and `stripe_account_label`, an
    omitted or null field keeps the stored value and an empty string clears it. Kept secrets
    are re-encrypted under the current encryption key; if a stored secret cannot be decrypted
    the call fails with `400` and must resend or clear it. Secret fields are write-only and
    never echoed back.

    **Validation:** prefix checks, a live Stripe call authenticated with `secret_key`, and, when
    a portal configuration id will be stored (sent or kept), a check that it exists in that
    Stripe account and meets the restricted-portal contract. A kept webhook secret is not
    checked against Stripe. If Stripe cannot be reached the call fails.

    **Responses:** `200` with presence flags and fingerprints only; `stripe_account_fingerprint`
    identifies the Stripe account `secret_key` authenticated as.
    """
    return _apply_credentials(group_hash, body)


@router.post("/{group_hash}/credentials/rotate", response_model=BillingCredentialsStatusResponse, responses=_CREDENTIALS_WRITE_RESPONSES)
async def rotate_credentials(
    group_hash: _GroupHash,
    body: StripeAccountCredentialsUpdate = Body(..., description=_CREDENTIALS_BODY_DESCRIPTION),
    session_data=Depends(require_billing_root),
) -> BillingCredentialsStatusResponse:
    """Replace a billing group's Stripe credentials; behaves exactly like `PUT .../credentials`.

    Same validation, encryption, and keep-or-clear semantics: omitted or null optional fields
    keep their stored values (re-encrypted under the current key), empty strings clear them.
    `credential_status` goes straight to `active`; there is no intermediate rotating state and
    the previous secret key is not kept.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or `session_token` cookie)
    of a root user; other admins get `403`.

    **Request:** JSON; secret fields are write-only and never echoed back.

    **Responses:** `200` with presence flags and fingerprints only.
    """
    return _apply_credentials(group_hash, body)


@router.post("/{group_hash}/credentials/test", response_model=CredentialValidationResponse, responses=_CREDENTIALS_TEST_RESPONSES)
async def test_credentials(
    group_hash: _GroupHash,
    body: StripeAccountCredentialsUpdate = Body(..., description=_CREDENTIALS_BODY_DESCRIPTION),
    session_data=Depends(require_billing_root),
) -> CredentialValidationResponse:
    """Check Stripe credentials against Stripe without saving them (a "test connection").

    **Auth:** access token (`Authorization: Bearer <access JWT>` or `session_token` cookie)
    of a root user; other admins get `403`.

    **Request:** the same JSON body as `PUT .../credentials`, with the same prefix checks,
    live Stripe call, and optional portal-configuration check. Nothing is stored.

    **Responses:** `200` with `valid`, `secret_key_valid`, `portal_configuration_valid` (null
    when no portal id was sent), `livemode`, and `account_fingerprint`; never secrets. Invalid
    or unverifiable credentials return `400` with a redacted message.
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
@router.get("/{group_hash}/catalog", response_model=CatalogListResponse, responses={**_AUTH_RESPONSES, **_GROUP_404})
async def list_catalog(
    group_hash: _GroupHash,
    item_type: str = Query(None, description="Filter by `subscription_plan` or `credit_package`; omit for both."),
    include_archived: bool = Query(False, description="Also return archived items."),
    scope: AdminScope = Depends(require_billing_scope),
) -> CatalogListResponse:
    """List a billing group's catalog items, ordered by item type, sort order, and creation time.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or `session_token` cookie)
    of a root or admin user whose session has the `admin` or `manage_billing` permission;
    consumers get `403`. Admin users only reach groups they fully own (every active project
    attached is one of their assigned projects, or an empty group they created); other
    groups return `403`.

    **Responses:** `200` with `catalog`. Items carry a Stripe price fingerprint, never raw
    Stripe ids; `features` and `metadata` are returned as stored. A database failure returns an
    empty list.
    """
    group = _require_scoped_group(group_hash, scope)
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


@router.get("/{group_hash}/catalog/reconcile", response_model=CatalogReconcileResponse, responses={**_AUTH_RESPONSES, **_GROUP_404})
async def reconcile_catalog(group_hash: _GroupHash, scope: AdminScope = Depends(require_billing_scope)) -> CatalogReconcileResponse:
    """Compare the group's local catalog with the active prices in its Stripe account, without writing anything.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or `session_token` cookie)
    of a root or admin user whose session has the `admin` or `manage_billing` permission;
    consumers get `403`. Admin users only reach groups they fully own (every active project
    attached is one of their assigned projects, or an empty group they created); other
    groups return `403`.

    **Responses:** `200` whenever the group exists. `result` holds:
    - `in_sync`: items whose stored price matches Stripe;
    - `drift`: items that diverge (`drift_kind` `amount_mismatch`, `interval_mismatch`, or
      `unresolved` when a provisioned item's price is not among the account's active prices);
    - `candidates`: active Stripe prices with no local item, for `POST .../catalog/import`;
    - `missing_ref_repaired`: always `0` here (see `POST .../catalog/sync`).

    `success` is `false` when `result.error` is set. `result.gated` is `true` with error
    `billing_disabled` when `BILLING_ENABLED` is off, or `account_not_ready` when the group's
    credentials are not active or cannot be decrypted. Stripe read failures set `error` without
    `gated`.
    """
    group = _require_scoped_group(group_hash, scope)
    report = handle_db_operation(
        lambda: stripe_catalog_sync.reconcile_catalog_for_group(billing_group_id=group["id"], write=False),
        error_context="reconcile catalog (read-only)",
    )
    return CatalogReconcileResponse(success=report.error is None, result=_reconcile_result(report))


@router.post("/{group_hash}/catalog/sync", response_model=CatalogReconcileResponse, responses={**_AUTH_RESPONSES, **_GROUP_404})
async def sync_catalog(group_hash: _GroupHash, scope: AdminScope = Depends(require_billing_scope)) -> CatalogReconcileResponse:
    """Run the catalog reconcile and apply its safe repairs.

    Local items that match a Stripe price by lookup key but lack (or have stale) stored Stripe
    references adopt that price and become provisioned. The group's catalog sync status (`ok`
    or `drift`) and timestamp are recorded, only when the Stripe read succeeded. Local prices
    and plan codes are never overwritten from Stripe, and nothing is created in Stripe.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or `session_token` cookie)
    of a root or admin user whose session has the `admin` or `manage_billing` permission;
    consumers get `403`. Admin users only reach groups they fully own (every active project
    attached is one of their assigned projects, or an empty group they created); other
    groups return `403`.

    **Request:** no body.

    **Responses:** `200` with the same shape as `GET .../catalog/reconcile`, where
    `missing_ref_repaired` counts the adopted references.
    """
    group = _require_scoped_group(group_hash, scope)
    report = handle_db_operation(
        lambda: stripe_catalog_sync.reconcile_catalog_for_group(billing_group_id=group["id"], write=True),
        error_context="reconcile catalog (sync)",
    )
    return CatalogReconcileResponse(success=report.error is None, result=_reconcile_result(report))


@router.post("/{group_hash}/catalog/import", response_model=CatalogImportResponse, responses={**_AUTH_RESPONSES, **_GROUP_404})
async def import_catalog(
    group_hash: _GroupHash,
    body: CatalogImportRequest = Body(
        ...,
        description=(
            "`price_fingerprints`: candidate `price_fingerprint` values from the reconcile result; "
            "`plan_code_overrides`: optional map of price fingerprint to plan code."
        ),
    ),
    scope: AdminScope = Depends(require_billing_scope),
) -> CatalogImportResponse:
    """Import selected Stripe prices (reconcile `candidates`) into the group's catalog as active, provisioned items.

    Without an override, the plan code is the price's lookup key, else the product's
    `plan_code` metadata, else a slug of the product name. Recurring prices become
    `subscription_plan` items, one-time prices `credit_package` items.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or `session_token` cookie)
    of a root or admin user whose session has the `admin` or `manage_billing` permission;
    consumers get `403`. Admin users only reach groups they fully own (every active project
    attached is one of their assigned projects, or an empty group they created); other
    groups return `403`.

    **Responses:** `200` with `imported` and `conflicts` (plan codes already active in the
    group) and `skipped` (fingerprints that are not active Stripe prices, have no derivable
    plan code, or failed to insert). A price already in the catalog is never inserted twice.
    If billing is disabled, the group's Stripe account is not ready, encryption keys are
    missing, or Stripe fails, the response is still `200` with empty lists.
    """
    group = _require_scoped_group(group_hash, scope)
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


@router.post(
    "/{group_hash}/catalog",
    response_model=CatalogItemResponse,
    responses={
        **_AUTH_RESPONSES,
        **_GROUP_404,
        400: {"description": "Invalid `item_type`, `features`/`metadata` that is not a JSON object, or a form that failed validation."},
    },
)
async def create_catalog_item(
    group_hash: _GroupHash,
    item_type: str = Form(..., description="`subscription_plan` or `credit_package`. Cannot be changed later."),
    plan_code: str = Form(..., description="Plan or credit product code. Only one active item per group may use it; cannot be changed later."),
    display_name: str = Form(..., description="Name shown to buyers; also used as the Stripe Product name."),
    tier_code: str = Form(None, description="Optional consumer-defined tier code; not accepted by the update endpoint."),
    tier_name: str = Form(None, description="Optional tier display name."),
    amount_cents: int = Form(None, description="Price in the currency's minor unit (for example cents). Required for Stripe provisioning."),
    currency: str = Form("usd", description="Three-letter ISO currency code."),
    recurring_interval: str = Form(None, description="`day`, `week`, `month`, or `year`. Used for subscription plans only."),
    lookup_key: str = Form(None, description="Optional Stripe price lookup key; provisioning transfers it onto the new price. Not accepted by the update endpoint."),
    features: str = Form(None, description="Opaque JSON object, as a string, passed through to consumers. `features.credits` is surfaced as `credits` in the S2S catalog."),
    metadata: str = Form(None, description="Opaque JSON object, as a string; stored and returned to admins only."),
    sort_order: int = Form(0, description="Display order within the item type."),
    scope: AdminScope = Depends(require_billing_scope),
) -> CatalogItemResponse:
    """Create a catalog item (subscription plan or credit package) and, when allowed, provision it into Stripe.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or `session_token` cookie)
    of a root or admin user whose session has the `admin` or `manage_billing` permission;
    consumers get `403`. Admin users only reach groups they fully own (every active project
    attached is one of their assigned projects, or an empty group they created); other
    groups return `403`.

    **Request:** form fields. Values outside the database constraints (for example an unknown
    `recurring_interval` or a currency longer than three letters) are not validated here and
    fail with `500`.

    **Provisioning:** when `BILLING_ENABLED` is on and the group has `provisioning_enabled` with
    `active` credentials, a Stripe Product and Price are created synchronously on the group's
    own Stripe account and the item becomes active. Otherwise the item is saved `pending` and
    inactive.

    **Responses:** `200` with the item. Stripe or provisioning failures do not fail the
    request: the item comes back with `provisioning_status` `failed` and a redacted
    `provisioning_error` (also when `amount_cents` or `currency` is missing). A duplicate
    `plan_code` is not rejected at creation; its provisioning fails because only one active
    item per plan code is allowed.
    """
    if item_type not in _VALID_ITEM_TYPES:
        raise ValidationError(message="item_type must be subscription_plan or credit_package", error_code=ErrorCode.INVALID_INPUT)
    group = _require_scoped_group(group_hash, scope)
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
            created_by=scope.user_id,
        ),
        error_context="create catalog item",
    )
    _maybe_provision(group, item_id, item_type, display_name, currency, amount_cents, recurring_interval, lookup_key, features_obj)
    return CatalogItemResponse(success=True, message="Catalog item created", item=_catalog_info(_require_catalog_item(item_hash, group=group)))


@router.put(
    "/{group_hash}/catalog/{item_hash}",
    response_model=CatalogItemResponse,
    responses={
        **_AUTH_RESPONSES,
        **_ITEM_404,
        400: {"description": "`features`/`metadata` is not a JSON object, or the form failed validation."},
    },
)
async def update_catalog_item(
    group_hash: _GroupHash,
    item_hash: _ItemHash,
    display_name: str = Form(None, description="New display name."),
    tier_name: str = Form(None, description="New tier display name."),
    amount_cents: int = Form(None, description="New price in the currency's minor unit; triggers a Stripe price rotation."),
    currency: str = Form(None, description="New three-letter ISO currency code; triggers a Stripe price rotation."),
    recurring_interval: str = Form(None, description="New interval (`day`, `week`, `month`, `year`); triggers a Stripe price rotation."),
    features: str = Form(None, description="Replacement opaque JSON object, as a string."),
    metadata: str = Form(None, description="Replacement opaque JSON object, as a string."),
    sort_order: int = Form(None, description="New display order within the item type."),
    scope: AdminScope = Depends(require_billing_scope),
) -> CatalogItemResponse:
    """Update a catalog item's display fields, price, or opaque JSON; omitted fields keep their current value.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or `session_token` cookie)
    of a root or admin user whose session has the `admin` or `manage_billing` permission;
    consumers get `403`. Admin users only reach groups they fully own (every active project
    attached is one of their assigned projects, or an empty group they created); other
    groups return `403`.

    **Request:** form fields. `item_type`, `plan_code`, `tier_code`, and `lookup_key` cannot
    be changed. The item must belong to `group_hash`; an item of another group is `404`.

    **Stripe:** prices are immutable in Stripe. When `amount_cents`, `currency`, or
    `recurring_interval` is sent (even unchanged) and provisioning is allowed for the group,
    a new Price is created on the item's existing Stripe Product and the old Price is
    deactivated once the new one is stored. Repricing again right away works too. If the new
    Price cannot be created, the item becomes `failed` (inactive, with a redacted
    `provisioning_error`) while the old Price stays active in Stripe; sending the price again
    retries. When provisioning is not allowed the change is local only and Stripe keeps the
    old price, which reconcile reports as drift. Other fields never reach Stripe.

    **Responses:** `200` with the updated item.
    """
    group = _require_scoped_group(group_hash, scope)
    item = _require_catalog_item(item_hash, group=group)
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
        refreshed = _require_catalog_item(item_hash, group=group)
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
    return CatalogItemResponse(success=True, message="Catalog item updated", item=_catalog_info(_require_catalog_item(item_hash, group=group)))


@router.post("/{group_hash}/catalog/{item_hash}/archive", response_model=CatalogItemResponse, responses={**_AUTH_RESPONSES, **_ITEM_404})
async def archive_catalog_item(
    group_hash: _GroupHash,
    item_hash: _ItemHash,
    archived: bool = Form(True, description="`true` archives the item; `false` only sets it active again."),
    scope: AdminScope = Depends(require_billing_scope),
) -> CatalogItemResponse:
    """Archive a catalog item, or set it active again with `archived=false`.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or `session_token` cookie)
    of a root or admin user whose session has the `admin` or `manage_billing` permission;
    consumers get `403`. Admin users only reach groups they fully own (every active project
    attached is one of their assigned projects, or an empty group they created); other
    groups return `403`.

    **Request:** form field `archived` (default `true`). The item must belong to `group_hash`;
    an item of another group is `404`.
    - `archived=true`: `provisioning_status` becomes `archived` and the item inactive, which
      removes it from the S2S catalog.
    - `archived=false`: sets `active` to true and leaves `provisioning_status` unchanged, so an
      archived item stays archived and hidden. It does activate a provisioned but inactive
      item, such as one whose Stripe references were adopted by `POST .../catalog/sync`.

    **Responses:** `200` with the item. Nothing is changed in Stripe.
    """
    group = _require_scoped_group(group_hash, scope)
    item = _require_catalog_item(item_hash, group=group)
    if archived:
        handle_db_operation(lambda: db_billing.archive_catalog_item(id=item["id"]), error_context="archive catalog item")
    else:
        handle_db_operation(lambda: db_billing.set_catalog_item_active(id=item["id"], active=True), error_context="reactivate catalog item")
    return CatalogItemResponse(success=True, item=_catalog_info(_require_catalog_item(item_hash, group=group)))


@router.delete("/{group_hash}/catalog/{item_hash}", response_model=BaseResponse, responses={**_AUTH_RESPONSES, **_ITEM_404})
async def delete_catalog_item(group_hash: _GroupHash, item_hash: _ItemHash, scope: AdminScope = Depends(require_billing_scope)) -> BaseResponse:
    """Archive a catalog item (soft delete); same effect as `POST .../archive` with `archived=true`.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or `session_token` cookie)
    of a root or admin user whose session has the `admin` or `manage_billing` permission;
    consumers get `403`. Admin users only reach groups they fully own (every active project
    attached is one of their assigned projects, or an empty group they created); other
    groups return `403`.

    **Responses:** `200`. The row is kept with `provisioning_status` `archived`, it leaves the
    S2S catalog, and nothing is changed in Stripe. `404` when the group is unknown or the item
    does not belong to it.
    """
    group = _require_scoped_group(group_hash, scope)
    item = _require_catalog_item(item_hash, group=group)
    handle_db_operation(lambda: db_billing.archive_catalog_item(id=item["id"]), error_context="delete catalog item")
    return BaseResponse(success=True, message="Catalog item archived")


__all__ = ["router"]
