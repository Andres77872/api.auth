"""DTOs for the OAuth admin API.

Secrets are WRITE-ONLY. No response model has a field that could carry a client
secret, signing key, ciphertext or HMAC: responses expose presence flags, a
12-character fingerprint and timestamps only. ``OAUTH_DTO_FORBIDDEN_FIELD_NAMES``
is asserted by tests against every response model in this module.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


OAUTH_DTO_FORBIDDEN_FIELD_NAMES = frozenset(
    {
        "client_secret",
        "client_secret_ciphertext",
        "client_secret_hmac",
        "signing_key",
        "signing_key_ciphertext",
        "signing_key_hmac",
        "legacy_redeem_token",
        "legacy_redeem_token_ciphertext",
        "legacy_redeem_url_ciphertext",
        "access_token",
        "refresh_token",
        "id_token",
    }
)

ProvisioningMode = Literal["disabled", "link_only", "auto_create", "both"]
ExistingUserPolicy = Literal["deny", "join_default_group"]
ConnectionStatus = Literal["draft", "active", "disabled", "archived"]
CatalogStatus = Literal["disabled", "enabled", "degraded", "archived"]
UrlKind = Literal["redirect_uri", "return_origin"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ────────────────────────────────────────────────────────────────────── requests

class ProviderCatalogUpdate(_Model):
    status: Optional[CatalogStatus] = None
    login_enabled: Optional[bool] = None
    link_enabled: Optional[bool] = None


class ConnectionCreate(_Model):
    provider_type: str = Field(..., min_length=1, max_length=32)
    display_name: str = Field(..., min_length=1, max_length=120)
    client_id: str = Field(..., min_length=1, max_length=512)
    scopes: Optional[str] = Field(default=None, max_length=512)
    owner_project_hash: Optional[str] = Field(default=None, max_length=255)
    issuer: Optional[str] = Field(default=None, max_length=512)
    discovery_url: Optional[str] = Field(default=None, max_length=1024)
    authorize_endpoint: Optional[str] = Field(default=None, max_length=1024)
    token_endpoint: Optional[str] = Field(default=None, max_length=1024)
    jwks_uri: Optional[str] = Field(default=None, max_length=1024)
    userinfo_endpoint: Optional[str] = Field(default=None, max_length=1024)
    restrictions: Optional[dict[str, Any]] = None
    provider_params: Optional[dict[str, Any]] = None

    @field_validator("provider_type")
    @classmethod
    def _lower(cls, value: str) -> str:
        return value.lower()


class ConnectionUpdate(_Model):
    display_name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    client_id: Optional[str] = Field(default=None, min_length=1, max_length=512)
    scopes: Optional[str] = Field(default=None, max_length=512)
    issuer: Optional[str] = Field(default=None, max_length=512)
    discovery_url: Optional[str] = Field(default=None, max_length=1024)
    authorize_endpoint: Optional[str] = Field(default=None, max_length=1024)
    token_endpoint: Optional[str] = Field(default=None, max_length=1024)
    jwks_uri: Optional[str] = Field(default=None, max_length=1024)
    userinfo_endpoint: Optional[str] = Field(default=None, max_length=1024)
    restrictions: Optional[dict[str, Any]] = None
    provider_params: Optional[dict[str, Any]] = None


class ConnectionCredentialsUpdate(_Model):
    """Write-only. Sent as JSON so secrets never land in URL-encoded request logs."""

    client_secret: Optional[str] = Field(default=None, min_length=1, max_length=4096, repr=False)
    signing_key: Optional[str] = Field(default=None, min_length=1, max_length=16384, repr=False)


class BindingUpsert(_Model):
    connection_hash: str = Field(..., min_length=1, max_length=255)
    enabled: Optional[bool] = None
    login_enabled: Optional[bool] = None
    link_enabled: Optional[bool] = None
    provisioning_mode: Optional[ProvisioningMode] = None
    default_user_group_hash: Optional[str] = Field(default=None, max_length=255)
    existing_user_policy: Optional[ExistingUserPolicy] = None
    state_ttl_seconds: Optional[int] = Field(default=None, ge=30, le=600)


class BindingUrlCreate(_Model):
    kind: UrlKind
    url: str = Field(..., min_length=1, max_length=2048)


class LegacyRedeemUpdate(_Model):
    """Write-only companion-handshake bridge (``init_mode='legacy_redeem'``). Root only."""

    redeem_url: str = Field(..., min_length=1, max_length=2048, repr=False)
    redeem_token: str = Field(..., min_length=1, max_length=4096, repr=False)


# ───────────────────────────────────────────────────────────────────── responses

class _Response(BaseModel):
    model_config = ConfigDict(extra="ignore")


class ProviderCatalogEntry(_Response):
    provider_type: str
    display_name: str
    protocol: str
    status: str
    login_enabled: bool = False
    link_enabled: bool = False
    tenant_endpoints_allowed: bool = False
    default_scopes: Optional[str] = None
    adapter_registered: bool = False
    capabilities: Optional[dict[str, Any]] = None
    connection_count: int = 0


class CredentialsStatus(_Response):
    credential_status: str = "absent"
    has_client_secret: bool = False
    has_signing_key: bool = False
    client_secret_fingerprint: Optional[str] = None
    signing_key_fingerprint: Optional[str] = None
    credential_key_id: Optional[str] = None
    credentials_set_at: Optional[datetime] = None


class ConnectionInfo(_Response):
    connection_hash: str
    provider_type: str
    display_name: str
    status: str
    client_id: Optional[str] = None
    scopes: Optional[str] = None
    identity_namespace: Optional[str] = None
    owner_project_hash: Optional[str] = None
    owner_project_name: Optional[str] = None
    issuer: Optional[str] = None
    discovery_url: Optional[str] = None
    authorize_endpoint: Optional[str] = None
    token_endpoint: Optional[str] = None
    jwks_uri: Optional[str] = None
    userinfo_endpoint: Optional[str] = None
    restrictions: Optional[dict[str, Any]] = None
    provider_params: Optional[dict[str, Any]] = None
    tenant_endpoints_allowed: bool = False
    catalog_status: Optional[str] = None
    binding_count: int = 0
    linked_identity_count: int = 0
    namespace_locked: bool = False
    credentials: CredentialsStatus = Field(default_factory=CredentialsStatus)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class AllowedUrl(_Response):
    id: str
    kind: str
    url: str
    created_at: Optional[datetime] = None


class ReadinessCheck(_Response):
    check: str
    ok: bool
    message: str


class BindingInfo(_Response):
    connection_key: str
    connection_hash: str
    provider_type: str
    connection_display_name: str
    connection_status: str
    credential_status: str
    project_hash: str
    project_name: Optional[str] = None
    enabled: bool = False
    login_enabled: bool = True
    link_enabled: bool = True
    provisioning_mode: str = "disabled"
    default_user_group_hash: Optional[str] = None
    default_user_group_name: Optional[str] = None
    existing_user_policy: str = "deny"
    init_mode: str = "api"
    has_legacy_redeem: bool = False
    delivery_mode: str = "bff"
    state_ttl_seconds: Optional[int] = None
    urls: list[AllowedUrl] = Field(default_factory=list)
    ready: bool = False
    readiness: list[ReadinessCheck] = Field(default_factory=list)


class CredentialProbeResult(_Response):
    valid: bool
    problems: list[str] = Field(default_factory=list)
    client_secret_fingerprint: Optional[str] = None


__all__ = [
    "AllowedUrl",
    "BindingInfo",
    "BindingUpsert",
    "BindingUrlCreate",
    "ConnectionCreate",
    "ConnectionCredentialsUpdate",
    "ConnectionInfo",
    "ConnectionUpdate",
    "CredentialProbeResult",
    "CredentialsStatus",
    "LegacyRedeemUpdate",
    "OAUTH_DTO_FORBIDDEN_FIELD_NAMES",
    "ProviderCatalogEntry",
    "ProviderCatalogUpdate",
    "ReadinessCheck",
]
