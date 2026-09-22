"""Base adapter for plain OAuth 2.0 providers that have no ID token.

Identity comes from a provider REST endpoint called with the access token. The
access token is used for that call and then dropped; it never leaves the adapter.
Endpoints are compiled into each subclass -- these provider types never accept
tenant-supplied URLs.
"""

from __future__ import annotations

import asyncio
from typing import Any, Mapping
from urllib.parse import urlencode

from src.Util.oauth.http import OAuthHTTPError, guarded_get_json, guarded_post_form
from src.Util.oauth.provider import (
    EMAIL_TRUST_UNVERIFIED,
    SUBJECT_SCOPE_GLOBAL,
    CallbackParams,
    ConnectionConfig,
    ConnectionSecrets,
    ExternalIdentity,
    OAuthExchangeError,
    OAuthFailure,
    OAuthIdentityError,
    OAuthTransaction,
    ProviderCapabilities,
    TokenResponse,
)
from src.Util.oauth.url_safety import UnsafeURLError


class OAuth2UserInfoAdapter:
    provider_type = "oauth2"
    capabilities = ProviderCapabilities(
        protocol="oauth2",
        pkce=True,
        nonce=False,
        subject_scope=SUBJECT_SCOPE_GLOBAL,
        email_trust=EMAIL_TRUST_UNVERIFIED,
    )
    authorize_endpoint = ""
    token_endpoint = ""
    userinfo_endpoint = ""
    default_scopes = ""
    required_scopes: frozenset[str] = frozenset()
    scope_separator = " "
    userinfo_headers: Mapping[str, str] = {}

    # ----------------------------------------------------------------- configuration
    def identity_namespace(self, connection: ConnectionConfig) -> str:
        return self.provider_type

    def validate_connection(self, connection: ConnectionConfig) -> list[str]:
        problems: list[str] = []
        if not connection.client_id:
            problems.append("client_id is required")
        missing = self.required_scopes - set(connection.scopes.split())
        if missing:
            problems.append(f"scopes must include: {' '.join(sorted(missing))}")
        for attribute in ("discovery_url", "authorize_endpoint", "token_endpoint", "jwks_uri", "userinfo_endpoint"):
            if getattr(connection, attribute, None):
                problems.append(f"{attribute} cannot be set for provider type '{self.provider_type}'")
        return problems

    # ------------------------------------------------------------------- authorize
    def build_authorization_url(self, connection: ConnectionConfig, tx: OAuthTransaction) -> str:
        params: dict[str, Any] = {
            "response_type": "code",
            "client_id": connection.client_id,
            "redirect_uri": tx.redirect_uri,
            "scope": self.scope_separator.join(connection.scopes.split()),
            "state": tx.state,
        }
        if self.capabilities.pkce:
            params["code_challenge"] = tx.code_challenge
            params["code_challenge_method"] = "S256"
        if tx.prompt and tx.prompt != "consent":
            params["prompt"] = tx.prompt
        return f"{self.authorize_endpoint}?{urlencode(params)}"

    # -------------------------------------------------------------------- exchange
    async def exchange_code(
        self,
        connection: ConnectionConfig,
        secrets: ConnectionSecrets,
        tx: OAuthTransaction,
        callback: CallbackParams,
    ) -> TokenResponse:
        if not secrets.client_secret:
            raise OAuthExchangeError("client secret is not available", failure=OAuthFailure.PROVIDER_MISCONFIGURED)
        data = {
            "grant_type": "authorization_code",
            "code": callback.code,
            "redirect_uri": tx.redirect_uri,
            "client_id": connection.client_id,
            "client_secret": secrets.client_secret,
        }
        if self.capabilities.pkce:
            data["code_verifier"] = tx.code_verifier
        try:
            payload = await asyncio.to_thread(guarded_post_form, self.token_endpoint, data=data)
        except (OAuthHTTPError, UnsafeURLError) as exc:
            raise OAuthExchangeError("Authorization code exchange failed") from exc
        if payload.get("error") or not payload.get("access_token"):
            raise OAuthExchangeError("Token response is missing access_token")
        return TokenResponse(payload)

    # -------------------------------------------------------------------- identity
    def _api_get(self, url: str, access_token: str) -> Any:
        headers = {"Authorization": f"Bearer {access_token}", **dict(self.userinfo_headers)}
        payload, _ = guarded_get_json(url, headers=headers)
        return payload

    def fetch_profile(self, connection: ConnectionConfig, access_token: str) -> Mapping[str, Any]:
        profile = self._api_get(self.userinfo_endpoint, access_token)
        if not isinstance(profile, Mapping):
            raise OAuthIdentityError(OAuthFailure.USERINFO_FAILED, "Provider profile response is malformed")
        return profile

    def identity_from_profile(self, connection: ConnectionConfig, profile: Mapping[str, Any]) -> ExternalIdentity:
        raise NotImplementedError

    async def resolve_identity(
        self,
        connection: ConnectionConfig,
        tx: OAuthTransaction,
        tokens: TokenResponse,
    ) -> ExternalIdentity:
        access_token = str(tokens.get("access_token") or "")
        if not access_token:
            raise OAuthIdentityError(OAuthFailure.USERINFO_FAILED, "Token response is missing access_token")
        try:
            profile = await asyncio.to_thread(self.fetch_profile, connection, access_token)
        except OAuthIdentityError:
            raise
        except (OAuthHTTPError, UnsafeURLError) as exc:
            raise OAuthIdentityError(OAuthFailure.USERINFO_FAILED, "Provider profile request failed") from exc
        return self.identity_from_profile(connection, profile)

    def enforce_restrictions(self, connection: ConnectionConfig, identity: ExternalIdentity) -> None:
        return None


__all__ = ["OAuth2UserInfoAdapter"]
