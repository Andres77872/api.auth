"""Authlib Google OAuth client construction and token-exchange seam.

Trace: `.dev/sdd/changes/google-oauth-login/tasks.md` task 6.3.

Context7 conclusions used for this implementation:
- Authlib's Starlette/FastAPI integration exposes ``OAuth`` from
  ``authlib.integrations.starlette_client``.
- A Google/OIDC client is registered via ``OAuth().register(...)`` with
  ``server_metadata_url``, ``client_id``, ``client_secret``, and
  ``client_kwargs``.
- ``authorize_redirect(request, redirect_uri, ...)`` initiates the browser
  redirect; ``authorize_access_token(request, ...)`` redeems the callback.
- PKCE S256 is expressed as ``code_challenge_method='S256'``.

This module keeps Authlib imports lazy so test collection does not depend on
runtime package installation until the Authlib path is actually exercised.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import urlencode

from src.Util.google_oauth_config import GoogleOAuthConfig, load_google_oauth_config, validate_google_oauth_readiness


class OAuthClientConfigurationError(RuntimeError):
    """Raised when the Google OAuth client cannot be safely constructed."""


@dataclass(frozen=True)
class GoogleAuthorizationRequest:
    authorization_url: str
    state: str
    nonce: str
    code_challenge: str
    code_challenge_method: str = "S256"


def _authlib_oauth_class():
    try:
        from authlib.integrations.starlette_client import OAuth
    except Exception as exc:  # pragma: no cover - depends on optional runtime install
        raise OAuthClientConfigurationError("Authlib Starlette OAuth client is unavailable") from exc
    return OAuth


def _require_ready_config(config: GoogleOAuthConfig) -> None:
    readiness = validate_google_oauth_readiness(config)
    if not readiness.ready:
        raise OAuthClientConfigurationError(f"Google OAuth config is {readiness.status}")
    if config.scope_set != {"openid", "email"}:
        raise OAuthClientConfigurationError("Google OAuth scope must be exactly 'openid email'")


def create_google_oauth_registry(*, config: GoogleOAuthConfig | None = None):
    """Create an Authlib OAuth registry with a registered Google OIDC client."""

    config = config or load_google_oauth_config()
    _require_ready_config(config)
    OAuth = _authlib_oauth_class()
    oauth = OAuth()
    oauth.register(
        "google",
        client_id=config.client_id,
        client_secret=config.client_secret,
        server_metadata_url=config.discovery_url,
        authorize_url=config.authorize_endpoint,
        access_token_url=config.token_endpoint,
        client_kwargs={
            "scope": config.scopes,
            "code_challenge_method": "S256",
        },
    )
    return oauth


def get_google_remote_app(*, config: GoogleOAuthConfig | None = None):
    """Return Authlib's registered ``google`` remote app."""

    return create_google_oauth_registry(config=config).google


def build_google_authorization_url(
    *,
    state: str,
    nonce: str,
    code_challenge: str,
    redirect_uri: str,
    config: GoogleOAuthConfig | None = None,
    extra_params: Mapping[str, Any] | None = None,
) -> GoogleAuthorizationRequest:
    """Build a minimal Google authorization URL from the configured endpoint.

    This helper is intentionally deterministic for tests/fakes. Route code can
    use it when a direct URL is preferred over an Authlib ``RedirectResponse``.
    """

    config = config or load_google_oauth_config()
    _require_ready_config(config)
    if not config.is_redirect_uri_allowed(redirect_uri):
        raise OAuthClientConfigurationError("Redirect URI is not allowlisted")

    params: dict[str, Any] = {
        "response_type": "code",
        "client_id": config.client_id,
        "redirect_uri": redirect_uri,
        "scope": "openid email",
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    for key, value in dict(extra_params or {}).items():
        if value is None:
            continue
        params[str(key)] = value
    params.pop("access_type", None)
    if params.get("prompt") == "consent":
        params.pop("prompt", None)
    authorization_url = f"{config.authorize_endpoint}?{urlencode(params)}"
    return GoogleAuthorizationRequest(
        authorization_url=authorization_url,
        state=state,
        nonce=nonce,
        code_challenge=code_challenge,
    )


class GoogleOAuthClient:
    """Small Authlib seam for routes and test fakes."""

    def __init__(self, *, config: GoogleOAuthConfig | None = None, remote_app: Any | None = None) -> None:
        self._config = config
        self._remote_app = remote_app

    @property
    def config(self) -> GoogleOAuthConfig:
        return self._config or load_google_oauth_config()

    @property
    def remote_app(self):
        if self._remote_app is None:
            self._remote_app = get_google_remote_app(config=self.config)
        return self._remote_app

    async def authorize_redirect(
        self,
        request,
        *,
        redirect_uri: str,
        state: str,
        nonce: str,
        code_challenge: str,
    ):
        """Return Authlib's Google redirect response with caller-owned state."""

        if not self.config.is_redirect_uri_allowed(redirect_uri):
            raise OAuthClientConfigurationError("Redirect URI is not allowlisted")
        return await self.remote_app.authorize_redirect(
            request,
            redirect_uri,
            response_type="code",
            state=state,
            nonce=nonce,
            code_challenge=code_challenge,
            code_challenge_method="S256",
        )

    async def authorize_access_token(self, request, *, code_verifier: str | None = None, redirect_uri: str | None = None):
        """Redeem the callback authorization code exactly once.

        Uses Authlib's session-free ``fetch_access_token`` rather than
        ``authorize_access_token``: api.auth owns OAuth state / nonce / PKCE in Redis and
        builds the authorize URL itself, so Authlib never stored state in
        ``request.session`` (and no ``SessionMiddleware`` is installed). We pull the
        ``code`` from the callback query and post directly to the token endpoint; the
        returned id_token is verified separately by the route (nonce/iss/aud/signature).
        """
        code = request.query_params.get("code")
        if not code:
            raise OAuthClientConfigurationError("Authorization code missing from callback")
        kwargs: dict[str, Any] = {"code": code, "grant_type": "authorization_code"}
        if code_verifier:
            kwargs["code_verifier"] = code_verifier
        if redirect_uri:
            kwargs["redirect_uri"] = redirect_uri
        return await self.remote_app.fetch_access_token(**kwargs)

    async def exchange_authorization_code(self, request, *, code_verifier: str, redirect_uri: str):
        """Named alias used by tests/routes to make one-shot exchange explicit."""

        return await self.authorize_access_token(request, code_verifier=code_verifier, redirect_uri=redirect_uri)

    def build_authorization_url(
        self,
        *,
        state: str,
        nonce: str,
        code_challenge: str,
        redirect_uri: str,
    ) -> GoogleAuthorizationRequest:
        return build_google_authorization_url(
            state=state,
            nonce=nonce,
            code_challenge=code_challenge,
            redirect_uri=redirect_uri,
            config=self.config,
        )


google_oauth_client = GoogleOAuthClient()


async def exchange_authorization_code(request, *, code_verifier: str, redirect_uri: str):
    return await google_oauth_client.exchange_authorization_code(
        request,
        code_verifier=code_verifier,
        redirect_uri=redirect_uri,
    )


__all__ = [
    "GoogleAuthorizationRequest",
    "GoogleOAuthClient",
    "OAuthClientConfigurationError",
    "build_google_authorization_url",
    "create_google_oauth_registry",
    "exchange_authorization_code",
    "get_google_remote_app",
    "google_oauth_client",
]
