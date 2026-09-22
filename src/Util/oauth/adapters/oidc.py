"""Discovery-driven generic OIDC adapter; base class for Google, Microsoft, Apple.

Configurable purely by connection data, so adding a standards-compliant IdP is a
data operation. Because its endpoints are tenant-supplied, this type carries the
mix-up and SSRF surface and stays root-managed (docs/agnostic_oauth/04, R-03/R-04).
"""

from __future__ import annotations

import asyncio
from typing import Any, Mapping
from urllib.parse import urlencode

from src.Util.oauth.http import OAuthHTTPError, guarded_post_form, load_discovery
from src.Util.oauth.oidc_verifier import ALLOWED_ID_TOKEN_ALGORITHMS, verify_oidc_id_token
from src.Util.oauth.provider import (
    EMAIL_TRUST_ADMIN_CONTROLLED,
    SUBJECT_SCOPE_ISSUER,
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
from src.Util.oauth.url_safety import UnsafeURLError, assert_safe_outbound_url


def coerce_bool_claim(value: Any) -> bool:
    """Normalise ``email_verified``: Apple and some IdPs send the string ``"true"``."""

    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() == "true"
    return False


class GenericOIDCAdapter:
    provider_type = "oidc"
    capabilities = ProviderCapabilities(
        protocol="oidc",
        pkce=True,
        nonce=True,
        subject_scope=SUBJECT_SCOPE_ISSUER,
        email_trust=EMAIL_TRUST_ADMIN_CONTROLLED,
        tenant_configurable_endpoints=True,
    )
    allowed_algorithms: tuple[str, ...] = ALLOWED_ID_TOKEN_ALGORITHMS
    subject_claim = "sub"

    # ----------------------------------------------------------------- configuration
    def identity_namespace(self, connection: ConnectionConfig) -> str:
        issuer = connection.issuers[0] if connection.issuers else ""
        return f"oidc:{issuer}"

    def validate_connection(self, connection: ConnectionConfig) -> list[str]:
        problems: list[str] = []
        if not connection.client_id:
            problems.append("client_id is required")
        scopes = set(connection.scopes.split())
        if "openid" not in scopes:
            problems.append("scopes must include 'openid'")
        if not connection.issuers:
            problems.append("issuer is required")
        if not connection.discovery_url and not (
            connection.authorize_endpoint and connection.token_endpoint and connection.jwks_uri
        ):
            problems.append("either discovery_url or authorize/token/jwks endpoints are required")
        for label, url in (
            ("discovery_url", connection.discovery_url),
            ("authorize_endpoint", connection.authorize_endpoint),
            ("token_endpoint", connection.token_endpoint),
            ("jwks_uri", connection.jwks_uri),
            ("userinfo_endpoint", connection.userinfo_endpoint),
        ):
            if not url:
                continue
            try:
                # Shape/scheme check only at write time; resolution is re-checked on every fetch.
                assert_safe_outbound_url(url, resolver=lambda host: ["93.184.216.34"])
            except UnsafeURLError as exc:
                problems.append(f"{label}: {exc}")
        return problems

    def _endpoint(self, connection: ConnectionConfig, attribute: str, discovery_key: str) -> str:
        explicit = getattr(connection, attribute, None)
        if explicit:
            return str(explicit)
        if not connection.discovery_url:
            raise OAuthExchangeError(f"{attribute} is not configured", failure=OAuthFailure.PROVIDER_MISCONFIGURED)
        try:
            document = load_discovery(connection.discovery_url, expected_issuers=tuple(connection.issuers))
        except (OAuthHTTPError, UnsafeURLError) as exc:
            raise OAuthExchangeError("Discovery document is unavailable", failure=OAuthFailure.PROVIDER_MISCONFIGURED) from exc
        value = str(document.get(discovery_key) or "")
        if not value:
            raise OAuthExchangeError(f"Discovery document has no {discovery_key}", failure=OAuthFailure.PROVIDER_MISCONFIGURED)
        return value

    # ------------------------------------------------------------------- authorize
    def extra_authorization_params(self, connection: ConnectionConfig, tx: OAuthTransaction) -> dict[str, Any]:
        return {}

    def build_authorization_url(self, connection: ConnectionConfig, tx: OAuthTransaction) -> str:
        endpoint = self._endpoint(connection, "authorize_endpoint", "authorization_endpoint")
        # Parameter order is part of the golden URL contract for the Google connection.
        params: dict[str, Any] = {
            "response_type": "code",
            "client_id": connection.client_id,
            "redirect_uri": tx.redirect_uri,
            "scope": connection.scopes,
            "state": tx.state,
        }
        if self.capabilities.nonce:
            params["nonce"] = tx.nonce
        if self.capabilities.pkce:
            params["code_challenge"] = tx.code_challenge
            params["code_challenge_method"] = "S256"
        for key, value in self.extra_authorization_params(connection, tx).items():
            if value is not None:
                params[str(key)] = value
        if tx.prompt and tx.prompt != "consent":
            params["prompt"] = tx.prompt
        # Login never asks for offline access or a refresh token.
        params.pop("access_type", None)
        return f"{endpoint}?{urlencode(params)}"

    # -------------------------------------------------------------------- exchange
    def client_authentication(self, connection: ConnectionConfig, secrets: ConnectionSecrets) -> dict[str, str]:
        if not secrets.client_secret:
            raise OAuthExchangeError("client secret is not available", failure=OAuthFailure.PROVIDER_MISCONFIGURED)
        return {"client_id": connection.client_id, "client_secret": secrets.client_secret}

    async def exchange_code(
        self,
        connection: ConnectionConfig,
        secrets: ConnectionSecrets,
        tx: OAuthTransaction,
        callback: CallbackParams,
    ) -> TokenResponse:
        endpoint = self._endpoint(connection, "token_endpoint", "token_endpoint")
        data = {
            "grant_type": "authorization_code",
            "code": callback.code,
            "redirect_uri": tx.redirect_uri,
            **self.client_authentication(connection, secrets),
        }
        if self.capabilities.pkce:
            data["code_verifier"] = tx.code_verifier
        try:
            payload = await asyncio.to_thread(guarded_post_form, endpoint, data=data)
        except (OAuthHTTPError, UnsafeURLError) as exc:
            raise OAuthExchangeError("Authorization code exchange failed") from exc
        if self.capabilities.protocol == "oidc" and not payload.get("id_token"):
            raise OAuthExchangeError("Token response is missing id_token")
        return TokenResponse(payload)

    # -------------------------------------------------------------------- identity
    def issuer_is_valid(self, connection: ConnectionConfig, issuer: str, claims: Mapping[str, Any]) -> bool:
        return issuer in tuple(connection.issuers)

    def normalize_claims(self, connection: ConnectionConfig, claims: Mapping[str, Any]) -> dict[str, Any]:
        normalized = dict(claims)
        if "email_verified" in normalized:
            normalized["email_verified"] = coerce_bool_claim(normalized.get("email_verified"))
        return normalized

    def verify_id_token(self, connection: ConnectionConfig, tx: OAuthTransaction, id_token: str) -> dict[str, Any]:
        jwks_uri = self._endpoint(connection, "jwks_uri", "jwks_uri")
        return verify_oidc_id_token(
            id_token,
            client_id=connection.client_id,
            issuers=tuple(connection.issuers),
            jwks_uri=jwks_uri,
            expected_nonce=tx.nonce if self.capabilities.nonce else None,
            leeway_seconds=connection.leeway_seconds,
            jwks_cache_ttl_seconds=connection.jwks_cache_ttl_seconds,
            allowed_algorithms=self.allowed_algorithms,
            issuer_validator=lambda issuer, claims: self.issuer_is_valid(connection, issuer, claims),
        )

    def identity_from_claims(self, connection: ConnectionConfig, claims: Mapping[str, Any]) -> ExternalIdentity:
        normalized = self.normalize_claims(connection, claims)
        subject = str(normalized.get(self.subject_claim) or "")
        if not subject:
            raise OAuthIdentityError(OAuthFailure.SUBJECT_MISSING, "Provider subject is missing")
        email = str(normalized.get("email") or "").strip().lower() or None
        return ExternalIdentity(
            provider_type=self.provider_type,
            identity_namespace=self.claims_namespace(connection, normalized),
            subject=subject,
            email=email,
            email_verified=bool(normalized.get("email_verified", False)),
            email_trust=self.capabilities.email_trust,
            display_name=None,
            attributes=self.identity_attributes(connection, normalized),
        )

    def claims_namespace(self, connection: ConnectionConfig, claims: Mapping[str, Any]) -> str:
        return connection.identity_namespace or self.identity_namespace(connection)

    def identity_attributes(self, connection: ConnectionConfig, claims: Mapping[str, Any]) -> dict[str, str]:
        return {}

    async def resolve_identity(
        self,
        connection: ConnectionConfig,
        tx: OAuthTransaction,
        tokens: TokenResponse,
    ) -> ExternalIdentity:
        id_token = str(tokens.get("id_token") or "")
        if not id_token:
            raise OAuthIdentityError(OAuthFailure.ID_TOKEN_INVALID, "Token response is missing id_token")
        claims = await asyncio.to_thread(self.verify_id_token, connection, tx, id_token)
        return self.identity_from_claims(connection, claims)

    def enforce_restrictions(self, connection: ConnectionConfig, identity: ExternalIdentity) -> None:
        return None


__all__ = ["GenericOIDCAdapter", "coerce_bool_claim"]
