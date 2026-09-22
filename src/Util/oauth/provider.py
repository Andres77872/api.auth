"""Provider adapter contract.

An adapter turns *a connection plus a callback* into an :class:`ExternalIdentity`
and nothing else. It never touches the database, Redis, sessions or HTTP
responses, and provider tokens never leave it. Everything downstream of the
identity is shared and provider-blind (:mod:`src.Util.oauth.pipeline`).

Security capabilities are declared in code per provider *type*. A tenant can
choose scopes and restrictions on a connection; it cannot turn off PKCE, nonce
or signature checks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Protocol, runtime_checkable


class OAuthFailure(str, Enum):
    """Closed classification of adapter failures.

    Replaces substring-matching on exception messages. Each value maps to exactly
    one neutral public error code in the pipeline.
    """

    PROVIDER_MISCONFIGURED = "provider_misconfigured"
    CODE_EXCHANGE_FAILED = "code_exchange_failed"
    ID_TOKEN_INVALID = "id_token_invalid"
    NONCE_MISMATCH = "nonce_mismatch"
    ISSUER_MISMATCH = "issuer_mismatch"
    AUDIENCE_MISMATCH = "audience_mismatch"
    TOKEN_EXPIRED = "token_expired"
    RESTRICTION_DENIED = "restriction_denied"
    USERINFO_FAILED = "userinfo_failed"
    SUBJECT_MISSING = "subject_missing"


class OAuthProviderError(RuntimeError):
    """Base adapter error carrying a closed failure classification."""

    def __init__(self, failure: OAuthFailure, message: str | None = None) -> None:
        self.failure = failure
        super().__init__(message or failure.value)


class OAuthExchangeError(OAuthProviderError):
    """Authorization-code exchange failed."""

    def __init__(self, message: str | None = None, *, failure: OAuthFailure = OAuthFailure.CODE_EXCHANGE_FAILED) -> None:
        super().__init__(failure, message)


class OAuthIdentityError(OAuthProviderError):
    """The provider response could not be turned into a trusted identity."""


class OAuthProviderUnknown(LookupError):
    """No adapter is registered for the requested provider type."""


EMAIL_TRUST_VERIFIED = "verified_by_provider"
EMAIL_TRUST_UNVERIFIED = "unverified"
EMAIL_TRUST_ADMIN_CONTROLLED = "admin_controlled"

SUBJECT_SCOPE_GLOBAL = "global"
SUBJECT_SCOPE_ISSUER = "issuer"
SUBJECT_SCOPE_TENANT = "tenant"
SUBJECT_SCOPE_TEAM = "team"


@dataclass(frozen=True)
class ProviderCapabilities:
    protocol: str  # "oidc" | "oauth2"
    pkce: bool = True
    nonce: bool = True
    issuer_response_param: bool = False
    callback_methods: frozenset[str] = frozenset({"GET"})
    subject_scope: str = SUBJECT_SCOPE_GLOBAL
    email_trust: str = EMAIL_TRUST_UNVERIFIED
    supports_login: bool = True
    tenant_configurable_endpoints: bool = False

    def as_metadata(self) -> dict[str, Any]:
        return {
            "protocol": self.protocol,
            "pkce": self.pkce,
            "nonce": self.nonce,
            "issuer_response_param": self.issuer_response_param,
            "callback_methods": sorted(self.callback_methods),
            "subject_scope": self.subject_scope,
            "email_trust": self.email_trust,
            "supports_login": self.supports_login,
            "tenant_configurable_endpoints": self.tenant_configurable_endpoints,
        }


@dataclass(frozen=True)
class ExternalIdentity:
    """Normalised identity returned by every adapter. Carries no provider tokens."""

    provider_type: str
    identity_namespace: str
    subject: str = field(repr=False)
    email: str | None = field(default=None, repr=False)
    email_verified: bool = False
    email_trust: str = EMAIL_TRUST_UNVERIFIED
    display_name: str | None = field(default=None, repr=False)
    attributes: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ConnectionConfig:
    """Non-secret configuration of one OAuth client at one provider."""

    connection_id: str
    provider_type: str
    client_id: str
    scopes: str
    identity_namespace: str
    display_name: str = ""
    issuers: tuple[str, ...] = ()
    discovery_url: str | None = None
    authorize_endpoint: str | None = None
    token_endpoint: str | None = None
    jwks_uri: str | None = None
    userinfo_endpoint: str | None = None
    restrictions: Mapping[str, Any] = field(default_factory=dict)
    provider_params: Mapping[str, Any] = field(default_factory=dict)
    leeway_seconds: int = 30
    jwks_cache_ttl_seconds: int = 3600

    def restriction_list(self, name: str) -> tuple[str, ...]:
        raw = self.restrictions.get(name) if isinstance(self.restrictions, Mapping) else None
        if isinstance(raw, str):
            raw = raw.split(",")
        if not isinstance(raw, (list, tuple, set, frozenset)):
            return ()
        return tuple(str(item).strip() for item in raw if str(item).strip())


@dataclass(frozen=True)
class ConnectionSecrets:
    """Decrypted secrets, alive only for the duration of one token exchange."""

    client_secret: str | None = field(default=None, repr=False)
    signing_key: str | None = field(default=None, repr=False)


@dataclass(frozen=True)
class OAuthTransaction:
    """Server-side transaction material bound at start and recovered from state."""

    state: str = field(repr=False)
    nonce: str = field(repr=False)
    code_verifier: str = field(repr=False)
    code_challenge: str
    redirect_uri: str
    purpose: str = "login"
    prompt: str | None = None


@dataclass(frozen=True)
class CallbackParams:
    code: str = field(repr=False)
    state: str = field(repr=False)
    iss: str | None = None
    raw_request: Any = field(default=None, repr=False, compare=False)


class TokenResponse(dict):
    """Provider token response whose repr never leaks token material."""

    def __repr__(self) -> str:  # pragma: no cover - defensive
        return f"TokenResponse(keys={sorted(self.keys())})"

    __str__ = __repr__


@runtime_checkable
class OAuthProviderAdapter(Protocol):
    provider_type: str
    capabilities: ProviderCapabilities

    def identity_namespace(self, connection: ConnectionConfig) -> str:
        """Namespace that scopes this connection's subjects (see docs/agnostic_oauth/04)."""

    def validate_connection(self, connection: ConnectionConfig) -> list[str]:
        """Static validation at admin-write time. Returns human-readable problems."""

    def build_authorization_url(self, connection: ConnectionConfig, tx: OAuthTransaction) -> str: ...

    async def exchange_code(
        self,
        connection: ConnectionConfig,
        secrets: ConnectionSecrets,
        tx: OAuthTransaction,
        callback: CallbackParams,
    ) -> TokenResponse: ...

    async def resolve_identity(
        self,
        connection: ConnectionConfig,
        tx: OAuthTransaction,
        tokens: TokenResponse,
    ) -> ExternalIdentity: ...

    def enforce_restrictions(self, connection: ConnectionConfig, identity: ExternalIdentity) -> None: ...


__all__ = [
    "CallbackParams",
    "ConnectionConfig",
    "ConnectionSecrets",
    "EMAIL_TRUST_ADMIN_CONTROLLED",
    "EMAIL_TRUST_UNVERIFIED",
    "EMAIL_TRUST_VERIFIED",
    "ExternalIdentity",
    "OAuthExchangeError",
    "OAuthFailure",
    "OAuthIdentityError",
    "OAuthProviderAdapter",
    "OAuthProviderError",
    "OAuthProviderUnknown",
    "OAuthTransaction",
    "ProviderCapabilities",
    "SUBJECT_SCOPE_GLOBAL",
    "SUBJECT_SCOPE_ISSUER",
    "SUBJECT_SCOPE_TEAM",
    "SUBJECT_SCOPE_TENANT",
    "TokenResponse",
]
