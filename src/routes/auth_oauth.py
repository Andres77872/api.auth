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
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, Header, Path, Query, Request, Response
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


# ─────────────────────────────────────────────────────────────── OpenAPI helpers

_X_API_KEY_DESCRIPTION = (
    "User API key (`sk_{public_id}.{secret}`) held by the project's backend; the project "
    "is derived from it. Missing or invalid keys get `401`."
)

_REDIRECT_303_RESPONSE = {
    "description": (
        "Redirect (`Location`) to the provider's authorization URL. Sets the short-lived "
        "HttpOnly `oauth_state` browser-binding cookie."
    ),
}

_RETURN_ORIGIN_REQUEST_BODY = {
    "required": False,
    "content": {
        "application/json": {
            "schema": {
                "type": "object",
                "properties": {
                    "return_origin": {
                        "type": "string",
                        "description": (
                            "Origin to return to; must be on the binding's allow-list. Required "
                            "when the binding lists more than one return origin."
                        ),
                    }
                },
            }
        }
    },
}

ConnectionKeyPath = Annotated[
    str,
    Path(description="Connection key (e.g. `google`), resolved within the caller's session project; case-insensitive."),
]


# ───────────────────────────────────────────────────────────── server-to-server

@router.post(
    "/init",
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "required": ["connection", "return_origin"],
                        "properties": {
                            "connection": {
                                "type": "string",
                                "description": "Connection key configured for the project (e.g. `google`); case-insensitive.",
                            },
                            "return_origin": {
                                "type": "string",
                                "description": "Origin the user returns to; must be on the binding's allow-list.",
                            },
                            "purpose": {
                                "type": "string",
                                "enum": ["login"],
                                "default": "login",
                                "description": "Only `login` is accepted.",
                            },
                            "remember_me": {
                                "type": "boolean",
                                "default": False,
                                "description": "Issue a longer-lived refresh token at login (the browser may override it at start).",
                            },
                        },
                    }
                }
            },
        }
    },
)
async def oauth_init(
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key", description=_X_API_KEY_DESCRIPTION),
) -> Response:
    """Mint a single-use init token that lets a browser start an OAuth login for the calling project.

    **Auth:** user API key in `X-API-Key`, called server-to-server by the project's
    backend/BFF. The project comes from the key and the provisioning group from the
    project's connection binding; neither can be sent in the body.

    **Request:** `application/json` with `connection` and `return_origin`; optional
    `purpose` (`login` only) and `remember_me`. Bodies containing `project_hash`,
    `user_group_hash`, `project` or `user_group` are rejected.

    **Responses:**
    - `200` — `{success, init_token, expires_in, connection, provider_type}` with
      `Cache-Control: no-store`. Pass `init_token` to `POST /auth/oauth/start` before it
      expires.
    - `400` — invalid body, forbidden field, unsupported `purpose` (`EXT_8012`), or
      `return_origin` not allowed (`EXT_8013`).
    - `401` — missing or invalid API key.
    - `403` — OAuth disabled deployment-wide or login disabled for the binding
      (`EXT_8011`), binding owned by another project (`EXT_8025`), or key owner lost
      project access.
    - `404` — connection disabled for the project (`EXT_8011`).
    - `503` — connection not configured (`EXT_8010`).
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
async def oauth_providers(
    x_api_key: str | None = Header(default=None, alias="X-API-Key", description=_X_API_KEY_DESCRIPTION),
) -> Response:
    """List the OAuth sign-in providers enabled for the calling project, so login pages can render from data.

    **Auth:** user API key in `X-API-Key` (server-to-server); the project comes from the key.

    **Responses:**
    - `200` — `{success, providers: [{connection, provider_type, display_name}]}`; the list
      is empty when OAuth is disabled deployment-wide or no connection is enabled for
      login in the project.
    - `401` — missing or invalid API key.
    - `403` — the key owner lost access to the key's project.
    """

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

@router.post(
    "/start",
    responses={303: _REDIRECT_303_RESPONSE},
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "required": ["init_token"],
                        "properties": {
                            "init_token": {
                                "type": "string",
                                "maxLength": 512,
                                "description": "Single-use token from `POST /auth/oauth/init`.",
                            },
                            "redirect_uri": {
                                "type": "string",
                                "description": (
                                    "Provider callback URL; must be one of the binding's redirect URIs. "
                                    "Required when the binding lists more than one."
                                ),
                            },
                            "remember_me": {
                                "type": "boolean",
                                "description": "Overrides the `remember_me` given at init.",
                            },
                        },
                    }
                }
            },
        }
    },
)
async def oauth_start(request: Request) -> Response:
    """Redeem an init token and redirect the browser to the provider's sign-in page.

    **Auth:** public; the single-use init token from `POST /auth/oauth/init` is the
    credential. Project, connection, return origin and provisioning group all come from
    that token, never from this request.

    **Request:** `application/json` with `init_token`; optional `redirect_uri` and
    `remember_me`. Bodies containing `project_hash` or `user_group_hash` are rejected.

    **Responses:**
    - `303` — redirect to the provider; sets the `oauth_state` cookie (path `/auth/oauth`).
      The provider returns to the binding's redirect URI, which must hand `code` and
      `state` to `/auth/oauth/callback`.
    - `400` — invalid body, forbidden field or missing token (`EXT_8012`), or redirect
      URI / return origin not allowed (`EXT_8013`).
    - `401` — init token unknown, expired or already used (`EXT_8012`), or state storage
      unavailable (`EXT_8014`).
    - `403` — OAuth disabled deployment-wide or for the connection (`EXT_8011`).
    - `429` — rate limited (`EXT_8030`); `Retry-After` is set.
    - `503` — connection not configured (`EXT_8010`).
    """
    if not _globally_enabled():
        return oauth_error_response(ErrorCode.OAUTH_PROVIDER_DISABLED, status_code=403)
    return await start_from_init_token(request, pipeline=build_pipeline(), init_store=_init_store)


_CODE_DESCRIPTION = "Authorization code issued by the provider."
_STATE_DESCRIPTION = "Opaque state issued at start; consumed on first use."
_ERROR_DESCRIPTION = "Provider error code (e.g. `access_denied` when the user cancelled)."
_ISS_DESCRIPTION = "Issuer identifier (RFC 9207); verified only for providers that require it."


@router.get("/callback", responses={200: {"model": LoginResponse}})
async def oauth_callback(
    request: Request,
    response: Response,
    code: str | None = Query(None, description=_CODE_DESCRIPTION),
    state: str | None = Query(None, description=_STATE_DESCRIPTION),
    error: str | None = Query(None, description=_ERROR_DESCRIPTION),
    iss: str | None = Query(None, description=_ISS_DESCRIPTION),
) -> Any:
    """Finish an OAuth round trip: consume the state, exchange the code, and complete the login, link or reauth it was started for.

    **Auth:** public; the single-use `state` is the credential, and the `oauth_state`
    cookie must match it when the browser sends one. Connection, project and purpose
    come from the stored state only. Always answers JSON; it does not redirect back to
    the return origin.

    **Result by purpose (`200`):**
    - login — `LoginResponse` for the project fixed at start, plus the `session_token`
      and `refresh_token` cookies. Only active consumer accounts can sign in this way;
      unknown identities are provisioned only when the binding allows auto-creation, and
      nothing is merged by email.
    - link — `{success, message, external_identity}` (masked identity).
    - reauth — `{success, message, reauthenticated: true}`; satisfies the
      recent-authentication check of the session that started it.

    **Errors** (OAuth envelope with `correlation_id`):
    - `400` — missing `state`, or neither `code` nor `error` (`EXT_8014`); user cancelled
      at the provider (`EXT_8031`).
    - `401` — state invalid, expired or reused (`EXT_8014`/`EXT_8016`); identity rejected
      (`EXT_8017`–`EXT_8023`); login/link not permitted (`EXT_8024`); reauth identity not
      linked to the session's user (`EXT_8028`).
    - `403` — no access to the bound project, or project inactive (`EXT_8025`).
    - `404` — connection disabled since start (`EXT_8011`).
    - `409` — a local account already uses this verified email: sign in and link instead
      (`EXT_8032`); or the identity is linked to another user (`EXT_8027`).
    - `429` — rate limited (`EXT_8030`); `Retry-After` is set.
    - `502` — provider returned an error or the code exchange failed (`EXT_8018`).
    - `503` — connection no longer configured (`EXT_8010`).
    """
    return await build_pipeline().handle_callback(request, response, code=code, state=state, error=error, iss=iss)


@router.post("/callback")
async def oauth_callback_form_post(
    request: Request,
    response: Response,
    code: str | None = Form(None, description=_CODE_DESCRIPTION),
    state: str | None = Form(None, description=_STATE_DESCRIPTION),
    error: str | None = Form(None, description=_ERROR_DESCRIPTION),
    iss: str | None = Form(None, description=_ISS_DESCRIPTION),
) -> Any:
    """Same as `GET /auth/oauth/callback`, for providers that post back with `response_mode=form_post` (e.g. Sign in with Apple).

    **Auth:** public; the single-use `state` is the credential.

    **Request:** form fields (`application/x-www-form-urlencoded` or
    `multipart/form-data`): `code`, `state`, `error`, `iss`.

    **Responses:** identical to `GET /auth/oauth/callback` (`LoginResponse`, link or
    reauth result on `200`; OAuth error envelope otherwise).
    """

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
    # The caller may name its return origin; it is validated against the binding exactly
    # as login start validates it. With several origins configured, "the first of many"
    # would silently pick an arbitrary one -- the binding's JSON_ARRAYAGG has no ORDER BY
    # -- so the caller must name the one it wants and we refuse rather than guess.
    requested_origin = str((await read_json_object(request) or {}).get("return_origin") or "").strip()
    if requested_origin and not resolved.binding.is_return_origin_allowed(requested_origin):
        return oauth_error_response(ErrorCode.OAUTH_REDIRECT_URI_NOT_ALLOWED, status_code=400)
    return_origin = requested_origin or resolved.binding.sole_return_origin()
    if not return_origin and resolved.binding.return_origins:
        return oauth_error_response(ErrorCode.OAUTH_REDIRECT_URI_NOT_ALLOWED, status_code=400)
    start = AuthorizationStart(
        resolved=resolved,
        purpose=purpose,
        project_hash=str(field_of(login_data, "project_hash") or ""),
        redirect_uri=redirect_uri,
        return_origin=return_origin,
        user_id=user_id,
        session_id=session_id_of(login_data),
        prompt="login" if purpose == OAUTH_PURPOSE_REAUTH else None,
    )
    try:
        return await pipeline.begin_authorization(request, start)
    except Exception:
        logger.debug("OAuth %s start failed closed", purpose, exc_info=True)
        return oauth_error_response(ErrorCode.OAUTH_STATE_INVALID, status_code=401)


@router.post(
    "/{connection}/link/start",
    responses={303: _REDIRECT_303_RESPONSE},
    openapi_extra={"requestBody": _RETURN_ORIGIN_REQUEST_BODY},
)
async def oauth_link_start(connection: ConnectionKeyPath, request: Request, credentials: HTTPAuthorizationCredentials = Depends(security)) -> Response:
    """Start linking an external identity from `connection` to the signed-in user; redirects to the provider.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `session_token`
    cookie) plus recent authentication: a sign-in, or an OAuth reauth of this session,
    within the recent-reauthentication window (refreshing the session does not renew
    it). The project's binding for `connection` must allow linking.

    **Request:** optional `application/json` body `{return_origin}`.

    **Responses:**
    - `303` — redirect to the provider (sets the `oauth_state` cookie, path
      `/auth/oauth`); the callback finishes the link.
    - `400` — the binding has no single redirect URI, or `return_origin` is not allowed or
      is required because several are configured (`EXT_8013`).
    - `401` — invalid session, linking not allowed for the binding, or no recent
      authentication (`EXT_8024`); state could not be created (`EXT_8014`).
    - `404` — connection disabled for the project (`EXT_8011`).
    - `503` — connection not configured for the project (`EXT_8010`).
    """
    return await start_session_round_trip(
        request, pipeline=build_pipeline(), credentials=credentials, connection_key=connection, purpose=OAUTH_PURPOSE_LINK
    )


@router.post(
    "/{connection}/reauth/start",
    responses={303: _REDIRECT_303_RESPONSE},
    openapi_extra={"requestBody": _RETURN_ORIGIN_REQUEST_BODY},
)
async def oauth_reauth_start(connection: ConnectionKeyPath, request: Request, credentials: HTTPAuthorizationCredentials = Depends(security)) -> Response:
    """Start a step-up reauthentication with `connection`; redirects to the provider with `prompt=login`.

    When the callback returns an identity already linked to the signed-in user, the
    session is marked as recently authenticated, which satisfies the recent-auth check
    of `/auth/switch-project`, OAuth link/unlink and the Patreon link routes.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `session_token`
    cookie). No recent authentication is required to start.

    **Request:** optional `application/json` body `{return_origin}`.

    **Responses:**
    - `303` — redirect to the provider (sets the `oauth_state` cookie, path `/auth/oauth`).
      A callback identity not linked to this user fails with `401` (`EXT_8028`).
    - `400` — the binding has no single redirect URI, or `return_origin` is not allowed or
      is required because several are configured (`EXT_8013`).
    - `401` — invalid session (`EXT_8024`) or state could not be created (`EXT_8014`).
    - `404` — connection disabled for the project (`EXT_8011`).
    - `503` — connection not configured for the project (`EXT_8010`).
    """
    return await start_session_round_trip(
        request, pipeline=build_pipeline(), credentials=credentials, connection_key=connection, purpose=OAUTH_PURPOSE_REAUTH
    )


@router.delete("/{connection}/link")
async def oauth_unlink(connection: ConnectionKeyPath, request: Request, credentials: HTTPAuthorizationCredentials = Depends(security)) -> Any:
    """Unlink the signed-in user's external identity for `connection` and sign the user out everywhere.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `session_token`
    cookie) plus recent authentication (a sign-in, or an OAuth reauth of this
    session, within the recent-reauthentication window; refreshing the session does not renew it). The account must
    keep a usable password to fall back on.

    **Request:** no body.

    **Responses:**
    - `200` — `ExternalIdentityUnlinkResponse`; all of the user's sessions and refresh
      tokens, including the current one, are revoked (`sessions_revoked`).
    - `401` — invalid session or no recent authentication (`EXT_8028`).
    - `404` — connection not available in the project, or nothing linked (`EXT_8028`).
    - `409` — the account has no usable password; set one before unlinking (`EXT_8029`).
    - `429` — too many unlink attempts (`EXT_8030`); `Retry-After` is set.
    """
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
    """List the signed-in user's linked external identities, masked.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or the `session_token`
    cookie).

    **Responses:**
    - `200` — `{success, links: [{provider, provider_subject_masked,
      provider_email_masked, status, linked_at}]}` for every provider linked to the user.
    - `401` — missing or invalid access token.
    """

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
