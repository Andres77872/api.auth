"""Google OAuth routes -- deprecated aliases onto the provider-agnostic pipeline.

``/auth/google/*`` predates ``/auth/oauth/*`` and is kept so existing consumers keep
working unchanged. Every handler delegates to :mod:`src.Util.oauth.pipeline` with
the connection key ``google``; there is no Google-specific flow logic left here.

The module-level names below are injection seams, looked up at request time so
integration fixtures can replace them. None of them alters behaviour when left at
its default, and there are no test-runtime branches in this module: a state that
was never issued, a code that the provider did not mint, or a token that does not
verify is rejected in every environment.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.security import HTTPAuthorizationCredentials

from src.Util import db
from src.Util.Models import ExternalIdentityUnlinkResponse, LoginResponse
from src.Util.Seccurity import HTTPBearerOrCookie
from src.Util.activity_logger import ActivityType
from src.Util.auth_constants import OAUTH_PURPOSE_LINK, OAUTH_PURPOSE_REAUTH
from src.Util.auth_lifecycle import validate_access_session
from src.Util.error_handler import ErrorCode
from src.Util.google_oauth_config import load_google_oauth_config
from src.Util.oauth.adapters.google import GoogleAdapter
from src.Util.oauth.connections import (
    DEFAULT_CONNECTION_KEY,
    ConnectionSource,
    EnvironmentConnectionSource,
    OAuthConnectionUnavailable,
    ResolvedConnection,
    get_connection_source,
)
from src.Util.oauth.pipeline import (
    OAuthPipeline,
    PipelineDeps,
    client_ip,
    field_of,
    maybe_await,
    oauth_error_response,
    safe_details,
    user_agent,
)
from src.Util.oauth.provider import (
    CallbackParams,
    ConnectionConfig,
    ConnectionSecrets,
    ExternalIdentity,
    OAuthExchangeError,
    OAuthFailure,
    OAuthIdentityError,
    OAuthTransaction,
    TokenResponse,
)
from src.Util.oauth.settings import load_oauth_settings
from src.Util.oauth.start import start_from_legacy_provider_init
from src.Util.oauth_rate_limit import OAuthRateLimiter
from src.Util.oauth_state import OAuthStateStore
from src.Util.provider_init import redeem_provider_init, redeem_provider_init_token
from src.routes.auth_oauth import start_session_round_trip


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/google", tags=["Google OAuth"])
security = HTTPBearerOrCookie()

# ── injection seams (resolved at request time) ────────────────────────────────
redis_client = None
# Token-exchange double: an object with ``exchange_authorization_code`` or
# ``authorize_access_token``. ``None`` means the GoogleAdapter exchanges the code.
oauth_client = None
google_oauth_client = None
# ID-token verifier double: ``callable(id_token, expected_nonce=...) -> claims``.
# ``None`` means the GoogleAdapter verifies the token.
verify_google_id_token = None
google_id_token_verifier = None

_FAILURES = {failure.value: failure for failure in OAuthFailure}


async def record_google_oauth_activity(
    activity_type: ActivityType,
    *,
    details: Mapping[str, Any] | None = None,
    request: Request | None = None,
    user_id: str | None = None,
    target_user_id: str | None = None,
) -> None:
    """Persist a redacted Google OAuth activity event."""

    try:
        from src.Util import activity_logger as activity_logger_module

        activity_logger_module.ActivityLogger.log_activity(
            user_id=user_id,
            activity_type=activity_type.value,
            details=safe_details(details),
            target_user_id=target_user_id,
            ip_address=client_ip(request),
            user_agent=user_agent(request),
        )
    except Exception:
        logger.debug("Google OAuth activity logging failed", exc_info=True)


async def capture_oauth_audit(event: str, *, details: Mapping[str, Any] | None = None, request: Request | None = None) -> None:
    """Route-level audit hook. Durable request/response rows are owned by the API audit
    middleware; this hook receives the same redacted details the activity log gets."""

    return None


record_oauth_audit = capture_oauth_audit


class _SeamedGoogleAdapter(GoogleAdapter):
    """GoogleAdapter that defers to the module seams when a fixture installed one."""

    async def exchange_code(
        self, connection: ConnectionConfig, secrets: ConnectionSecrets, tx: OAuthTransaction, callback: CallbackParams
    ) -> TokenResponse:
        client = oauth_client if oauth_client is not None else google_oauth_client
        if client is None:
            return await super().exchange_code(connection, secrets, tx, callback)
        exchange = getattr(client, "exchange_authorization_code", None) or getattr(client, "authorize_access_token")
        payload = await maybe_await(exchange(callback.raw_request, code_verifier=tx.code_verifier, redirect_uri=tx.redirect_uri))
        if not isinstance(payload, Mapping) or not payload.get("id_token"):
            raise OAuthExchangeError("Google token response is malformed")
        return TokenResponse(payload)

    async def resolve_identity(self, connection: ConnectionConfig, tx: OAuthTransaction, tokens: TokenResponse) -> ExternalIdentity:
        verify = verify_google_id_token if verify_google_id_token is not None else google_id_token_verifier
        if verify is None:
            return await super().resolve_identity(connection, tx, tokens)
        try:
            claims = await maybe_await(verify(str(tokens.get("id_token") or ""), expected_nonce=tx.nonce))
        except OAuthIdentityError:
            raise
        except Exception as exc:
            failure = _FAILURES.get(str(getattr(exc, "failure", "")), OAuthFailure.ID_TOKEN_INVALID)
            raise OAuthIdentityError(failure, "Google ID token was rejected") from exc
        return self.identity_from_claims(connection, claims)


_ADAPTER = _SeamedGoogleAdapter()


def _connection_source() -> ConnectionSource:
    settings = load_oauth_settings()
    if settings.uses_database:
        return get_connection_source(settings=settings)
    # ``load_google_oauth_config`` is resolved here, at request time, so it stays patchable.
    return EnvironmentConnectionSource(settings=settings, config_loader=lambda: load_google_oauth_config())


def _adapter_for(resolved: ResolvedConnection):
    return _ADAPTER if resolved.config.provider_type == "google" else resolved.adapter


def _state_store() -> OAuthStateStore:
    return OAuthStateStore(redis_client=redis_client) if redis_client is not None else OAuthStateStore()


def _rate_limiter() -> OAuthRateLimiter:
    return OAuthRateLimiter(redis_client=redis_client) if redis_client is not None else OAuthRateLimiter()


async def _record(activity_type: ActivityType, **kwargs: Any) -> None:
    await maybe_await(record_google_oauth_activity(activity_type, **kwargs))
    await maybe_await(capture_oauth_audit(activity_type.value, details=kwargs.get("details"), request=kwargs.get("request")))


def build_pipeline() -> OAuthPipeline:
    return OAuthPipeline(
        PipelineDeps(
            db=db,
            state_store=_state_store,
            rate_limiter=_rate_limiter,
            connection_source=_connection_source,
            record_activity=_record,
            adapter_for=_adapter_for,
            legacy_google_activity=True,
            cookie_path="/auth/google",
        )
    )


def _resolve_google_for_session(login_data: Any, connection_key: str) -> ResolvedConnection:
    return _connection_source().get_binding(
        project_hash=str(field_of(login_data, "project_hash") or ""), connection_key=DEFAULT_CONNECTION_KEY
    )


@router.post("/start", deprecated=True)
async def start_google_oauth(request: Request) -> Response:
    redeem = redeem_provider_init_token if redeem_provider_init_token is not None else redeem_provider_init
    return await start_from_legacy_provider_init(
        request, pipeline=build_pipeline(), connection_key=DEFAULT_CONNECTION_KEY, redeem=redeem
    )


@router.get("/callback", responses={200: {"model": LoginResponse}}, deprecated=True)
async def google_oauth_callback(
    request: Request,
    response: Response,
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
    error_description: str | None = Query(None),
) -> Any:
    return await build_pipeline().handle_callback(request, response, code=code, state=state, error=error)


@router.post("/link/start", deprecated=True)
async def google_oauth_link_start(request: Request, credentials: HTTPAuthorizationCredentials = Depends(security)) -> Response:
    return await start_session_round_trip(
        request,
        pipeline=build_pipeline(),
        credentials=credentials,
        connection_key=DEFAULT_CONNECTION_KEY,
        purpose=OAUTH_PURPOSE_LINK,
        resolve=_resolve_google_for_session,
    )


@router.post("/reauth/start", deprecated=True)
async def google_oauth_reauth_start(request: Request, credentials: HTTPAuthorizationCredentials = Depends(security)) -> Response:
    return await start_session_round_trip(
        request,
        pipeline=build_pipeline(),
        credentials=credentials,
        connection_key=DEFAULT_CONNECTION_KEY,
        purpose=OAUTH_PURPOSE_REAUTH,
        resolve=_resolve_google_for_session,
    )


@router.delete("/unlink", response_model=ExternalIdentityUnlinkResponse, deprecated=True)
async def google_oauth_unlink(request: Request, credentials: HTTPAuthorizationCredentials = Depends(security)) -> Any:
    try:
        login_data = validate_access_session(credentials.credentials)
        resolved = _resolve_google_for_session(login_data, DEFAULT_CONNECTION_KEY)
    except OAuthConnectionUnavailable:
        return oauth_error_response(ErrorCode.EXTERNAL_IDENTITY_NOT_LINKED, status_code=404)
    except Exception:
        return oauth_error_response(ErrorCode.EXTERNAL_IDENTITY_NOT_LINKED, status_code=401)
    return await build_pipeline().unlink(request, resolved=resolved, login_data=login_data, session_token=credentials.credentials)

