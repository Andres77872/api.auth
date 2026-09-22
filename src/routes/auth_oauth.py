"""Provider-agnostic OAuth routes.

Public route family ``/auth/oauth/*``. The connection is never chosen from the
browser: at start it comes from the init token, at callback from the state
record. Authenticated routes (link, reauth, unlink) take a connection *key* that
is resolved against the session's own project.

``/auth/google/*`` (see ``src/routes/auth_google.py``) are deprecated aliases onto
the same pipeline.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Form, Header, Query, Request, Response
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials

from src.Util import db
from src.Util.Models import LoginResponse
from src.Util.Seccurity import HTTPBearerOrCookie
from src.Util.auth_constants import OAUTH_PURPOSE_LINK, OAUTH_PURPOSE_LOGIN, OAUTH_PURPOSE_REAUTH
from src.Util.auth_flow import require_recent_reauthentication
from src.Util.auth_lifecycle import validate_access_session
from src.Util.error_handler import ErrorCode
from src.Util.oauth.connections import OAuthConnectionUnavailable, get_connection_source
from src.Util.oauth.init_tokens import DEFAULT_INIT_TOKEN_TTL_SECONDS, OAuthInitTokenStore
from src.Util.oauth.pipeline import (
    AuthorizationStart,
    OAuthPipeline,
    PipelineDeps,
    field_of,
    oauth_error_response,
    session_id_of,
)
from src.Util.oauth.settings import load_oauth_settings
from src.Util.oauth.start import read_json_object, start_from_init_token
from src.Util.oauth_rate_limit import OAuthRateLimiter
from src.Util.oauth_state import OAuthStateStore


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/oauth", tags=["OAuth"])
security = HTTPBearerOrCookie()

# Patched by integration fixtures; ``None`` avoids creating Redis connections at import.
redis_client = None


def _state_store() -> OAuthStateStore:
    return OAuthStateStore(redis_client=redis_client) if redis_client is not None else OAuthStateStore()


def _init_store() -> OAuthInitTokenStore:
    return OAuthInitTokenStore(redis_client=redis_client) if redis_client is not None else OAuthInitTokenStore()


def _rate_limiter() -> OAuthRateLimiter:
    return OAuthRateLimiter(redis_client=redis_client) if redis_client is not None else OAuthRateLimiter()


def build_pipeline() -> OAuthPipeline:
    return OAuthPipeline(
        PipelineDeps(
            db=db,
            state_store=_state_store,
            rate_limiter=_rate_limiter,
            connection_source=get_connection_source,
            cookie_path="/auth/oauth",
        )
    )


def _globally_enabled() -> bool:
    try:
        return load_oauth_settings().enabled
    except Exception:
        return False


# ───────────────────────────────────────────────────────────── server-to-server

@router.post("/init")
async def oauth_init(request: Request, x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> Response:
    """Mint a single-use init token for the calling project's backend.

    Authenticated by a project-scoped API key. The project is derived from that
    credential; the provisioning group comes from the binding. Neither is accepted
    from the request body.
    """

    from src.middleware.authentication import validate_api_key_context

    if not _globally_enabled():
        return oauth_error_response(ErrorCode.OAUTH_PROVIDER_DISABLED, status_code=403)
    context = await validate_api_key_context(x_api_key)
    project_hash = str(context.get("project_hash") or "")
    body = await read_json_object(request)
    if body is None or not project_hash:
        return oauth_error_response(ErrorCode.OAUTH_PROVIDER_INIT_INVALID, status_code=400)
    if {"project_hash", "user_group_hash", "project", "user_group"}.intersection(body):
        return oauth_error_response(
            ErrorCode.OAUTH_PROVIDER_INIT_INVALID, status_code=400, message="Project and group are derived from the credential."
        )
    connection_key = str(body.get("connection") or "").strip().lower()
    purpose = str(body.get("purpose") or OAUTH_PURPOSE_LOGIN).strip().lower()
    return_origin = str(body.get("return_origin") or "").strip()
    if not connection_key or purpose != OAUTH_PURPOSE_LOGIN or not return_origin:
        return oauth_error_response(ErrorCode.OAUTH_PROVIDER_INIT_INVALID, status_code=400)

    try:
        resolved = get_connection_source().get_binding(project_hash=project_hash, connection_key=connection_key)
    except OAuthConnectionUnavailable as exc:
        code = ErrorCode.OAUTH_PROVIDER_DISABLED if exc.kind == "disabled" else ErrorCode.OAUTH_PROVIDER_NOT_CONFIGURED
        return oauth_error_response(code)
    if resolved.binding.project_hash and resolved.binding.project_hash != project_hash:
        return oauth_error_response(ErrorCode.OAUTH_PROJECT_ACCESS_DENIED, status_code=403)
    if not resolved.binding.login_enabled:
        return oauth_error_response(ErrorCode.OAUTH_PROVIDER_DISABLED, status_code=403)
    if not resolved.binding.is_return_origin_allowed(return_origin):
        return oauth_error_response(ErrorCode.OAUTH_REDIRECT_URI_NOT_ALLOWED, status_code=400)

    minted = _init_store().mint(
        binding={
            "connection_id": resolved.config.connection_id,
            "binding_id": resolved.binding.binding_id,
            "connection_key": resolved.binding.connection_key,
            "config_source": resolved.source_name,
            "purpose": purpose,
            "project_hash": project_hash,
            "return_origin": return_origin,
            "remember_me": bool(body.get("remember_me", False)),
        },
        ttl_seconds=DEFAULT_INIT_TOKEN_TTL_SECONDS,
    )
    return JSONResponse(
        {
            "success": True,
            "init_token": minted.token,
            "expires_in": minted.expires_in,
            "connection": resolved.binding.connection_key,
            "provider_type": resolved.config.provider_type,
        },
        headers={"Cache-Control": "no-store"},
    )


@router.get("/providers")
async def oauth_providers(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> Response:
    """Enabled sign-in providers for the calling project, so login pages render from data."""

    from src.middleware.authentication import validate_api_key_context

    context = await validate_api_key_context(x_api_key)
    project_hash = str(context.get("project_hash") or "")
    providers: list[dict[str, Any]] = []
    if _globally_enabled() and project_hash:
        for resolved in get_connection_source().list_project_bindings(project_hash=project_hash):
            if resolved.binding.enabled and resolved.binding.login_enabled:
                providers.append(
                    {
                        "connection": resolved.binding.connection_key,
                        "provider_type": resolved.config.provider_type,
                        "display_name": resolved.config.display_name or resolved.config.provider_type.title(),
                    }
                )
    return JSONResponse({"success": True, "providers": providers})


# ──────────────────────────────────────────────────────────────────── public

@router.post("/start")
async def oauth_start(request: Request) -> Response:
    if not _globally_enabled():
        return oauth_error_response(ErrorCode.OAUTH_PROVIDER_DISABLED, status_code=403)
    return await start_from_init_token(request, pipeline=build_pipeline(), init_store=_init_store)


@router.get("/callback", responses={200: {"model": LoginResponse}})
async def oauth_callback(
    request: Request,
    response: Response,
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
    iss: str | None = Query(None),
) -> Any:
    return await build_pipeline().handle_callback(request, response, code=code, state=state, error=error, iss=iss)


@router.post("/callback")
async def oauth_callback_form_post(
    request: Request,
    response: Response,
    code: str | None = Form(None),
    state: str | None = Form(None),
    error: str | None = Form(None),
    iss: str | None = Form(None),
) -> Any:
    """``response_mode=form_post`` callback (Sign in with Apple and similar providers)."""

    return await build_pipeline().handle_callback(request, response, code=code, state=state, error=error, iss=iss)


# ─────────────────────────────────────────────────────────────── authenticated

def _resolve_for_session(login_data: Any, connection_key: str):
    project_hash = str(field_of(login_data, "project_hash") or "")
    return get_connection_source().get_binding(project_hash=project_hash, connection_key=connection_key.strip().lower())


async def start_session_round_trip(
    request: Request,
    *,
    pipeline: OAuthPipeline,
    credentials: HTTPAuthorizationCredentials,
    connection_key: str,
    purpose: str,
    resolve=None,
) -> Response:
    """Shared body of ``link/start`` and ``reauth/start``."""

    try:
        login_data = validate_access_session(credentials.credentials)
    except Exception:
        return oauth_error_response(ErrorCode.OAUTH_PROVISIONING_DENIED, status_code=401)
    user_id = str(field_of(login_data, "user_id") or "")
    if not user_id:
        return oauth_error_response(ErrorCode.OAUTH_PROVISIONING_DENIED, status_code=401)
    try:
        resolved = (resolve or _resolve_for_session)(login_data, connection_key)
    except OAuthConnectionUnavailable as exc:
        code = ErrorCode.OAUTH_PROVIDER_DISABLED if exc.kind == "disabled" else ErrorCode.OAUTH_PROVIDER_NOT_CONFIGURED
        return oauth_error_response(code)

    if purpose == OAUTH_PURPOSE_LINK:
        if not resolved.binding.can_link:
            return oauth_error_response(ErrorCode.OAUTH_PROVISIONING_DENIED, status_code=401)
        try:
            require_recent_reauthentication(
                user_id=user_id,
                session_token=credentials.credentials,
                session_id=session_id_of(login_data),
                operation="oauth_link",
            )
        except Exception:
            return oauth_error_response(ErrorCode.OAUTH_PROVISIONING_DENIED, status_code=401)

    redirect_uri = resolved.binding.sole_redirect_uri() or (
        resolved.binding.redirect_uris[0] if resolved.binding.trusts_caller_scope and resolved.binding.redirect_uris else None
    )
    if not redirect_uri:
        return oauth_error_response(ErrorCode.OAUTH_REDIRECT_URI_NOT_ALLOWED, status_code=400)
    start = AuthorizationStart(
        resolved=resolved,
        purpose=purpose,
        project_hash=str(field_of(login_data, "project_hash") or ""),
        redirect_uri=redirect_uri,
        return_origin=resolved.binding.return_origins[0] if resolved.binding.return_origins else None,
        user_id=user_id,
        session_id=session_id_of(login_data),
        prompt="login" if purpose == OAUTH_PURPOSE_REAUTH else None,
    )
    try:
        return await pipeline.begin_authorization(request, start)
    except Exception:
        logger.debug("OAuth %s start failed closed", purpose, exc_info=True)
        return oauth_error_response(ErrorCode.OAUTH_STATE_INVALID, status_code=401)


@router.post("/{connection}/link/start")
async def oauth_link_start(connection: str, request: Request, credentials: HTTPAuthorizationCredentials = Depends(security)) -> Response:
    return await start_session_round_trip(
        request, pipeline=build_pipeline(), credentials=credentials, connection_key=connection, purpose=OAUTH_PURPOSE_LINK
    )


@router.post("/{connection}/reauth/start")
async def oauth_reauth_start(connection: str, request: Request, credentials: HTTPAuthorizationCredentials = Depends(security)) -> Response:
    return await start_session_round_trip(
        request, pipeline=build_pipeline(), credentials=credentials, connection_key=connection, purpose=OAUTH_PURPOSE_REAUTH
    )


@router.delete("/{connection}/link")
async def oauth_unlink(connection: str, request: Request, credentials: HTTPAuthorizationCredentials = Depends(security)) -> Any:
    try:
        login_data = validate_access_session(credentials.credentials)
        resolved = _resolve_for_session(login_data, connection)
    except OAuthConnectionUnavailable:
        return oauth_error_response(ErrorCode.EXTERNAL_IDENTITY_NOT_LINKED, status_code=404)
    except Exception:
        return oauth_error_response(ErrorCode.EXTERNAL_IDENTITY_NOT_LINKED, status_code=401)
    return await build_pipeline().unlink(request, resolved=resolved, login_data=login_data, session_token=credentials.credentials)


@router.get("/links")
async def oauth_links(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Any:
    """The caller's linked external identities, masked."""

    try:
        login_data = validate_access_session(credentials.credentials)
    except Exception:
        return oauth_error_response(ErrorCode.EXTERNAL_IDENTITY_NOT_LINKED, status_code=401)
    user_id = str(field_of(login_data, "user_id") or "")
    rows = db.list_external_accounts_for_user(user_id=user_id) if user_id else []
    return {
        "success": True,
        "links": [
            {
                "provider": row.get("provider"),
                "provider_subject_masked": row.get("provider_sub_fingerprint"),
                "provider_email_masked": row.get("provider_email_masked"),
                "status": row.get("status"),
                "linked_at": str(row.get("linked_at")) if row.get("linked_at") else None,
            }
            for row in rows or []
        ],
    }
