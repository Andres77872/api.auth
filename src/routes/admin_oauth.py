"""Admin API for provider-agnostic OAuth configuration.

Manages the provider catalog (kill switch), connections (write-only encrypted
credentials), per-project bindings, exact-match URL allow-lists and readiness.
Modelled on the billing credentials admin API:

* ``admin`` may read status and manage bindings of projects they administer;
* every route that ACCEPTS a secret, creates a connection or flips the catalog is
  root-only;
* responses carry presence flags and fingerprints, never secrets;
* bodies are JSON so secrets never land in URL-encoded request logs;
* every write emits an activity event naming the changed FIELDS, never values.
"""

from __future__ import annotations

import hashlib
import logging
import os
import secrets as token_source
from typing import Any, Mapping, Optional

from fastapi import APIRouter, Body, Depends, Query, Request
from fastapi.security import HTTPAuthorizationCredentials

from src.Util.Seccurity import HTTPBearerOrCookie
from src.Util.activity_logger import ActivityType
from src.Util.auth_constants import OAUTH_INIT_MODE_LEGACY_REDEEM
from src.Util.db import (
    check_admin_multi_project_access,
    db_oauth_connections,
    get_project_by_hash,
    get_user_group_by_hash,
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
    OAuthSecretsNotReady,
    encrypt_secret,
    fingerprint_from_digest,
    secret_hmac,
)
from src.Util.oauth.settings import load_oauth_settings
from src.Util.oauth.url_safety import UnsafeURLError, validate_origin, validate_redirect_uri


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

@router.get("/providers")
async def list_providers(session_data=Depends(require_oauth_admin)) -> dict[str, Any]:
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


@router.put("/providers/{provider_type}")
async def update_provider(
    provider_type: str, request: Request, body: ProviderCatalogUpdate = Body(...), session_data=Depends(require_oauth_root)
) -> dict[str, Any]:
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

@router.get("/connections")
async def list_connections(
    provider_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None, max_length=120),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session_data=Depends(require_oauth_admin),
) -> dict[str, Any]:
    rows, total = db_oauth_connections.list_connections(
        provider_type=provider_type, status=status, search=search, limit=limit, offset=offset
    )
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


@router.post("/connections")
async def create_connection(request: Request, body: ConnectionCreate = Body(...), session_data=Depends(require_oauth_root)) -> dict[str, Any]:
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


@router.get("/connections/{connection_hash}")
async def get_connection(connection_hash: str, session_data=Depends(require_oauth_admin)) -> dict[str, Any]:
    return {"success": True, "connection": _connection_info(_require_connection(connection_hash))}


@router.put("/connections/{connection_hash}")
async def update_connection(
    connection_hash: str, request: Request, body: ConnectionUpdate = Body(...), session_data=Depends(require_oauth_root)
) -> dict[str, Any]:
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


@router.post("/connections/{connection_hash}/activate")
async def activate_connection(connection_hash: str, request: Request, session_data=Depends(require_oauth_root)) -> dict[str, Any]:
    return await _set_status(connection_hash, "active", request, session_data)


@router.post("/connections/{connection_hash}/disable")
async def disable_connection(connection_hash: str, request: Request, session_data=Depends(require_oauth_root)) -> dict[str, Any]:
    return await _set_status(connection_hash, "disabled", request, session_data)


@router.delete("/connections/{connection_hash}")
async def delete_connection(connection_hash: str, request: Request, session_data=Depends(require_oauth_root)) -> dict[str, Any]:
    current = _require_connection(connection_hash)
    if int(current.get("binding_count") or 0) > 0:
        raise ConflictError(message="Remove the project bindings before deleting this connection", error_code=ErrorCode.STATE_CONFLICT)
    outcome = db_oauth_connections.delete_connection(id=str(current["id"]), deleted_by=session_data.user_id)
    invalidate_connection_cache()
    _audit(ActivityType.OAUTH_CONNECTION_STATUS_CHANGED, request=request, session_data=session_data,
           reason=str((outcome or {}).get("outcome") or "deleted"), connection=connection_hash[:12])
    return {"success": True, "message": "Connection removed", "outcome": (outcome or {}).get("outcome", "deleted")}


# ──────────────────────────────────────────────────── credentials (root, write-only)

def _encrypt_credentials(connection_id: str, body: ConnectionCredentialsUpdate):
    if not body.client_secret and not body.signing_key:
        raise ValidationError(message="Provide a client secret or a signing key", error_code=ErrorCode.INVALID_INPUT)
    try:
        client = encrypt_secret(owner_id=connection_id, kind=KIND_CLIENT_SECRET, value=body.client_secret) if body.client_secret else None
        signing = encrypt_secret(owner_id=connection_id, kind=KIND_SIGNING_KEY, value=body.signing_key) if body.signing_key else None
    except OAuthSecretsNotReady as exc:
        raise ValidationError(
            message="Server OAuth secret encryption keys are not configured", error_code=ErrorCode.INVALID_INPUT
        ) from exc
    return client, signing


@router.get("/connections/{connection_hash}/credentials")
async def get_credentials(connection_hash: str, session_data=Depends(require_oauth_admin)) -> dict[str, Any]:
    return {"success": True, "credentials": _credentials_status(_require_connection(connection_hash))}


@router.put("/connections/{connection_hash}/credentials")
async def set_credentials(
    connection_hash: str, request: Request, body: ConnectionCredentialsUpdate = Body(...), session_data=Depends(require_oauth_root)
) -> dict[str, Any]:
    current = _require_connection(connection_hash)
    connection_id = str(current["id"])
    client, signing = _encrypt_credentials(connection_id, body)
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
    fields = ",".join(name for name, value in (("client_secret", client), ("signing_key", signing)) if value)
    _audit(ActivityType.OAUTH_CONNECTION_CREDENTIALS_SET, request=request, session_data=session_data,
           reason=f"set:{fields}", connection=connection_hash[:12])
    return {"success": True, "message": "Credentials saved (encrypted; never echoed)", "credentials": _credentials_status(row or {})}


@router.post("/connections/{connection_hash}/credentials/test")
async def test_credentials(
    connection_hash: str, body: ConnectionCredentialsUpdate = Body(...), session_data=Depends(require_oauth_root)
) -> dict[str, Any]:
    """Validate WITHOUT saving.

    Runs the adapter's static validation and, for discovery-driven providers, fetches the
    discovery document and pins its issuer. A client secret itself cannot be verified
    against a provider without a user round trip, so this reports the fingerprint the
    secret WOULD be stored under -- compare it with the one shown after saving.
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

@router.get("/connections/{connection_hash}/bindings")
async def list_connection_bindings(connection_hash: str, session_data=Depends(require_oauth_admin)) -> dict[str, Any]:
    current = _require_connection(connection_hash)
    rows = db_oauth_connections.list_bindings_for_connection(connection_id=str(current["id"]))
    return {"success": True, "bindings": [_binding_info(row) for row in rows]}


@router.get("/projects/{project_hash}/bindings")
async def list_project_bindings(project_hash: str, session_data=Depends(require_oauth_admin)) -> dict[str, Any]:
    project = _require_project(project_hash)
    _assert_project_access(session_data, project)
    rows = db_oauth_connections.list_bindings_for_project(project_hash=project_hash)
    return {"success": True, "bindings": [_binding_info(row) for row in rows]}


@router.get("/projects/{project_hash}/readiness")
async def project_readiness(project_hash: str, session_data=Depends(require_oauth_admin)) -> dict[str, Any]:
    project = _require_project(project_hash)
    _assert_project_access(session_data, project)
    rows = db_oauth_connections.list_bindings_for_project(project_hash=project_hash)
    providers = []
    for row in rows:
        ready, checks = _readiness(row)
        providers.append({"connection_key": row.get("connection_key"), "provider_type": row.get("provider_type"), "ready": ready, "checks": checks})
    return {"success": True, "oauth_enabled": load_oauth_settings().enabled, "providers": providers}


@router.put("/projects/{project_hash}/bindings/{connection_key}")
async def upsert_binding(
    project_hash: str, connection_key: str, request: Request, body: BindingUpsert = Body(...), session_data=Depends(require_oauth_admin)
) -> dict[str, Any]:
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


@router.delete("/projects/{project_hash}/bindings/{connection_key}")
async def delete_binding(project_hash: str, connection_key: str, request: Request, session_data=Depends(require_oauth_admin)) -> dict[str, Any]:
    project = _require_project(project_hash)
    _assert_project_access(session_data, project)
    row = _require_binding(project_hash, connection_key)
    db_oauth_connections.delete_binding(binding_id=str(row["binding_id"]))
    invalidate_connection_cache()
    _audit(ActivityType.OAUTH_BINDING_REMOVED, request=request, session_data=session_data, reason=connection_key)
    return {"success": True, "message": "Binding removed"}


@router.post("/projects/{project_hash}/bindings/{connection_key}/urls")
async def add_binding_url(
    project_hash: str, connection_key: str, request: Request, body: BindingUrlCreate = Body(...), session_data=Depends(require_oauth_admin)
) -> dict[str, Any]:
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


@router.delete("/projects/{project_hash}/bindings/{connection_key}/urls/{url_id}")
async def remove_binding_url(
    project_hash: str, connection_key: str, url_id: str, request: Request, session_data=Depends(require_oauth_admin)
) -> dict[str, Any]:
    project = _require_project(project_hash)
    _assert_project_access(session_data, project)
    row = _require_binding(project_hash, connection_key)
    outcome = db_oauth_connections.remove_binding_url(binding_id=str(row["binding_id"]), url_id=url_id)
    if not outcome or int(outcome.get("removed") or 0) == 0:
        raise NotFoundError(message="Allowed URL not found", error_code=ErrorCode.RESOURCE_NOT_FOUND)
    invalidate_connection_cache()
    _audit(ActivityType.OAUTH_BINDING_URL_REMOVED, request=request, session_data=session_data, reason=connection_key)
    return {"success": True, "message": "URL removed"}


@router.put("/projects/{project_hash}/bindings/{connection_key}/legacy-redeem")
async def set_legacy_redeem(
    project_hash: str, connection_key: str, request: Request, body: LegacyRedeemUpdate = Body(...), session_data=Depends(require_oauth_root)
) -> dict[str, Any]:
    """Compatibility bridge for a companion backend that still redeems provider-init tokens."""

    _require_project(project_hash)
    row = _require_binding(project_hash, connection_key)
    binding_id = str(row["binding_id"])
    if not body.redeem_url.lower().startswith(("https://", "http://")):
        raise ValidationError(message="Redeem URL must be http(s)", error_code=ErrorCode.INVALID_INPUT)
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
