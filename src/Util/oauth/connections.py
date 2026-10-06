"""Resolve database connections and project bindings. All enablement layers must permit OAuth."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from src.Util.auth_constants import OAUTH_EXISTING_USER_DENY, OAUTH_PROVISIONING_AUTO_CREATE, OAUTH_PROVISIONING_BOTH, OAUTH_PROVISIONING_DISABLED, OAUTH_PROVISIONING_LINK_ONLY
from src.Util.oauth.provider import ConnectionConfig, ConnectionSecrets, OAuthProviderAdapter
from src.Util.oauth.settings import OAuthDeploymentSettings, load_oauth_settings


UNAVAILABLE_NOT_CONFIGURED = "not_configured"
UNAVAILABLE_DISABLED = "disabled"


class OAuthConnectionUnavailable(RuntimeError):
    """The requested connection cannot be used. ``reason`` is operator-facing only."""

    def __init__(self, kind: str, reason: str) -> None:
        self.kind = kind
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class ProjectBinding:
    binding_id: str
    connection_key: str
    project_id: str | None = field(default=None, repr=False)
    project_hash: str | None = field(default=None, repr=False)
    enabled: bool = False
    login_enabled: bool = True
    link_enabled: bool = True
    provisioning_mode: str = OAUTH_PROVISIONING_DISABLED
    default_user_group_id: str | None = field(default=None, repr=False)
    default_user_group_hash: str | None = field(default=None, repr=False)
    existing_user_policy: str = OAUTH_EXISTING_USER_DENY
    delivery_mode: str = "bff"
    redirect_uris: tuple[str, ...] = ()
    return_origins: tuple[str, ...] = ()
    state_ttl_seconds: int | None = None

    @property
    def can_auto_create(self) -> bool:
        return self.provisioning_mode in {OAUTH_PROVISIONING_AUTO_CREATE, OAUTH_PROVISIONING_BOTH}

    @property
    def can_link(self) -> bool:
        return self.link_enabled and self.provisioning_mode in {OAUTH_PROVISIONING_LINK_ONLY, OAUTH_PROVISIONING_BOTH}


    def is_redirect_uri_allowed(self, redirect_uri: str | None) -> bool:
        return bool(redirect_uri) and str(redirect_uri) in self.redirect_uris

    def is_return_origin_allowed(self, return_origin: str | None) -> bool:
        return bool(return_origin) and str(return_origin) in self.return_origins

    def sole_redirect_uri(self) -> str | None:
        """The redirect URI when exactly one is configured; never "the first of many"."""

        return self.redirect_uris[0] if len(self.redirect_uris) == 1 else None

    def sole_return_origin(self) -> str | None:
        """The return origin when exactly one is configured; never "the first of many"."""

        return self.return_origins[0] if len(self.return_origins) == 1 else None


@dataclass(frozen=True)
class ResolvedConnection:
    config: ConnectionConfig
    binding: ProjectBinding
    adapter: OAuthProviderAdapter


class ConnectionSource(Protocol):
    name: str

    def get_binding(self, *, project_hash: str | None, connection_key: str) -> ResolvedConnection: ...

    def get_by_ids(self, *, connection_id: str, binding_id: str) -> ResolvedConnection: ...


    def list_project_bindings(self, *, project_hash: str) -> list[ResolvedConnection]: ...

    def load_secrets(self, resolved: ResolvedConnection) -> ConnectionSecrets: ...


# The three readers below accept only real values. A configuration object may be a
# test double whose attributes are fabricated on access; those must read as "unset".


def get_connection_source(*, settings: OAuthDeploymentSettings | None = None) -> ConnectionSource:
    from src.Util.oauth.db_source import DatabaseConnectionSource

    return DatabaseConnectionSource(settings=settings or load_oauth_settings())


__all__ = [
    "ConnectionSource",
    "OAuthConnectionUnavailable",
    "ProjectBinding",
    "ResolvedConnection",
    "UNAVAILABLE_DISABLED",
    "UNAVAILABLE_NOT_CONFIGURED",
    "get_connection_source",
]
