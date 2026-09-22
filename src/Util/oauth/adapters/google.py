"""Google OIDC adapter.

Endpoints are compiled in: a connection of type ``google`` can never point the
server at tenant-supplied URLs. Google's ``sub`` is unique across all Google
accounts and identical for every client id, so the identity namespace is the
constant ``google`` -- the same person is the same user at every project.
"""

from __future__ import annotations

import asyncio
from typing import Any, Mapping

from src.Util.google_id_token_verifier import GoogleIDTokenValidationError, GoogleIDTokenVerifier
from src.Util.oauth.adapters.oidc import GenericOIDCAdapter
from src.Util.oauth.provider import (
    EMAIL_TRUST_VERIFIED,
    SUBJECT_SCOPE_GLOBAL,
    ConnectionConfig,
    ExternalIdentity,
    OAuthFailure,
    OAuthIdentityError,
    OAuthTransaction,
    ProviderCapabilities,
)


GOOGLE_DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"
GOOGLE_AUTHORIZE_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_JWKS_URI = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = ("https://accounts.google.com", "accounts.google.com")
GOOGLE_DEFAULT_SCOPES = "openid email"
GOOGLE_NAMESPACE = "google"

_FAILURES = {failure.value: failure for failure in OAuthFailure}


class GoogleAdapter(GenericOIDCAdapter):
    provider_type = "google"
    capabilities = ProviderCapabilities(
        protocol="oidc",
        pkce=True,
        nonce=True,
        subject_scope=SUBJECT_SCOPE_GLOBAL,
        email_trust=EMAIL_TRUST_VERIFIED,
        tenant_configurable_endpoints=False,
    )
    allowed_algorithms = ("RS256",)

    def identity_namespace(self, connection: ConnectionConfig) -> str:
        return GOOGLE_NAMESPACE

    def validate_connection(self, connection: ConnectionConfig) -> list[str]:
        problems: list[str] = []
        if not connection.client_id:
            problems.append("client_id is required")
        if set(connection.scopes.split()) != {"openid", "email"}:
            problems.append("scopes must be exactly 'openid email'")
        for domain in connection.restriction_list("hosted_domains"):
            if "/" in domain or " " in domain:
                problems.append(f"hosted domain is malformed: {domain}")
        return problems

    def _endpoint(self, connection: ConnectionConfig, attribute: str, discovery_key: str) -> str:
        # Test doubles and the legacy environment overrides may set explicit endpoints on
        # the environment-sourced connection; database connections of this type never can.
        explicit = getattr(connection, attribute, None)
        if explicit:
            return str(explicit)
        return {
            "authorize_endpoint": GOOGLE_AUTHORIZE_ENDPOINT,
            "token_endpoint": GOOGLE_TOKEN_ENDPOINT,
            "jwks_uri": GOOGLE_JWKS_URI,
        }[attribute]

    def _issuers(self, connection: ConnectionConfig) -> tuple[str, ...]:
        return tuple(connection.issuers) or GOOGLE_ISSUERS

    def cross_check_enabled(self, connection: ConnectionConfig) -> bool:
        params = connection.provider_params if isinstance(connection.provider_params, Mapping) else {}
        return bool(params.get("google_auth_cross_check", True))

    def verify_id_token(self, connection: ConnectionConfig, tx: OAuthTransaction, id_token: str) -> dict[str, Any]:
        verifier = GoogleIDTokenVerifier(
            client_id=connection.client_id,
            jwks_uri=self._endpoint(connection, "jwks_uri", "jwks_uri"),
            issuers=self._issuers(connection),
            leeway_seconds=connection.leeway_seconds,
            jwks_cache_ttl_seconds=connection.jwks_cache_ttl_seconds,
            allowed_hosted_domains=connection.restriction_list("hosted_domains"),
            google_auth_verifier=None if self.cross_check_enabled(connection) else (lambda token, **_: _unverified(token)),
        )
        try:
            return verifier.verify(id_token, expected_nonce=tx.nonce)
        except GoogleIDTokenValidationError as exc:
            failure = _FAILURES.get(str(getattr(exc, "failure", "")), OAuthFailure.ID_TOKEN_INVALID)
            raise OAuthIdentityError(failure, str(exc)) from exc

    def identity_attributes(self, connection: ConnectionConfig, claims: Mapping[str, Any]) -> dict[str, str]:
        hosted_domain = str(claims.get("hd") or "").strip().lower()
        return {"hd": hosted_domain} if hosted_domain else {}

    def claims_namespace(self, connection: ConnectionConfig, claims: Mapping[str, Any]) -> str:
        return GOOGLE_NAMESPACE

    async def resolve_identity(self, connection, tx, tokens) -> ExternalIdentity:
        id_token = str(tokens.get("id_token") or "")
        if not id_token:
            raise OAuthIdentityError(OAuthFailure.ID_TOKEN_INVALID, "Token response is missing id_token")
        claims = await asyncio.to_thread(self.verify_id_token, connection, tx, id_token)
        return self.identity_from_claims(connection, claims)


def _unverified(id_token: str) -> dict[str, Any]:
    """Claims for the agreement check when the google-auth cross-check is switched off.

    The token has already passed local signature and claim validation at this point;
    this only feeds the verifier's "both checks agree" comparison with the same claims.
    """

    import base64
    import json

    segment = id_token.split(".")[1]
    padding = "=" * (-len(segment) % 4)
    return json.loads(base64.urlsafe_b64decode((segment + padding).encode("ascii")).decode("utf-8"))


__all__ = [
    "GOOGLE_AUTHORIZE_ENDPOINT",
    "GOOGLE_DEFAULT_SCOPES",
    "GOOGLE_DISCOVERY_URL",
    "GOOGLE_ISSUERS",
    "GOOGLE_JWKS_URI",
    "GOOGLE_NAMESPACE",
    "GOOGLE_TOKEN_ENDPOINT",
    "GoogleAdapter",
]
