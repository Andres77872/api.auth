"""Microsoft Entra ID adapter.

Three things differ from a plain OIDC provider (docs/agnostic_oauth/04):

* ``sub`` is pairwise per application, so the identity subject is ``oid`` and the
  namespace is ``microsoft:<tid>``. Two projects with two client ids still see the
  same person as the same user.
* The issuer is per tenant. The multi-tenant discovery document carries an issuer
  *template*, so the issuer is validated against the token's own ``tid`` claim and
  the connection's tenant allow-list rather than by string equality.
* ``email`` is tenant-administrator-controlled and is never trusted for identity.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from src.Util.oauth.adapters.oidc import GenericOIDCAdapter
from src.Util.oauth.provider import (
    EMAIL_TRUST_ADMIN_CONTROLLED,
    SUBJECT_SCOPE_TENANT,
    ConnectionConfig,
    ExternalIdentity,
    OAuthFailure,
    OAuthIdentityError,
    ProviderCapabilities,
)


_TENANT_ALIASES = {"common", "organizations", "consumers"}
_GUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_AUTHORITY = "https://login.microsoftonline.com"
MICROSOFT_DEFAULT_SCOPES = "openid profile email"


def _tenant(connection: ConnectionConfig) -> str:
    params = connection.provider_params if isinstance(connection.provider_params, Mapping) else {}
    return str(params.get("tenant") or "common").strip().lower()


class MicrosoftAdapter(GenericOIDCAdapter):
    provider_type = "microsoft"
    capabilities = ProviderCapabilities(
        protocol="oidc",
        pkce=True,
        nonce=True,
        subject_scope=SUBJECT_SCOPE_TENANT,
        email_trust=EMAIL_TRUST_ADMIN_CONTROLLED,
        tenant_configurable_endpoints=False,
    )
    allowed_algorithms = ("RS256",)
    subject_claim = "oid"

    def identity_namespace(self, connection: ConnectionConfig) -> str:
        tenant = _tenant(connection)
        return f"microsoft:{tenant}" if _GUID_RE.fullmatch(tenant) else "microsoft:*"

    def validate_connection(self, connection: ConnectionConfig) -> list[str]:
        problems: list[str] = []
        if not connection.client_id:
            problems.append("client_id is required")
        scopes = set(connection.scopes.split())
        if not {"openid", "profile"} <= scopes:
            problems.append("scopes must include 'openid' and 'profile' (the oid claim requires profile)")
        tenant = _tenant(connection)
        if tenant not in _TENANT_ALIASES and not _GUID_RE.fullmatch(tenant):
            problems.append("provider_params.tenant must be a tenant GUID, 'common', 'organizations' or 'consumers'")
        for tenant_id in connection.restriction_list("tenant_ids"):
            if not _GUID_RE.fullmatch(tenant_id):
                problems.append(f"tenant id is malformed: {tenant_id}")
        for attribute in ("discovery_url", "authorize_endpoint", "token_endpoint", "jwks_uri", "userinfo_endpoint"):
            if getattr(connection, attribute, None):
                problems.append(f"{attribute} cannot be set for provider type 'microsoft'")
        return problems

    def _endpoint(self, connection: ConnectionConfig, attribute: str, discovery_key: str) -> str:
        tenant = _tenant(connection)
        return {
            "authorize_endpoint": f"{_AUTHORITY}/{tenant}/oauth2/v2.0/authorize",
            "token_endpoint": f"{_AUTHORITY}/{tenant}/oauth2/v2.0/token",
            "jwks_uri": f"{_AUTHORITY}/{tenant}/discovery/v2.0/keys",
        }[attribute]

    def _allowed_tenants(self, connection: ConnectionConfig) -> set[str]:
        allowed = {tenant.lower() for tenant in connection.restriction_list("tenant_ids")}
        tenant = _tenant(connection)
        if _GUID_RE.fullmatch(tenant):
            allowed.add(tenant)
        return allowed

    def issuer_is_valid(self, connection: ConnectionConfig, issuer: str, claims: Mapping[str, Any]) -> bool:
        tenant_id = str(claims.get("tid") or "").lower()
        if not _GUID_RE.fullmatch(tenant_id):
            return False
        if issuer != f"{_AUTHORITY}/{tenant_id}/v2.0":
            return False
        allowed = self._allowed_tenants(connection)
        return not allowed or tenant_id in allowed

    def claims_namespace(self, connection: ConnectionConfig, claims: Mapping[str, Any]) -> str:
        return f"microsoft:{str(claims.get('tid') or '').lower()}"

    def identity_from_claims(self, connection: ConnectionConfig, claims: Mapping[str, Any]) -> ExternalIdentity:
        if not _GUID_RE.fullmatch(str(claims.get("tid") or "")):
            raise OAuthIdentityError(OAuthFailure.ISSUER_MISMATCH, "Microsoft tenant id is missing")
        identity = super().identity_from_claims(connection, claims)
        # The email claim is set by the tenant administrator: display only, never verified.
        return ExternalIdentity(
            provider_type=identity.provider_type,
            identity_namespace=identity.identity_namespace,
            subject=identity.subject,
            email=identity.email,
            email_verified=False,
            email_trust=EMAIL_TRUST_ADMIN_CONTROLLED,
            display_name=identity.display_name,
            attributes={"tid": str(claims.get("tid") or "").lower()},
        )


__all__ = ["MICROSOFT_DEFAULT_SCOPES", "MicrosoftAdapter"]
