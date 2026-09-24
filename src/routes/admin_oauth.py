"""Admin API for provider-agnostic OAuth configuration.

Manages the provider catalog (kill switch), connections (write-only encrypted
credentials), per-project bindings, exact-match URL allow-lists and readiness.
Modelled on the billing credentials admin API:

* any session with the ``admin`` permission may READ the catalog, connections,
  credential status and a connection's bindings (these reads are not
  project-scoped);
* project bindings, their URL allow-lists and readiness are scoped to projects the
  admin administers (root: every project);
* every route that ACCEPTS a secret, creates or changes a connection or flips the
  catalog is root-only;
* responses carry presence flags and fingerprints, never secrets;
* bodies are JSON so secrets never land in URL-encoded request logs;
* every write emits an activity event naming the changed FIELDS, never values.
"""

from __future__ import annotations

import hashlib
import logging
import os
import secrets as token_source
from typing import Annotated, Any, Mapping, Optional

from fastapi import APIRouter, Body, Depends, Path, Query, Request
from fastapi.security import HTTPAuthorizationCredentials

from src.Util.Seccurity import HTTPBearerOrCookie
from src.Util.activity_logger import ActivityType
from src.Util.auth_constants import OAUTH_INIT_MODE_LEGACY_REDEEM
from src.Util.db import (
    check_admin_multi_project_access,
    db_oauth_connections,
    get_project_by_hash,
    get_user_group_by_hash,
    is_admin_user,
    is_root_user,
    validate_session,
)
from src.Util.db_error_wrapper import handle_db_operation
from src.Util.error_handler import (
    AuthenticationError,
    AuthorizationError,
    ConflictError,
    ErrorCode,
    NotFoundError,
    ValidationError,
)
from src.Util.oauth.admin_models import (
    AllowedUrl,
    BindingInfo,
    BindingUpsert,
    BindingUrlCreate,
    ConnectionCreate,
    ConnectionCredentialsUpdate,
    ConnectionInfo,
    ConnectionUpdate,
    CredentialProbeResult,
    CredentialsStatus,
    LegacyRedeemUpdate,
    ProviderCatalogEntry,
    ProviderCatalogUpdate,
    ReadinessCheck,
)
from src.Util.oauth.db_source import evaluate_binding_row, invalidate_connection_cache
from src.Util.oauth.pipeline import client_ip, safe_details, user_agent
from src.Util.oauth.provider import ConnectionConfig, OAuthProviderUnknown
from src.Util.oauth.registry import get_adapter, is_registered, register_default_adapters
from src.Util.oauth.secrets import (
    KIND_CLIENT_SECRET,
    KIND_LEGACY_REDEEM_TOKEN,
    KIND_LEGACY_REDEEM_URL,
    KIND_SIGNING_KEY,
    OAuthSecretError,
    OAuthSecretsNotReady,
    decrypt_secret,
    encrypt_secret,
    fingerprint_from_digest,
    secret_hmac,
)
from src.Util.oauth.settings import load_oauth_settings
from src.Util.oauth.url_safety import UnsafeURLError, validate_origin, validate_redeem_url, validate_redirect_uri


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/oauth", tags=["Admin - OAuth"])
security = HTTPBearerOrCookie()

_ENDPOINT_FIELDS = ("discovery_url", "authorize_endpoint", "token_endpoint", "jwks_uri", "userinfo_endpoint")
_READINESS_MESSAGES = {
    "oauth_globally_disabled": "OAuth is disabled for the whole deployment (OAUTH_ENABLED).",
    "provider_type_disabled": "The provider type is disabled in the provider catalog.",
    "adapter_not_registered": "The running backend has no adapter for this provider type.",
    "connection_not_active": "The connection is draft, disabled or archived.",
    "credentials_not_active": "No client secret is stored, or the credentials were revoked.",
    "binding_disabled": "The provider is not enabled for this project.",
    "project_inactive": "The project is inactive or archived.",
    "no_redirect_uri": "No redirect URI is configured.",
    "no_return_origin": "No return origin is configured.",
    "default_group_missing": "Auto-create is on but the default user group is missing or inactive.",
    "default_group_does_not_reach_project": "Auto-create is on but the default user group does not reach this project.",
}
_READINESS_ORDER = tuple(_READINESS_MESSAGES)


# ─────────────────────────────────────────────────────── OpenAPI parameter docs
# Documented path parameters shared by the routes below (the parameters stay plain
# required ``str`` path values; ``Annotated`` only attaches the description).

ProviderTypePath = Annotated[str, Path(description=(
    "Provider type as listed in the catalog: `google`, `github`, `discord`, `microsoft`, `oidc` "
    "(generic OpenID Connect) or `patreon` (link-only). Case-insensitive. It names a kind of "
    "provider, not a configured connection."
))]
ConnectionHashPath = Annotated[str, Path(description=(
    "Server-generated identifier of one OAuth connection (a provider app registration: client id, "
    "scopes, endpoints and write-only credentials), returned as `connection_hash` when the "
    "connection is created. One connection can be bound to many projects."
))]
ProjectHashPath = Annotated[str, Path(description="Hash of the project whose OAuth bindings are read or changed.")]
ConnectionKeyPath = Annotated[str, Path(description=(
    "Project-local name of a binding, such as `google` or `acme-okta` (lowercased on save, at most 64 "
    "characters). Sign-in clients send it as the `connection` value of the `/auth/oauth` endpoints. "
    "It is unique within the project and is not the `connection_hash` of the connection it points to."
))]
UrlIdPath = Annotated[str, Path(description=(
    "`id` of an allow-list row, as returned when the URL was added or listed in the binding's `urls`."
))]

# 403 notes reused in the operation ``responses`` below (descriptions only).
_ROOT_ONLY_403 = {403: {"description": "The caller is not a root user."}}
_ADMIN_403 = {
    403: {
        "description": (
            "The caller is not a root or admin user, its session lacks the `admin` permission, or (admin "
            "users) the connection is owned by a project the caller does not administer."
        )
    }
}
_PROJECT_403 = {403: {"description": "The caller is neither root nor an admin assigned to this project."}}


# ───────────────────────────────────────────────────────────────────── auth gates

async def require_oauth_admin(credentials: HTTPAuthorizationCredentials = Depends(security)):
    session_data = validate_session(credentials.credentials)
    if not session_data:
        raise AuthenticationError(message="Invalid or expired session", error_code=ErrorCode.SESSION_INVALID)
    permissions = session_data.permissions if hasattr(session_data, "permissions") else []
    if "admin" not in permissions:
        raise AuthorizationError(
            message="Admin permission required",
            error_code=ErrorCode.INSUFFICIENT_PERMISSIONS,
            details={"required_permissions": ["admin"]},
        )
    # The permission name alone is not enough: a consumer's global role can carry it.
    if not (is_root_user(session_data.user_id) or is_admin_user(session_data.user_id)):
        raise AuthorizationError(
            message="Root or admin user access required",
            error_code=ErrorCode.INSUFFICIENT_PERMISSIONS,
            details={"required_user_types": ["root", "admin"]},
        )
    return session_data


async def require_oauth_root(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Routes that accept a secret, create a connection or flip the catalog are root-only."""

    session_data = await require_oauth_admin(credentials)
    if not is_root_user(session_data.user_id):
        raise AuthorizationError(
            message="Root privilege required to manage OAuth connections and credentials",
            error_code=ErrorCode.INSUFFICIENT_PERMISSIONS,
        )
    return session_data


def _assert_project_access(session_data: Any, project: Any) -> None:
    if is_root_user(session_data.user_id):
        return
    if not check_admin_multi_project_access(session_data.user_id, project.id):
        raise AuthorizationError(message="Access denied to requested project", error_code=ErrorCode.PROJECT_ACCESS_DENIED)


# ──────────────────────────────────────────────────────────────────────── helpers

def _new_id(prefix: str) -> str:
    return f"{prefix}-{token_source.token_hex(24)}"


def _new_hash() -> str:
    return token_source.token_hex(32).upper()


def _production() -> bool:
    return str(os.environ.get("APP_ENV", "")).strip().lower() in {"prod", "production"}


def _audit(activity: ActivityType, *, request: Request, session_data: Any, reason: str, connection: str | None = None) -> None:
    """Record an admin write. ``reason`` names the changed fields -- never their values."""

    try:
        from src.Util import activity_logger as activity_logger_module

        activity_logger_module.ActivityLogger.log_activity(
            user_id=getattr(session_data, "user_id", None),
            activity_type=activity.value,
            details=safe_details({"reason": reason, "connection": connection}),
            ip_address=client_ip(request),
            user_agent=user_agent(request),
        )
    except Exception:
        logger.debug("OAuth admin activity logging failed", exc_info=True)


def _require_project(project_hash: str):
    project = handle_db_operation(lambda: get_project_by_hash(project_hash), error_context="resolve project")
    if not project:
        raise NotFoundError(message="Project not found", error_code=ErrorCode.RESOURCE_NOT_FOUND)
    return project


def _require_connection(connection_hash: str) -> Mapping[str, Any]:
    row = db_oauth_connections.get_connection_by_hash(connection_hash=connection_hash)
    if not row:
        raise NotFoundError(message="OAuth connection not found", error_code=ErrorCode.RESOURCE_NOT_FOUND)
    return row


def _connection_visible(session_data: Any, connection: Mapping[str, Any], *, root: bool) -> bool:
    """Root sees every connection; an admin user sees shared ones and those its projects own."""

    owner_id = connection.get("owner_project_id")
    return root or not owner_id or check_admin_multi_project_access(session_data.user_id, owner_id)


def _require_visible_connection(connection_hash: str, session_data: Any) -> Mapping[str, Any]:
    """Load a connection the caller may read; 404 before 403, as for projects."""

    connection = _require_connection(connection_hash)
    if not _connection_visible(session_data, connection, root=is_root_user(session_data.user_id)):
        raise AuthorizationError(message="This connection belongs to another project", error_code=ErrorCode.PROJECT_ACCESS_DENIED)
    return connection


def _adapter(provider_type: str):
    if not is_registered(provider_type):
        register_default_adapters()
    try:
        return get_adapter(provider_type)
    except OAuthProviderUnknown as exc:
        raise ValidationError(message="Unknown OAuth provider type", error_code=ErrorCode.INVALID_INPUT) from exc


def _credentials_status(row: Mapping[str, Any]) -> CredentialsStatus:
    return CredentialsStatus(
        credential_status=str(row.get("credential_status") or "absent"),
        has_client_secret=bool(row.get("has_client_secret")),
        has_signing_key=bool(row.get("has_signing_key")),
        client_secret_fingerprint=row.get("client_secret_fingerprint"),
        signing_key_fingerprint=row.get("signing_key_fingerprint"),
        credential_key_id=row.get("credential_key_id"),
        credentials_set_at=row.get("credentials_set_at"),
    )


def _connection_info(row: Mapping[str, Any]) -> ConnectionInfo:
    return ConnectionInfo(
        **{key: row.get(key) for key in (
            "connection_hash", "provider_type", "display_name", "status", "client_id", "scopes",
            "identity_namespace", "owner_project_hash", "owner_project_name", "issuer", "discovery_url",
            "authorize_endpoint", "token_endpoint", "jwks_uri", "userinfo_endpoint", "restrictions",
            "provider_params", "catalog_status", "created_at", "updated_at",
        )},
        tenant_endpoints_allowed=bool(row.get("tenant_endpoints_allowed")),
        binding_count=int(row.get("binding_count") or 0),
        linked_identity_count=int(row.get("linked_identity_count") or 0),
        # Once identities are linked, the namespace (issuer / tenant / team) is frozen.
        namespace_locked=int(row.get("linked_identity_count") or 0) > 0,
        credentials=_credentials_status(row),
    )


def _connection_config(row: Mapping[str, Any], *, namespace: str = "") -> ConnectionConfig:
    issuer = str(row.get("issuer") or "").strip()
    return ConnectionConfig(
        connection_id=str(row.get("id") or "draft"),
        provider_type=str(row.get("provider_type") or ""),
        client_id=str(row.get("client_id") or ""),
        scopes=str(row.get("scopes") or ""),
        identity_namespace=namespace or str(row.get("identity_namespace") or ""),
        display_name=str(row.get("display_name") or ""),
        issuers=(issuer,) if issuer else (),
        discovery_url=row.get("discovery_url") or None,
        authorize_endpoint=row.get("authorize_endpoint") or None,
        token_endpoint=row.get("token_endpoint") or None,
        jwks_uri=row.get("jwks_uri") or None,
        userinfo_endpoint=row.get("userinfo_endpoint") or None,
        restrictions=row.get("restrictions") or {},
        provider_params=row.get("provider_params") or {},
    )


def _validated(fields: Mapping[str, Any]) -> tuple[ConnectionConfig, str]:
    """Validate a complete non-secret field set; return the config and its namespace."""

    adapter = _adapter(str(fields.get("provider_type") or ""))
    if not adapter.capabilities.tenant_configurable_endpoints and any(fields.get(name) for name in (*_ENDPOINT_FIELDS, "issuer")):
        raise ValidationError(
            message="This provider type uses built-in endpoints; endpoint and issuer fields are not accepted",
            error_code=ErrorCode.INVALID_INPUT,
        )
    config = _connection_config(fields)
    problems = adapter.validate_connection(config)
    if problems:
        raise ValidationError(message="OAuth connection is invalid", error_code=ErrorCode.INVALID_INPUT, details={"problems": problems})
    namespace = adapter.identity_namespace(config)
    return _connection_config(fields, namespace=namespace), namespace


def _readiness(row: Mapping[str, Any]) -> tuple[bool, list[ReadinessCheck]]:
    failures = set(evaluate_binding_row(row))
    try:
        if not load_oauth_settings().enabled:
            failures.add("oauth_globally_disabled")
    except Exception:
        failures.add("oauth_globally_disabled")
    checks = [
        ReadinessCheck(check=name, ok=name not in failures, message="" if name not in failures else _READINESS_MESSAGES[name])
        for name in _READINESS_ORDER
    ]
    return not failures, checks


def _binding_info(row: Mapping[str, Any]) -> BindingInfo:
    ready, checks = _readiness(row)
    urls = [AllowedUrl(**item) for item in db_oauth_connections.list_binding_urls(binding_id=str(row["binding_id"]))]
    return BindingInfo(
        connection_key=str(row.get("connection_key") or ""),
        connection_hash=str(row.get("connection_hash") or ""),
        provider_type=str(row.get("provider_type") or ""),
        connection_display_name=str(row.get("display_name") or ""),
        connection_status=str(row.get("connection_status") or ""),
        credential_status=str(row.get("credential_status") or "absent"),
        project_hash=str(row.get("project_hash") or ""),
        project_name=row.get("project_name"),
        enabled=bool(row.get("enabled")),
        login_enabled=bool(row.get("login_enabled")),
        link_enabled=bool(row.get("link_enabled")),
        provisioning_mode=str(row.get("provisioning_mode") or "disabled"),
        default_user_group_hash=row.get("default_user_group_hash"),
        default_user_group_name=row.get("default_user_group_name"),
        existing_user_policy=str(row.get("existing_user_policy") or "deny"),
        init_mode=str(row.get("init_mode") or "api"),
        has_legacy_redeem=bool(row.get("has_legacy_redeem")),
        delivery_mode=str(row.get("delivery_mode") or "bff"),
        state_ttl_seconds=row.get("state_ttl_seconds"),
        urls=urls,
        ready=ready,
        readiness=checks,
    )


def _require_binding(project_hash: str, connection_key: str) -> Mapping[str, Any]:
    row = db_oauth_connections.get_binding(project_hash=project_hash, connection_key=connection_key.strip().lower())
    if not row:
        raise NotFoundError(message="OAuth binding not found", error_code=ErrorCode.RESOURCE_NOT_FOUND)
    return row


# ──────────────────────────────────────────────────────────────── provider catalog

@router.get("/providers", responses=_ADMIN_403)
async def list_providers(session_data=Depends(require_oauth_admin)) -> dict[str, Any]:
    """List the OAuth provider catalog: each provider type, its kill-switch state and whether this backend can serve it.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or `session_token` cookie) of a
    root or admin user whose session has the `admin` permission; consumers get `403` even when
    their global role grants `admin`.

    **Responses:** `200` with `oauth_enabled` (the deployment-wide OAuth switch) and `providers[]`:
    `status`, catalog-level `login_enabled` / `link_enabled`, `tenant_endpoints_allowed`,
    `default_scopes`, `adapter_registered`, the adapter's `capabilities` and `connection_count`
    (non-archived connections).

    Built-in adapters exist for `google`, `github`, `discord`, `microsoft` and `oidc`. `patreon`
    appears as a link-only catalog entry with no adapter; it can never be enabled for sign-in.
    """

    register_default_adapters()
    entries = []
    for row in db_oauth_connections.list_provider_catalog():
        provider_type = str(row.get("provider_type") or "")
        registered = is_registered(provider_type)
        entries.append(
            ProviderCatalogEntry(
                **{key: row.get(key) for key in ("provider_type", "display_name", "protocol", "status", "default_scopes")},
                login_enabled=bool(row.get("login_enabled")),
                link_enabled=bool(row.get("link_enabled")),
                tenant_endpoints_allowed=bool(row.get("tenant_endpoints_allowed")),
                adapter_registered=registered,
                capabilities=get_adapter(provider_type).capabilities.as_metadata() if registered else None,
                connection_count=int(row.get("connection_count") or 0),
            )
        )
    return {"success": True, "oauth_enabled": load_oauth_settings().enabled, "providers": entries}


@router.put(
    "/providers/{provider_type}",
    responses={**_ROOT_ONLY_403, 404: {"description": "The provider type is not in the catalog."}},
)
async def update_provider(
    provider_type: ProviderTypePath,
    request: Request,
    body: ProviderCatalogUpdate = Body(..., description="Catalog fields to change; omitted fields keep their value."),
    session_data=Depends(require_oauth_root),
) -> dict[str, Any]:
    """Change a provider type's catalog entry: its status (the run-time kill switch) and catalog-level login/link flags.

    **Auth:** root only — access token (`Authorization: Bearer <access JWT>` or `session_token`
    cookie) of a root user.

    **Request:** JSON; every field is optional and omitted fields are left unchanged.
    - `status`: `enabled`, `degraded`, `disabled` or `archived`. Bindings of a provider type whose
      status is not `enabled` or `degraded` fail readiness and cannot be used.
    - `login_enabled` / `link_enabled`: catalog-wide gates, combined (AND) with each binding's own
      flags at sign-in time.

    **Responses:** `200` with the updated catalog row. `400` when setting `login_enabled: true` on
    `patreon` (Patreon is link-only). `404` unknown provider type. Changes apply at once on this
    instance and within the 30-second connection cache on other instances.
    """

    provider_type = provider_type.strip().lower()
    if not db_oauth_connections.get_provider_catalog_entry(provider_type=provider_type):
        raise NotFoundError(message="OAuth provider type not found", error_code=ErrorCode.RESOURCE_NOT_FOUND)
    if provider_type == "patreon" and body.login_enabled:
        raise ValidationError(message="Patreon is link-only and cannot be enabled for login", error_code=ErrorCode.INVALID_INPUT)
    row = db_oauth_connections.set_provider_catalog_status(
        provider_type=provider_type, status=body.status, login_enabled=body.login_enabled, link_enabled=body.link_enabled
    )
    invalidate_connection_cache()
    _audit(ActivityType.OAUTH_PROVIDER_CATALOG_UPDATED, request=request, session_data=session_data,
           reason=f"{provider_type}:" + ",".join(sorted(body.model_dump(exclude_none=True))))
    return {"success": True, "message": "Provider updated", "provider": row}


# ──────────────────────────────────────────────────────────────────── connections

@router.get("/connections", responses=_ADMIN_403)
async def list_connections(
    provider_type: Optional[str] = Query(None, description="Only connections of this provider type, e.g. `google`."),
    status: Optional[str] = Query(
        None, description="Only connections in this status: `draft`, `active`, `disabled` or `archived`."
    ),
    search: Optional[str] = Query(None, max_length=120, description="Case-insensitive substring match on `display_name`."),
    limit: int = Query(50, ge=1, le=200, description="Page size (1-200)."),
    offset: int = Query(0, ge=0, description="Number of rows to skip."),
    session_data=Depends(require_oauth_admin),
) -> dict[str, Any]:
    """List OAuth connections (provider app registrations), ordered by display name.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or `session_token` cookie) of a
    root or admin user whose session has the `admin` permission; consumers get `403`. Root sees
    every connection. Admin users see shared connections (no owner project) and connections owned
    by the projects they administer; `pagination.total` counts only those. `binding_count` counts
    bindings across all projects.

    **Responses:** `200` with `connections[]` — `connection_hash`, `provider_type`, `display_name`,
    `status`, `credential_status`, `credentials_set_at`, `client_secret_fingerprint`,
    `identity_namespace`, `scopes`, owner project, `catalog_status`, `binding_count` — and
    `pagination`. Secrets are never returned.
    """

    if is_root_user(session_data.user_id):
        rows, total = db_oauth_connections.list_connections(
            provider_type=provider_type, status=status, search=search, limit=limit, offset=offset
        )
    else:
        # Visibility depends on each row's owner project, so filter the whole (small) catalog
        # and page afterwards; the SQL total would count connections the caller cannot see.
        visible: list[Mapping[str, Any]] = []
        page_offset, page_size = 0, 200
        while True:
            page, page_total = db_oauth_connections.list_connections(
                provider_type=provider_type, status=status, search=search, limit=page_size, offset=page_offset
            )
            visible.extend(row for row in page if _connection_visible(session_data, row, root=False))
            page_offset += page_size
            if len(page) < page_size or page_offset >= page_total:
                break
        rows, total = visible[offset:offset + limit], len(visible)
    return {
        "success": True,
        "connections": [
            {
                **{key: row.get(key) for key in (
                    "connection_hash", "provider_type", "display_name", "status", "credential_status",
                    "credentials_set_at", "client_secret_fingerprint", "identity_namespace", "scopes",
                    "owner_project_hash", "owner_project_name", "catalog_status", "created_at", "updated_at",
                )},
                "binding_count": int(row.get("binding_count") or 0),
            }
            for row in rows
        ],
        "pagination": {"limit": limit, "offset": offset, "total": total, "has_more": offset + len(rows) < total},
    }


@router.post(
    "/connections",
    responses={**_ROOT_ONLY_403, 404: {"description": "`owner_project_hash` does not name an existing project."}},
)
async def create_connection(
    request: Request,
    body: ConnectionCreate = Body(..., description="Non-secret connection configuration. Credentials are set separately."),
    session_data=Depends(require_oauth_root),
) -> dict[str, Any]:
    """Create an OAuth connection in `draft` status: one provider app registration that projects can later bind.

    **Auth:** root only — access token (`Authorization: Bearer <access JWT>` or `session_token`
    cookie) of a root user.

    **Request:** JSON, no secrets.
    - `provider_type`, `display_name` and `client_id` are required. `scopes` defaults to the
      catalog's default scopes and must satisfy the adapter (for example Google needs exactly
      `openid email`).
    - `issuer`, `discovery_url` and the explicit endpoint fields are accepted only for `oidc`;
      `google`, `github`, `discord` and `microsoft` use built-in endpoints and reject them.
    - `restrictions` / `provider_params` are provider-specific JSON objects (for example
      `restrictions.hosted_domains` for Google, `restrictions.orgs` for GitHub,
      `provider_params.tenant` and `restrictions.tenant_ids` for Microsoft).
    - `owner_project_hash` makes the connection project-owned: only root can bind it to other projects.

    **Responses:** `200` with the new connection (`status: draft`, no credentials); next store
    credentials, then activate. `400` for an unknown or archived provider type, a type whose
    catalog entry allows neither login nor link, `patreon` (managed by the Patreon integration,
    not here) or a configuration the adapter rejects (the individual problems are only included
    in error details when debug mode is on). `404` unknown `owner_project_hash`.
    """

    catalog = db_oauth_connections.get_provider_catalog_entry(provider_type=body.provider_type)
    if not catalog or str(catalog.get("status")) == "archived":
        raise ValidationError(message="Unknown OAuth provider type", error_code=ErrorCode.INVALID_INPUT)
    if not bool(catalog.get("login_enabled")) and not bool(catalog.get("link_enabled")):
        raise ValidationError(message="This provider type cannot hold OAuth connections", error_code=ErrorCode.INVALID_INPUT)
    if body.provider_type == "patreon":
        raise ValidationError(message="Patreon is configured through the Patreon integration", error_code=ErrorCode.INVALID_INPUT)
    owner = _require_project(body.owner_project_hash) if body.owner_project_hash else None
    fields = body.model_dump()
    fields["scopes"] = body.scopes or str(catalog.get("default_scopes") or "")
    config, namespace = _validated(fields)
    row = db_oauth_connections.create_connection(
        id=_new_id("oac"),
        connection_hash=_new_hash(),
        provider_type=body.provider_type,
        owner_project_id=owner.id if owner else None,
        display_name=body.display_name,
        client_id=body.client_id,
        issuer=body.issuer,
        discovery_url=body.discovery_url,
        authorize_endpoint=body.authorize_endpoint,
        token_endpoint=body.token_endpoint,
        jwks_uri=body.jwks_uri,
        userinfo_endpoint=body.userinfo_endpoint,
        scopes=config.scopes,
        restrictions=body.restrictions,
        provider_params=body.provider_params,
        identity_namespace=namespace,
        created_by=session_data.user_id,
    )
    invalidate_connection_cache()
    _audit(ActivityType.OAUTH_CONNECTION_CREATED, request=request, session_data=session_data,
           reason=f"provider_type={body.provider_type}", connection=str(row.get("connection_hash"))[:12] if row else None)
    return {"success": True, "message": "Connection created as draft", "connection": _connection_info(row or {})}


@router.get(
    "/connections/{connection_hash}",
    responses={**_ADMIN_403, 404: {"description": "Unknown `connection_hash`."}},
)
async def get_connection(connection_hash: ConnectionHashPath, session_data=Depends(require_oauth_admin)) -> dict[str, Any]:
    """Get one OAuth connection's non-secret configuration and credential status.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or `session_token` cookie) of a
    root or admin user whose session has the `admin` permission; consumers get `403`. Admin users
    may read shared connections and those owned by projects they administer; a connection owned
    by another project returns `403` (an unknown hash is still `404`).

    **Responses:** `200` with `connection`: provider type, status, client id, scopes, issuer and
    endpoints, restrictions, provider params, `identity_namespace`, `namespace_locked` (true once
    identities are linked through it), binding and linked-identity counts, and `credentials`
    (presence flags, 12-character fingerprints, key id, set-at time). Secrets are never returned.
    `404` unknown connection.
    """

    return {"success": True, "connection": _connection_info(_require_visible_connection(connection_hash, session_data))}


@router.put(
    "/connections/{connection_hash}",
    responses={
        **_ROOT_ONLY_403,
        404: {"description": "Unknown `connection_hash`."},
        409: {"description": "The change would alter the identity namespace of a connection that already has linked identities."},
    },
)
async def update_connection(
    connection_hash: ConnectionHashPath,
    request: Request,
    body: ConnectionUpdate = Body(..., description="Fields to change; omitted fields keep their stored value."),
    session_data=Depends(require_oauth_root),
) -> dict[str, Any]:
    """Update a connection's non-secret configuration (display name, client id, scopes, issuer and endpoints, restrictions, provider params).

    **Auth:** root only — access token (`Authorization: Bearer <access JWT>` or `session_token`
    cookie) of a root user.

    **Request:** JSON partial update: omitted fields keep their stored value and a field sent as
    `null` is cleared. The merged configuration is re-validated by the provider adapter (same
    endpoint, issuer and scope rules as create).
    The connection's status and credentials are not changed here (see `.../activate`,
    `.../disable` and `.../credentials`).

    **Responses:** `200` with the updated connection. `400` invalid configuration. `404` unknown
    connection. `409` when the change would move the identity namespace (issuer, Microsoft
    tenant, ...) of a connection that already has linked identities — create a new connection
    instead.
    """

    current = _require_connection(connection_hash)
    changes = body.model_dump(exclude_unset=True)
    merged = {**{key: current.get(key) for key in (
        "id", "provider_type", "display_name", "client_id", "scopes", "issuer", *_ENDPOINT_FIELDS, "restrictions", "provider_params",
    )}, **changes}
    config, namespace = _validated(merged)
    if namespace != current.get("identity_namespace") and int(current.get("linked_identity_count") or 0) > 0:
        raise ConflictError(
            message="Identities are already linked through this connection; its issuer, tenant or team cannot change. "
                    "Create a new connection instead.",
            error_code=ErrorCode.STATE_CONFLICT,
        )
    row = db_oauth_connections.update_connection(
        id=str(current["id"]),
        display_name=str(merged.get("display_name") or ""),
        client_id=str(merged.get("client_id") or ""),
        issuer=merged.get("issuer"),
        discovery_url=merged.get("discovery_url"),
        authorize_endpoint=merged.get("authorize_endpoint"),
        token_endpoint=merged.get("token_endpoint"),
        jwks_uri=merged.get("jwks_uri"),
        userinfo_endpoint=merged.get("userinfo_endpoint"),
        scopes=config.scopes,
        restrictions=merged.get("restrictions"),
        provider_params=merged.get("provider_params"),
        identity_namespace=namespace,
        updated_by=session_data.user_id,
    )
    invalidate_connection_cache()
    _audit(ActivityType.OAUTH_CONNECTION_UPDATED, request=request, session_data=session_data,
           reason=",".join(sorted(changes)), connection=connection_hash[:12])
    return {"success": True, "message": "Connection updated", "connection": _connection_info(row or {})}


async def _set_status(connection_hash: str, status: str, request: Request, session_data: Any) -> dict[str, Any]:
    current = _require_connection(connection_hash)
    if status == "active":
        if str(current.get("credential_status")) != "active":
            raise ValidationError(message="Store credentials before activating the connection", error_code=ErrorCode.INVALID_INPUT)
        _validated({key: current.get(key) for key in current})
    row = db_oauth_connections.set_connection_status(id=str(current["id"]), status=status, updated_by=session_data.user_id)
    invalidate_connection_cache()
    _audit(ActivityType.OAUTH_CONNECTION_STATUS_CHANGED, request=request, session_data=session_data,
           reason=f"status={status}", connection=connection_hash[:12])
    return {"success": True, "message": f"Connection {status}", "connection": _connection_info(row or {})}


@router.post(
    "/connections/{connection_hash}/activate",
    responses={**_ROOT_ONLY_403, 404: {"description": "Unknown `connection_hash`."}},
)
async def activate_connection(
    connection_hash: ConnectionHashPath, request: Request, session_data=Depends(require_oauth_root)
) -> dict[str, Any]:
    """Activate a connection (`status: active`) so the project bindings that use it can serve sign-in.

    **Auth:** root only — access token (`Authorization: Bearer <access JWT>` or `session_token`
    cookie) of a root user.

    **Request:** no request body.

    **Responses:** `200` with the connection. `400` when no active credentials are stored (call
    `PUT .../credentials` first) or the stored configuration no longer passes adapter validation.
    `404` unknown connection. Activation alone does not make a project ready: the provider type
    must be enabled in the catalog and each binding must be enabled and have a redirect URI and a
    return origin (see the project readiness endpoint).
    """

    return await _set_status(connection_hash, "active", request, session_data)


@router.post(
    "/connections/{connection_hash}/disable",
    responses={**_ROOT_ONLY_403, 404: {"description": "Unknown `connection_hash`."}},
)
async def disable_connection(
    connection_hash: ConnectionHashPath, request: Request, session_data=Depends(require_oauth_root)
) -> dict[str, Any]:
    """Disable a connection (`status: disabled`), turning off every project binding that uses it.

    Stored credentials and bindings are kept, so `.../activate` restores service. The change
    applies at once on this instance and within the 30-second connection cache on other instances.

    **Auth:** root only — access token (`Authorization: Bearer <access JWT>` or `session_token`
    cookie) of a root user.

    **Request:** no request body.

    **Responses:** `200` with the connection. `404` unknown connection.
    """

    return await _set_status(connection_hash, "disabled", request, session_data)


@router.delete(
    "/connections/{connection_hash}",
    responses={
        **_ROOT_ONLY_403,
        404: {"description": "Unknown `connection_hash`."},
        409: {"description": "Project bindings still use this connection; delete them first."},
    },
)
async def delete_connection(
    connection_hash: ConnectionHashPath, request: Request, session_data=Depends(require_oauth_root)
) -> dict[str, Any]:
    """Remove a connection that no project binding uses.

    **Auth:** root only — access token (`Authorization: Bearer <access JWT>` or `session_token`
    cookie) of a root user.

    **Responses:**
    - `200` with `outcome: deleted` when no external identity references the connection.
    - `200` with `outcome: archived` when external identities reference it: the row is kept
      because its identity namespace still identifies those users, its status becomes `archived`
      and its stored credentials are erased (`credential_status: revoked`).
    - `409` while any project binding still uses it; `404` unknown connection.
    """

    current = _require_connection(connection_hash)
    if int(current.get("binding_count") or 0) > 0:
        raise ConflictError(message="Remove the project bindings before deleting this connection", error_code=ErrorCode.STATE_CONFLICT)
    outcome = db_oauth_connections.delete_connection(id=str(current["id"]), deleted_by=session_data.user_id)
    invalidate_connection_cache()
    _audit(ActivityType.OAUTH_CONNECTION_STATUS_CHANGED, request=request, session_data=session_data,
           reason=str((outcome or {}).get("outcome") or "deleted"), connection=connection_hash[:12])
    return {"success": True, "message": "Connection removed", "outcome": (outcome or {}).get("outcome", "deleted")}


# ──────────────────────────────────────────────────── credentials (root, write-only)

_CREDENTIAL_KINDS = (KIND_CLIENT_SECRET, KIND_SIGNING_KEY)


def _stored_secrets(current: Mapping[str, Any], kinds: list[str]) -> dict[str, str]:
    """Decrypt the stored secrets a save omitted, so they can be kept. Fails closed."""

    if not kinds or str(current.get("credential_status") or "absent") == "absent":
        return {}
    connection_id = str(current["id"])
    row = db_oauth_connections.get_connection_operational_credentials(id=connection_id) or {}
    stored: dict[str, str] = {}
    for kind in kinds:
        if row.get(f"{kind}_ciphertext") is None:
            continue
        try:
            stored[kind] = decrypt_secret(
                owner_id=connection_id,
                kind=kind,
                ciphertext=row[f"{kind}_ciphertext"],
                key_id=row.get("credential_key_id"),
                expected_digest=row.get(f"{kind}_hmac"),
            )
        except OAuthSecretError as exc:
            raise ValidationError(
                message=f"The stored {kind} cannot be decrypted with the configured keys; send it again, or send an empty string to clear it",
                error_code=ErrorCode.INVALID_INPUT,
            ) from exc
    return stored


def _encrypt_credentials(current: Mapping[str, Any], body: ConnectionCredentialsUpdate):
    """Encrypt the credential set to store: sent secrets, plus stored ones the body omitted.

    Omitted or null keeps the stored secret; an empty string clears it. Both secrets share
    the row's one ``credential_key_id``, so a kept secret is re-encrypted under the active key.
    """

    sent = {kind: getattr(body, kind) for kind in _CREDENTIAL_KINDS}
    if all(value is None for value in sent.values()):
        raise ValidationError(message="Provide a client secret or a signing key", error_code=ErrorCode.INVALID_INPUT)
    stored = _stored_secrets(current, [kind for kind, value in sent.items() if value is None])
    values = {kind: stored.get(kind) if value is None else (value if value.strip() else None) for kind, value in sent.items()}
    if not any(values.values()):
        raise ValidationError(
            message="A connection needs a client secret or a signing key; both would be empty", error_code=ErrorCode.INVALID_INPUT
        )
    connection_id = str(current["id"])
    try:
        encrypted = {
            kind: encrypt_secret(owner_id=connection_id, kind=kind, value=value) if value else None
            for kind, value in values.items()
        }
    except OAuthSecretsNotReady as exc:
        raise ValidationError(
            message="Server OAuth secret encryption keys are not configured", error_code=ErrorCode.INVALID_INPUT
        ) from exc
    changes = [
        f"{'kept' if sent[kind] is None else 'set' if values[kind] else 'cleared'}:{kind}"
        for kind in _CREDENTIAL_KINDS
        if sent[kind] is not None or values[kind]
    ]
    return encrypted[KIND_CLIENT_SECRET], encrypted[KIND_SIGNING_KEY], changes


@router.get(
    "/connections/{connection_hash}/credentials",
    responses={**_ADMIN_403, 404: {"description": "Unknown `connection_hash`."}},
)
async def get_credentials(connection_hash: ConnectionHashPath, session_data=Depends(require_oauth_admin)) -> dict[str, Any]:
    """Show whether a connection has credentials stored, without revealing them.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or `session_token` cookie) of a
    root or admin user whose session has the `admin` permission; consumers get `403`. Admin users
    may read shared connections and those owned by projects they administer; a connection owned
    by another project returns `403`.

    **Responses:** `200` with `credentials`: `credential_status` (`absent`, `active`, `rotating`
    or `revoked`), `has_client_secret`, `has_signing_key`, 12-character fingerprints,
    `credential_key_id` (encryption key id) and `credentials_set_at`. Secret values are
    write-only and never returned. `404` unknown connection.
    """

    return {"success": True, "credentials": _credentials_status(_require_visible_connection(connection_hash, session_data))}


@router.put(
    "/connections/{connection_hash}/credentials",
    responses={**_ROOT_ONLY_403, 404: {"description": "Unknown `connection_hash`."}},
)
async def set_credentials(
    connection_hash: ConnectionHashPath,
    request: Request,
    body: ConnectionCredentialsUpdate = Body(
        ...,
        description=(
            "Write-only secrets. An omitted or null field keeps the stored secret; an empty string clears it. "
            "At least one field must be sent."
        ),
    ),
    session_data=Depends(require_oauth_root),
) -> dict[str, Any]:
    """Store a connection's client secret and/or signing key, encrypted at rest and write-only.

    **Auth:** root only — access token (`Authorization: Bearer <access JWT>` or `session_token`
    cookie) of a root user.

    **Request:** JSON (never form or query parameters, so secrets stay out of URL-encoded logs)
    with `client_secret` and/or `signing_key`; at least one must be sent. A field you omit (or
    send as null) keeps its stored secret, re-encrypted under the current encryption key; an
    empty string clears it. The connection must keep at least one of the two.

    **Responses:** `200` with the credential status only (`credential_status: active`, presence
    flags, fingerprints); secrets are never echoed back. The connection's status is unchanged, so
    a `draft` connection still needs `.../activate`. `400` when neither field is sent, when the
    save would leave no secret, when a kept secret cannot be decrypted with the configured keys
    (send it again or clear it), or when the server has no OAuth secret encryption keys
    configured. `404` unknown connection.
    """

    current = _require_connection(connection_hash)
    connection_id = str(current["id"])
    client, signing, changes = _encrypt_credentials(current, body)
    row = db_oauth_connections.set_connection_credentials(
        id=connection_id,
        client_secret_ciphertext=client.ciphertext if client else None,
        client_secret_hmac=client.digest if client else None,
        client_secret_fingerprint=client.fingerprint if client else None,
        signing_key_ciphertext=signing.ciphertext if signing else None,
        signing_key_hmac=signing.digest if signing else None,
        signing_key_fingerprint=signing.fingerprint if signing else None,
        credential_key_id=(client or signing).key_id,
        set_by=session_data.user_id,
    )
    invalidate_connection_cache()
    _audit(ActivityType.OAUTH_CONNECTION_CREDENTIALS_SET, request=request, session_data=session_data,
           reason=";".join(changes), connection=connection_hash[:12])
    return {"success": True, "message": "Credentials saved (encrypted; never echoed)", "credentials": _credentials_status(row or {})}


@router.post(
    "/connections/{connection_hash}/credentials/test",
    responses={**_ROOT_ONLY_403, 404: {"description": "Unknown `connection_hash`."}},
)
async def test_credentials(
    connection_hash: ConnectionHashPath,
    body: ConnectionCredentialsUpdate = Body(
        ..., description="Optional `client_secret` to fingerprint; `signing_key` is ignored. Nothing is saved."
    ),
    session_data=Depends(require_oauth_root),
) -> dict[str, Any]:
    """Check a connection's stored configuration and fingerprint a candidate secret, without saving anything.

    **Auth:** root only — access token (`Authorization: Bearer <access JWT>` or `session_token`
    cookie) of a root user.

    **Request:** JSON object with the same shape as `PUT .../credentials`; both fields are
    optional (`{}` is valid). Only `client_secret` is used. The stored connection configuration
    is what gets validated, not the body.

    **Responses:** `200` for any existing connection, with `result`:
    - `valid` / `problems`: the adapter's validation of the stored configuration; for `oidc`
      connections with a `discovery_url` the discovery document is also fetched and its issuer
      compared with the connection's issuer.
    - `client_secret_fingerprint`: the fingerprint the submitted secret would be stored under —
      compare it with the stored fingerprint to confirm which secret is saved. The secret itself
      is not checked against the provider (that needs a real sign-in round trip).

    `404` unknown connection.
    """

    current = _require_connection(connection_hash)
    adapter = _adapter(str(current.get("provider_type")))
    config = _connection_config(current)
    problems = list(adapter.validate_connection(config))
    if config.discovery_url and adapter.capabilities.tenant_configurable_endpoints:
        try:
            from src.Util.oauth.http import load_discovery

            load_discovery(config.discovery_url, expected_issuers=tuple(config.issuers))
        except Exception:
            problems.append("discovery document is unreachable or its issuer does not match the connection issuer")
    fingerprint = None
    if body.client_secret:
        try:
            fingerprint = fingerprint_from_digest(
                secret_hmac(owner_id=str(current["id"]), kind=KIND_CLIENT_SECRET, value=body.client_secret)
            )
        except OAuthSecretsNotReady:
            problems.append("server OAuth secret encryption keys are not configured")
    return {"success": True, "result": CredentialProbeResult(valid=not problems, problems=problems, client_secret_fingerprint=fingerprint)}


# ─────────────────────────────────────────────────────────────────────── bindings

@router.get(
    "/connections/{connection_hash}/bindings",
    responses={**_ADMIN_403, 404: {"description": "Unknown `connection_hash`."}},
)
async def list_connection_bindings(
    connection_hash: ConnectionHashPath, session_data=Depends(require_oauth_admin)
) -> dict[str, Any]:
    """List the project bindings that use a connection.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or `session_token` cookie) of a
    root or admin user whose session has the `admin` permission; consumers get `403`. Root sees
    the bindings of every project. Admin users may list shared connections and those owned by
    projects they administer (another project's connection returns `403`), and see only the
    bindings of projects they administer.

    **Responses:** `200` with `bindings[]` in the same shape as the project bindings list,
    including each binding's allowed URLs and readiness checks. `404` unknown connection.
    """

    current = _require_visible_connection(connection_hash, session_data)
    rows = db_oauth_connections.list_bindings_for_connection(connection_id=str(current["id"]))
    if not is_root_user(session_data.user_id):
        rows = [row for row in rows if check_admin_multi_project_access(session_data.user_id, row.get("project_id"))]
    return {"success": True, "bindings": [_binding_info(row) for row in rows]}


@router.get(
    "/projects/{project_hash}/bindings",
    responses={**_PROJECT_403, 404: {"description": "Unknown project."}},
)
async def list_project_bindings(project_hash: ProjectHashPath, session_data=Depends(require_oauth_admin)) -> dict[str, Any]:
    """List a project's OAuth bindings with their allowed URLs and readiness.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or `session_token` cookie) of a
    root user, or of an admin user assigned to this project.

    **Responses:** `200` with `bindings[]`: `connection_key`, the bound connection
    (`connection_hash`, `provider_type`, display name, `connection_status`, `credential_status`),
    `enabled`, `login_enabled`, `link_enabled`, `provisioning_mode`, default user group,
    `existing_user_policy`, `init_mode`, `has_legacy_redeem`, `state_ttl_seconds`, `urls[]`,
    `ready` and `readiness[]`. `404` unknown project (checked before access, so a missing project
    is not hidden behind `403`); `403` the caller does not administer the project.
    """

    project = _require_project(project_hash)
    _assert_project_access(session_data, project)
    rows = db_oauth_connections.list_bindings_for_project(project_hash=project_hash)
    return {"success": True, "bindings": [_binding_info(row) for row in rows]}


@router.get(
    "/projects/{project_hash}/readiness",
    responses={**_PROJECT_403, 404: {"description": "Unknown project."}},
)
async def project_readiness(project_hash: ProjectHashPath, session_data=Depends(require_oauth_admin)) -> dict[str, Any]:
    """Explain, per binding, whether a project's OAuth providers are usable and which layer is missing.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or `session_token` cookie) of a
    root user, or of an admin user assigned to this project.

    **Responses:** `200` with `oauth_enabled` and `providers[]` (`connection_key`,
    `provider_type`, `ready`, `checks[]`). `ready` is true only when every check passes. Every
    check is always reported, in this order, and failing ones carry a readable `message`:
    `oauth_globally_disabled`, `provider_type_disabled`, `adapter_not_registered`,
    `connection_not_active`, `credentials_not_active`, `binding_disabled`, `project_inactive`,
    `no_redirect_uri`, `no_return_origin`, and — when `provisioning_mode` is `auto_create` or
    `both` — `default_group_missing` / `default_group_does_not_reach_project`.
    `404` unknown project; `403` the caller does not administer the project.

    Readiness evaluates the database-stored configuration, which serves sign-in only when the
    deployment reads OAuth configuration from the database (`OAUTH_CONFIG_SOURCE=db`). The
    per-purpose `login_enabled` / `link_enabled` flags are not part of `ready`.
    """

    project = _require_project(project_hash)
    _assert_project_access(session_data, project)
    rows = db_oauth_connections.list_bindings_for_project(project_hash=project_hash)
    providers = []
    for row in rows:
        ready, checks = _readiness(row)
        providers.append({"connection_key": row.get("connection_key"), "provider_type": row.get("provider_type"), "ready": ready, "checks": checks})
    return {"success": True, "oauth_enabled": load_oauth_settings().enabled, "providers": providers}


@router.put(
    "/projects/{project_hash}/bindings/{connection_key}",
    responses={
        403: {"description": (
            "The caller is neither root nor an admin assigned to this project, or the connection "
            "is owned by another project and the caller is not root."
        )},
        404: {"description": "Unknown project, `connection_hash` or `default_user_group_hash`."},
        409: {"description": "This connection is already bound to the project under another `connection_key`."},
    },
)
async def upsert_binding(
    project_hash: ProjectHashPath,
    connection_key: ConnectionKeyPath,
    request: Request,
    body: BindingUpsert = Body(..., description="Binding policy; only `connection_hash` is required."),
    session_data=Depends(require_oauth_admin),
) -> dict[str, Any]:
    """Create or update the binding that makes a connection available to a project under `connection_key`.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or `session_token` cookie) of a
    root user, or of an admin user assigned to this project. Connections without an owner project
    can be bound by such admins; a connection owned by another project only by root.

    **Request:** JSON. `connection_hash` (required) selects the connection; on an existing binding
    it re-points the key at that connection. Other fields are optional and omitted ones keep their
    value (a new binding starts with `enabled: false`, `login_enabled: true`, `link_enabled: true`,
    `provisioning_mode: disabled`, `existing_user_policy: deny`).
    - `provisioning_mode`: `disabled`, `link_only`, `auto_create` or `both`; `auto_create` and
      `both` require a default user group.
    - `default_user_group_hash`: group that auto-provisioned users join; it must be active and
      reach this project. Send `null` to clear it.
    - `existing_user_policy`: `deny` or `join_default_group` (needs a default user group).
    - `state_ttl_seconds`: 30-600, or `null` for the deployment default.

    **Responses:** `200` with the binding and its readiness. A new binding is not usable until it
    is enabled and has at least one redirect URI and one return origin (`POST .../urls`). `400`
    when the provisioning / default-group rules are violated. `403`, `404`, `409` as listed.
    """

    connection_key = connection_key.strip().lower()
    project = _require_project(project_hash)
    _assert_project_access(session_data, project)
    connection = _require_connection(body.connection_hash)
    owner_id = connection.get("owner_project_id")
    # A project-owned connection may only be bound elsewhere by root.
    if owner_id and str(owner_id) != str(project.id) and not is_root_user(session_data.user_id):
        raise AuthorizationError(message="This connection belongs to another project", error_code=ErrorCode.PROJECT_ACCESS_DENIED)

    existing = db_oauth_connections.get_binding(project_hash=project_hash, connection_key=connection_key)
    group_id = existing.get("default_user_group_id") if existing else None
    if "default_user_group_hash" in body.model_fields_set:
        group_id = None
        if body.default_user_group_hash:
            group = handle_db_operation(lambda: get_user_group_by_hash(body.default_user_group_hash), error_context="resolve user group")
            if not group:
                raise NotFoundError(message="User group not found", error_code=ErrorCode.RESOURCE_NOT_FOUND)
            group_id = group.id
    mode = body.provisioning_mode or (existing.get("provisioning_mode") if existing else "disabled")
    if mode in {"auto_create", "both"} and not group_id:
        raise ValidationError(message="Auto-create requires a default user group", error_code=ErrorCode.INVALID_INPUT)

    try:
        row = db_oauth_connections.upsert_binding(
            id=_new_id("pob"),
            project_id=project.id,
            connection_id=str(connection["id"]),
            connection_key=connection_key,
            enabled=body.enabled,
            login_enabled=body.login_enabled,
            link_enabled=body.link_enabled,
            provisioning_mode=body.provisioning_mode,
            default_user_group_id=group_id,
            existing_user_policy=body.existing_user_policy,
            init_mode=None,
            delivery_mode=None,
            state_ttl_seconds=body.state_ttl_seconds if "state_ttl_seconds" in body.model_fields_set else (existing or {}).get("state_ttl_seconds"),
            rate_limit_overrides=(existing or {}).get("rate_limit_overrides"),
            actor=session_data.user_id,
        )
    except (ValidationError, ConflictError, NotFoundError):
        raise
    except Exception as exc:  # stored-procedure SIGNAL: group does not reach project, key clash, ...
        raise ValidationError(
            message="Binding rejected: the default user group must be active and reach this project",
            error_code=ErrorCode.INVALID_INPUT,
        ) from exc
    invalidate_connection_cache()
    _audit(ActivityType.OAUTH_BINDING_UPDATED, request=request, session_data=session_data,
           reason=f"{connection_key}:" + ",".join(sorted(body.model_fields_set)), connection=body.connection_hash[:12])
    return {"success": True, "message": "Binding saved", "binding": _binding_info(row or {})}


@router.delete(
    "/projects/{project_hash}/bindings/{connection_key}",
    responses={**_PROJECT_403, 404: {"description": "Unknown project or binding."}},
)
async def delete_binding(
    project_hash: ProjectHashPath,
    connection_key: ConnectionKeyPath,
    request: Request,
    session_data=Depends(require_oauth_admin),
) -> dict[str, Any]:
    """Remove a project's binding together with its allowed URLs; the connection itself is kept.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or `session_token` cookie) of a
    root user, or of an admin user assigned to this project.

    **Responses:** `200` when removed. `404` unknown project or binding; `403` the caller does not
    administer the project.
    """

    project = _require_project(project_hash)
    _assert_project_access(session_data, project)
    row = _require_binding(project_hash, connection_key)
    db_oauth_connections.delete_binding(binding_id=str(row["binding_id"]))
    invalidate_connection_cache()
    _audit(ActivityType.OAUTH_BINDING_REMOVED, request=request, session_data=session_data, reason=connection_key)
    return {"success": True, "message": "Binding removed"}


@router.post(
    "/projects/{project_hash}/bindings/{connection_key}/urls",
    responses={**_PROJECT_403, 404: {"description": "Unknown project or binding."}},
)
async def add_binding_url(
    project_hash: ProjectHashPath,
    connection_key: ConnectionKeyPath,
    request: Request,
    body: BindingUrlCreate = Body(..., description="The allow-list entry: `kind` and the exact `url`."),
    session_data=Depends(require_oauth_admin),
) -> dict[str, Any]:
    """Add one exact-match URL to a binding's redirect URI or return-origin allow-list.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or `session_token` cookie) of a
    root user, or of an admin user assigned to this project.

    **Request:** JSON `{"kind": ..., "url": ...}`.
    - `kind: redirect_uri`: a callback URL the sign-in flow may use. Absolute `https` URL with no
      wildcard, fragment or embedded credentials.
    - `kind: return_origin`: an origin the browser may be sent back to, `scheme://host[:port]`
      only — no path, query or trailing slash.

    Outside production, `http://` is also accepted for `localhost`, `127.0.0.1` and `[::1]`.
    Matching at sign-in is exact string equality; there are no prefixes or wildcards.

    **Responses:** `200` with the stored row (`id`, `kind`, `url`, `created_at`); adding a URL
    that is already listed returns the existing row. `400` rejected URL or `kind`. `404` unknown
    project or binding; `403` the caller does not administer the project.
    """

    project = _require_project(project_hash)
    _assert_project_access(session_data, project)
    row = _require_binding(project_hash, connection_key)
    try:
        validator = validate_redirect_uri if body.kind == "redirect_uri" else validate_origin
        url = validator(body.url, allow_http_localhost=not _production())
    except UnsafeURLError as exc:
        raise ValidationError(message=str(exc), error_code=ErrorCode.INVALID_INPUT) from exc
    created = db_oauth_connections.add_binding_url(
        id=_new_id("pau"),
        binding_id=str(row["binding_id"]),
        kind=body.kind,
        url=url,
        url_hash=hashlib.sha256(url.encode("utf-8")).digest(),
        created_by=session_data.user_id,
    )
    invalidate_connection_cache()
    _audit(ActivityType.OAUTH_BINDING_URL_ADDED, request=request, session_data=session_data, reason=f"{connection_key}:{body.kind}")
    return {"success": True, "message": "URL added", "url": AllowedUrl(**(created or {}))}


@router.delete(
    "/projects/{project_hash}/bindings/{connection_key}/urls/{url_id}",
    responses={**_PROJECT_403, 404: {"description": "Unknown project or binding, or `url_id` is not on this binding."}},
)
async def remove_binding_url(
    project_hash: ProjectHashPath,
    connection_key: ConnectionKeyPath,
    url_id: UrlIdPath,
    request: Request,
    session_data=Depends(require_oauth_admin),
) -> dict[str, Any]:
    """Remove one URL from a binding's allow-list.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or `session_token` cookie) of a
    root user, or of an admin user assigned to this project.

    **Responses:** `200` when removed. `404` unknown project or binding, or the `url_id` does not
    belong to this binding; `403` the caller does not administer the project. Removing the last
    redirect URI or return origin makes the binding fail readiness.
    """

    project = _require_project(project_hash)
    _assert_project_access(session_data, project)
    row = _require_binding(project_hash, connection_key)
    outcome = db_oauth_connections.remove_binding_url(binding_id=str(row["binding_id"]), url_id=url_id)
    if not outcome or int(outcome.get("removed") or 0) == 0:
        raise NotFoundError(message="Allowed URL not found", error_code=ErrorCode.RESOURCE_NOT_FOUND)
    invalidate_connection_cache()
    _audit(ActivityType.OAUTH_BINDING_URL_REMOVED, request=request, session_data=session_data, reason=connection_key)
    return {"success": True, "message": "URL removed"}


@router.put(
    "/projects/{project_hash}/bindings/{connection_key}/legacy-redeem",
    responses={**_ROOT_ONLY_403, 404: {"description": "Unknown project or binding."}},
)
async def set_legacy_redeem(
    project_hash: ProjectHashPath,
    connection_key: ConnectionKeyPath,
    request: Request,
    body: LegacyRedeemUpdate = Body(..., description="Write-only redeem endpoint and bearer; both required."),
    session_data=Depends(require_oauth_root),
) -> dict[str, Any]:
    """Store the legacy provider-init redeem bridge on a binding and switch it to `init_mode: legacy_redeem`.

    Compatibility path for a companion backend that still issues provider-init tokens: when a
    sign-in starts with such a token, api.auth POSTs it to `redeem_url`, authenticated with
    `redeem_token` as a bearer, to learn the project and return origin.

    **Auth:** root only — access token (`Authorization: Bearer <access JWT>` or `session_token`
    cookie) of a root user.

    **Request:** JSON with `redeem_url` and `redeem_token`. Both are stored encrypted and are
    write-only. Because the token is sent to it as a bearer, `redeem_url` must be `https://`
    (plain `http://` only to `localhost`, `127.0.0.1` or `::1`) and must not contain
    credentials; internal hostnames and private addresses are allowed. The redeem call never
    follows redirects.

    **Responses:** `200` with the binding (`init_mode: legacy_redeem`, `has_legacy_redeem: true`);
    the URL and token are never echoed. `400` when `redeem_url` breaks those rules, or the
    server has no OAuth secret encryption keys configured. `404` unknown project or binding. No endpoint
    switches a binding back to `init_mode: api`.
    """

    _require_project(project_hash)
    row = _require_binding(project_hash, connection_key)
    binding_id = str(row["binding_id"])
    try:
        validate_redeem_url(body.redeem_url)
    except UnsafeURLError as exc:
        raise ValidationError(
            message="Redeem URL must be an https URL (plain http only on localhost) without credentials",
            error_code=ErrorCode.INVALID_INPUT,
        ) from exc
    try:
        url = encrypt_secret(owner_id=binding_id, kind=KIND_LEGACY_REDEEM_URL, value=body.redeem_url)
        token = encrypt_secret(owner_id=binding_id, kind=KIND_LEGACY_REDEEM_TOKEN, value=body.redeem_token)
    except OAuthSecretsNotReady as exc:
        raise ValidationError(message="Server OAuth secret encryption keys are not configured", error_code=ErrorCode.INVALID_INPUT) from exc
    db_oauth_connections.upsert_binding(
        id=binding_id, project_id=str(row["project_id"]), connection_id=str(row["connection_id"]),
        connection_key=str(row["connection_key"]), enabled=None, login_enabled=None, link_enabled=None,
        provisioning_mode=None, default_user_group_id=row.get("default_user_group_id"), existing_user_policy=None,
        init_mode=OAUTH_INIT_MODE_LEGACY_REDEEM, delivery_mode=None, state_ttl_seconds=row.get("state_ttl_seconds"),
        rate_limit_overrides=row.get("rate_limit_overrides"), actor=session_data.user_id,
    )
    updated = db_oauth_connections.set_binding_legacy_redeem(
        binding_id=binding_id, url_ciphertext=url.ciphertext, token_ciphertext=token.ciphertext, key_id=url.key_id, actor=session_data.user_id
    )
    invalidate_connection_cache()
    _audit(ActivityType.OAUTH_BINDING_UPDATED, request=request, session_data=session_data, reason=f"{connection_key}:legacy_redeem")
    return {"success": True, "message": "Legacy redeem bridge saved (encrypted; never echoed)", "binding": _binding_info(updated or {})}
