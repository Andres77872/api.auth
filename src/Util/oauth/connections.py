"""Connection and project-binding resolution.

Two sources behind one interface, selected by ``OAUTH_CONFIG_SOURCE``:

* ``env`` (default): one Google connection built from the historical
  ``GOOGLE_OAUTH_*`` variables with a wildcard binding. Behaviour-preserving.
* ``db``: connections, bindings and allow-lists from the database
  (:mod:`src.Util.oauth.db_source`).

The effective enabled state is an AND across four layers: global kill switch,
provider catalog, connection, project binding.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from src.Util.auth_constants import (
    OAUTH_EXISTING_USER_DENY,
    OAUTH_INIT_MODE_API,
    OAUTH_INIT_MODE_LEGACY_REDEEM,
    OAUTH_PROVISIONING_AUTO_CREATE,
    OAUTH_PROVISIONING_BOTH,
    OAUTH_PROVISIONING_DISABLED,
    OAUTH_PROVISIONING_LINK_ONLY,
)
from src.Util.oauth.provider import ConnectionConfig, ConnectionSecrets, OAuthProviderAdapter
from src.Util.oauth.settings import OAuthDeploymentSettings, load_oauth_settings


ENV_CONNECTION_ID = "env:google"
ENV_BINDING_ID = "env:google"
DEFAULT_CONNECTION_KEY = "google"

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
    init_mode: str = OAUTH_INIT_MODE_API
    delivery_mode: str = "bff"
    redirect_uris: tuple[str, ...] = ()
    return_origins: tuple[str, ...] = ()
    state_ttl_seconds: int | None = None
    # True only for the environment-sourced wildcard binding: there the project and
    # the provisioning group are whatever the companion backend asserted. Database
    # bindings never trust caller-asserted scope (docs/agnostic_oauth F-26, F-27).
    trusts_caller_scope: bool = False

    @property
    def can_auto_create(self) -> bool:
        return self.provisioning_mode in {OAUTH_PROVISIONING_AUTO_CREATE, OAUTH_PROVISIONING_BOTH}

    @property
    def can_link(self) -> bool:
        return self.link_enabled and self.provisioning_mode in {OAUTH_PROVISIONING_LINK_ONLY, OAUTH_PROVISIONING_BOTH}

    @property
    def uses_legacy_redeem(self) -> bool:
        return self.init_mode == OAUTH_INIT_MODE_LEGACY_REDEEM

    def is_redirect_uri_allowed(self, redirect_uri: str | None) -> bool:
        return bool(redirect_uri) and str(redirect_uri) in self.redirect_uris

    def is_return_origin_allowed(self, return_origin: str | None) -> bool:
        return bool(return_origin) and str(return_origin) in self.return_origins

    def sole_redirect_uri(self) -> str | None:
        """The redirect URI when exactly one is configured; never "the first of many"."""

        return self.redirect_uris[0] if len(self.redirect_uris) == 1 else None


@dataclass(frozen=True)
class LegacyRedeemConfig:
    url: str = field(repr=False)
    token: str = field(repr=False)
    # Origins the redeemed binding may name. Empty means "the binding's return origins".
    return_origins: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResolvedConnection:
    config: ConnectionConfig
    binding: ProjectBinding
    adapter: OAuthProviderAdapter
    source_name: str


class ConnectionSource(Protocol):
    name: str

    def get_binding(self, *, project_hash: str | None, connection_key: str) -> ResolvedConnection: ...

    def get_by_ids(self, *, connection_id: str, binding_id: str) -> ResolvedConnection: ...

    def find_legacy_bindings(self, *, connection_key: str) -> list[ResolvedConnection]: ...

    def list_project_bindings(self, *, project_hash: str) -> list[ResolvedConnection]: ...

    def load_secrets(self, resolved: ResolvedConnection) -> ConnectionSecrets: ...

    def load_legacy_redeem(self, resolved: ResolvedConnection) -> LegacyRedeemConfig | None: ...


class EnvironmentConnectionSource:
    """The historical single Google connection, read from ``GOOGLE_OAUTH_*``."""

    name = "env"

    def __init__(self, *, settings: OAuthDeploymentSettings | None = None, config_loader=None) -> None:
        self._settings = settings
        self._config_loader = config_loader

    def _load(self):
        if self._config_loader is not None:
            return self._config_loader()
        from src.Util.google_oauth_config import load_google_oauth_config

        return load_google_oauth_config()

    def _resolve(self) -> ResolvedConnection:
        from src.Util.oauth.adapters.google import GOOGLE_NAMESPACE
        from src.Util.oauth.registry import get_adapter, is_registered, register_default_adapters

        if not is_registered("google"):
            register_default_adapters()
        config = self._load()
        if not getattr(config, "enabled", False):
            raise OAuthConnectionUnavailable(UNAVAILABLE_DISABLED, "google_oauth_disabled")
        # Enabled but without a client id: fail fast instead of sending the user to the
        # provider with an empty client and failing at the callback.
        if not _text(config, "client_id"):
            raise OAuthConnectionUnavailable(UNAVAILABLE_NOT_CONFIGURED, "google_oauth_client_id_missing")

        hosted = _values(config, "allowed_hosted_domains")
        connection = ConnectionConfig(
            connection_id=ENV_CONNECTION_ID,
            provider_type="google",
            client_id=_text(config, "client_id") or "",
            scopes=_text(config, "scopes") or "openid email",
            identity_namespace=GOOGLE_NAMESPACE,
            display_name="Google",
            issuers=_values(config, "issuers"),
            discovery_url=_text(config, "discovery_url"),
            authorize_endpoint=_text(config, "authorize_endpoint"),
            token_endpoint=_text(config, "token_endpoint"),
            jwks_uri=_text(config, "jwks_uri"),
            restrictions={"hosted_domains": list(hosted)} if hosted else {},
            leeway_seconds=_int(config, "leeway_seconds", 30),
            jwks_cache_ttl_seconds=_int(config, "jwks_cache_ttl_seconds", 3600),
        )
        binding = ProjectBinding(
            binding_id=ENV_BINDING_ID,
            connection_key=DEFAULT_CONNECTION_KEY,
            enabled=True,
            provisioning_mode=(_text(config, "provisioning_mode") or OAUTH_PROVISIONING_DISABLED).lower(),
            init_mode=OAUTH_INIT_MODE_LEGACY_REDEEM,
            redirect_uris=_values(config, "redirect_uris"),
            return_origins=_values(config, "return_origins"),
            state_ttl_seconds=_int(config, "state_ttl_seconds", 0) or None,
            trusts_caller_scope=True,
        )
        return ResolvedConnection(config=connection, binding=binding, adapter=get_adapter("google"), source_name=self.name)

    def get_binding(self, *, project_hash: str | None, connection_key: str) -> ResolvedConnection:
        if connection_key != DEFAULT_CONNECTION_KEY:
            raise OAuthConnectionUnavailable(UNAVAILABLE_NOT_CONFIGURED, "unknown_connection_key")
        return self._resolve()

    def get_by_ids(self, *, connection_id: str, binding_id: str) -> ResolvedConnection:
        if connection_id != ENV_CONNECTION_ID or binding_id != ENV_BINDING_ID:
            raise OAuthConnectionUnavailable(UNAVAILABLE_NOT_CONFIGURED, "unknown_connection")
        return self._resolve()

    def find_legacy_bindings(self, *, connection_key: str) -> list[ResolvedConnection]:
        return [self.get_binding(project_hash=None, connection_key=connection_key)]

    def list_project_bindings(self, *, project_hash: str) -> list[ResolvedConnection]:
        try:
            return [self._resolve()]
        except OAuthConnectionUnavailable:
            return []

    def load_secrets(self, resolved: ResolvedConnection) -> ConnectionSecrets:
        return ConnectionSecrets(client_secret=_text(self._load(), "client_secret"))

    def load_legacy_redeem(self, resolved: ResolvedConnection) -> LegacyRedeemConfig | None:
        config = self._load()
        url = _text(config, "provider_init_redeem_url")
        token = _text(config, "provider_init_redeem_token")
        if not url or not token:
            return None
        return LegacyRedeemConfig(url=url, token=token, return_origins=_values(config, "provider_init_return_origins"))


# The three readers below accept only real values. A configuration object may be a
# test double whose attributes are fabricated on access; those must read as "unset".
def _values(config, attribute: str) -> tuple[str, ...]:
    raw = getattr(config, attribute, ())
    if isinstance(raw, str):
        raw = raw.split(",")
    if not isinstance(raw, (list, tuple, set, frozenset)):
        return ()
    return tuple(str(item).strip() for item in raw if isinstance(item, str) and item.strip())


def _text(config, attribute: str) -> str | None:
    raw = getattr(config, attribute, None)
    return raw.strip() if isinstance(raw, str) and raw.strip() else None


def _int(config, attribute: str, default: int) -> int:
    raw = getattr(config, attribute, None)
    if isinstance(raw, bool) or not isinstance(raw, int):
        return default
    return raw


def get_connection_source(*, settings: OAuthDeploymentSettings | None = None) -> ConnectionSource:
    settings = settings or load_oauth_settings()
    if settings.uses_database:
        from src.Util.oauth.db_source import DatabaseConnectionSource

        return DatabaseConnectionSource(settings=settings)
    return EnvironmentConnectionSource(settings=settings)


__all__ = [
    "ConnectionSource",
    "DEFAULT_CONNECTION_KEY",
    "ENV_BINDING_ID",
    "ENV_CONNECTION_ID",
    "EnvironmentConnectionSource",
    "LegacyRedeemConfig",
    "OAuthConnectionUnavailable",
    "ProjectBinding",
    "ResolvedConnection",
    "UNAVAILABLE_DISABLED",
    "UNAVAILABLE_NOT_CONFIGURED",
    "get_connection_source",
]
