"""Database-backed connection source (``OAUTH_CONFIG_SOURCE=db``).

Resolution is an AND across four layers -- global kill switch (checked by the
routes), provider catalog, connection, project binding -- plus the project itself.
Non-secret rows are cached in-process for a short TTL and invalidated on admin
writes; with several instances the TTL bounds staleness, and the callback
re-resolves after consuming state, so a disabled connection stays disabled.

Secrets are decrypted per call, never cached.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Mapping

from src.Util.auth_constants import OAUTH_INIT_MODE_LEGACY_REDEEM
from src.Util.oauth.connections import (
    LegacyRedeemConfig,
    OAuthConnectionUnavailable,
    ProjectBinding,
    ResolvedConnection,
    UNAVAILABLE_DISABLED,
    UNAVAILABLE_NOT_CONFIGURED,
)
from src.Util.oauth.provider import ConnectionConfig, ConnectionSecrets
from src.Util.oauth.registry import get_adapter, is_registered, register_default_adapters
from src.Util.oauth.secrets import (
    KIND_CLIENT_SECRET,
    KIND_LEGACY_REDEEM_TOKEN,
    KIND_LEGACY_REDEEM_URL,
    KIND_SIGNING_KEY,
    OAuthSecretError,
    decrypt_secret,
)
from src.Util.oauth.settings import OAuthDeploymentSettings, load_oauth_settings


CACHE_TTL_SECONDS = 30.0
_USABLE_CATALOG_STATUSES = {"enabled", "degraded"}

_cache: dict[tuple[str, ...], tuple[float, Mapping[str, Any] | None]] = {}
_cache_lock = threading.Lock()


def invalidate_connection_cache() -> None:
    """Drop every cached row. Called by the admin API after any write."""

    with _cache_lock:
        _cache.clear()


def _cached(key: tuple[str, ...], loader):
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(key)
        if hit is not None and now < hit[0]:
            return hit[1]
    row = loader()
    with _cache_lock:
        _cache[key] = (now + CACHE_TTL_SECONDS, row)
    return row


def _list(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(item) for item in value if isinstance(item, str) and item)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def evaluate_binding_row(row: Mapping[str, Any]) -> list[str]:
    """Return the failing layers for a resolved binding row, most fundamental first.

    Shared by request-time resolution and the admin readiness endpoint so both always
    agree on why a provider is unavailable.
    """

    failures: list[str] = []
    provider_type = str(row.get("provider_type") or "")
    if str(row.get("catalog_status") or "") not in _USABLE_CATALOG_STATUSES:
        failures.append("provider_type_disabled")
    if not is_registered(provider_type):
        register_default_adapters()
    if not is_registered(provider_type):
        failures.append("adapter_not_registered")
    if str(row.get("connection_status") or "") != "active":
        failures.append("connection_not_active")
    if str(row.get("credential_status") or "") != "active":
        failures.append("credentials_not_active")
    if not row.get("enabled"):
        failures.append("binding_disabled")
    if not row.get("project_is_active", True) or row.get("project_archived"):
        failures.append("project_inactive")
    if not _list(row.get("redirect_uris")):
        failures.append("no_redirect_uri")
    if not _list(row.get("return_origins")):
        failures.append("no_return_origin")
    if str(row.get("provisioning_mode") or "") in {"auto_create", "both"}:
        if not row.get("default_user_group_id") or not row.get("default_user_group_is_active"):
            failures.append("default_group_missing")
        elif not row.get("default_user_group_reaches_project"):
            failures.append("default_group_does_not_reach_project")
    return failures


_DISABLED_FAILURES = {"provider_type_disabled", "binding_disabled", "project_inactive"}
# Missing URLs or a broken default group make a binding unusable for some flows but must
# not mask the more precise error the pipeline reports for them.
_NON_BLOCKING_FAILURES = {
    "no_redirect_uri", "no_return_origin", "default_group_missing", "default_group_does_not_reach_project",
}


class DatabaseConnectionSource:
    name = "db"

    def __init__(self, *, settings: OAuthDeploymentSettings | None = None, db_module: Any | None = None) -> None:
        self._settings = settings or load_oauth_settings()
        self._db = db_module

    @property
    def _oauth_db(self):
        if self._db is not None:
            return self._db
        from src.Util.db import db_oauth_connections

        return db_oauth_connections

    # ------------------------------------------------------------------ building
    def _build(self, row: Mapping[str, Any] | None, *, enforce: bool = True) -> ResolvedConnection:
        if not row:
            raise OAuthConnectionUnavailable(UNAVAILABLE_NOT_CONFIGURED, "binding_not_found")
        if enforce:
            blocking = [item for item in evaluate_binding_row(row) if item not in _NON_BLOCKING_FAILURES]
            if blocking:
                kind = UNAVAILABLE_DISABLED if blocking[0] in _DISABLED_FAILURES else UNAVAILABLE_NOT_CONFIGURED
                raise OAuthConnectionUnavailable(kind, blocking[0])

        provider_type = str(row.get("provider_type") or "")
        issuer = str(row.get("issuer") or "").strip()
        config = ConnectionConfig(
            connection_id=str(row["connection_id"]),
            provider_type=provider_type,
            client_id=str(row.get("client_id") or ""),
            scopes=str(row.get("scopes") or ""),
            identity_namespace=str(row.get("identity_namespace") or ""),
            display_name=str(row.get("display_name") or ""),
            issuers=(issuer,) if issuer else (),
            discovery_url=row.get("discovery_url") or None,
            authorize_endpoint=row.get("authorize_endpoint") or None,
            token_endpoint=row.get("token_endpoint") or None,
            jwks_uri=row.get("jwks_uri") or None,
            userinfo_endpoint=row.get("userinfo_endpoint") or None,
            restrictions=_mapping(row.get("restrictions")),
            provider_params=_mapping(row.get("provider_params")),
            leeway_seconds=self._settings.leeway_seconds,
            jwks_cache_ttl_seconds=self._settings.jwks_cache_ttl_seconds,
        )
        ttl = row.get("state_ttl_seconds")
        binding = ProjectBinding(
            binding_id=str(row["binding_id"]),
            connection_key=str(row.get("connection_key") or ""),
            project_id=str(row.get("project_id") or "") or None,
            project_hash=str(row.get("project_hash") or "") or None,
            enabled=bool(row.get("enabled")),
            login_enabled=bool(row.get("login_enabled")) and bool(row.get("catalog_login_enabled")),
            link_enabled=bool(row.get("link_enabled")) and bool(row.get("catalog_link_enabled")),
            provisioning_mode=str(row.get("provisioning_mode") or "disabled"),
            default_user_group_id=(
                str(row["default_user_group_id"])
                if row.get("default_user_group_id")
                and row.get("default_user_group_is_active")
                and row.get("default_user_group_reaches_project")
                else None
            ),
            default_user_group_hash=str(row.get("default_user_group_hash") or "") or None,
            existing_user_policy=str(row.get("existing_user_policy") or "deny"),
            init_mode=str(row.get("init_mode") or "api"),
            delivery_mode=str(row.get("delivery_mode") or "bff"),
            redirect_uris=_list(row.get("redirect_uris")),
            return_origins=_list(row.get("return_origins")),
            state_ttl_seconds=int(ttl) if isinstance(ttl, int) and ttl > 0 else None,
            trusts_caller_scope=False,
        )
        adapter = get_adapter(provider_type) if is_registered(provider_type) else None
        return ResolvedConnection(config=config, binding=binding, adapter=adapter, source_name=self.name)  # type: ignore[arg-type]

    # -------------------------------------------------------------------- lookup
    def get_binding(self, *, project_hash: str | None, connection_key: str) -> ResolvedConnection:
        if not project_hash:
            raise OAuthConnectionUnavailable(UNAVAILABLE_NOT_CONFIGURED, "project_required")
        row = _cached(
            ("binding", project_hash, connection_key),
            lambda: self._oauth_db.get_binding(project_hash=project_hash, connection_key=connection_key),
        )
        return self._build(row)

    def get_by_ids(self, *, connection_id: str, binding_id: str) -> ResolvedConnection:
        row = _cached(
            ("ids", connection_id, binding_id),
            lambda: self._oauth_db.get_binding_by_ids(connection_id=connection_id, binding_id=binding_id),
        )
        return self._build(row)

    def find_legacy_bindings(self, *, connection_key: str) -> list[ResolvedConnection]:
        resolved: list[ResolvedConnection] = []
        for row in self._oauth_db.list_legacy_bindings(connection_key=connection_key):
            try:
                resolved.append(self._build(row))
            except OAuthConnectionUnavailable:
                continue
        if not resolved:
            raise OAuthConnectionUnavailable(UNAVAILABLE_DISABLED, "no_legacy_binding")
        return resolved

    def list_project_bindings(self, *, project_hash: str) -> list[ResolvedConnection]:
        resolved: list[ResolvedConnection] = []
        for row in self._oauth_db.list_bindings_for_project(project_hash=project_hash):
            try:
                resolved.append(self._build(row))
            except OAuthConnectionUnavailable:
                continue
        return resolved

    # ------------------------------------------------------------------- secrets
    def load_secrets(self, resolved: ResolvedConnection) -> ConnectionSecrets:
        connection_id = resolved.config.connection_id
        row = self._oauth_db.get_connection_operational_credentials(id=connection_id)
        if not row or str(row.get("credential_status") or "") != "active":
            raise OAuthConnectionUnavailable(UNAVAILABLE_NOT_CONFIGURED, "credentials_not_active")
        key_id = row.get("credential_key_id")
        try:
            client_secret = (
                decrypt_secret(
                    owner_id=connection_id,
                    kind=KIND_CLIENT_SECRET,
                    ciphertext=row.get("client_secret_ciphertext"),
                    key_id=key_id,
                    expected_digest=row.get("client_secret_hmac"),
                    settings=self._settings,
                )
                if row.get("client_secret_ciphertext") is not None
                else None
            )
            signing_key = (
                decrypt_secret(
                    owner_id=connection_id,
                    kind=KIND_SIGNING_KEY,
                    ciphertext=row.get("signing_key_ciphertext"),
                    key_id=key_id,
                    expected_digest=row.get("signing_key_hmac"),
                    settings=self._settings,
                )
                if row.get("signing_key_ciphertext") is not None
                else None
            )
        except OAuthSecretError as exc:
            raise OAuthConnectionUnavailable(UNAVAILABLE_NOT_CONFIGURED, "credentials_undecryptable") from exc
        return ConnectionSecrets(client_secret=client_secret, signing_key=signing_key)

    def load_legacy_redeem(self, resolved: ResolvedConnection) -> LegacyRedeemConfig | None:
        if resolved.binding.init_mode != OAUTH_INIT_MODE_LEGACY_REDEEM:
            return None
        binding_id = resolved.binding.binding_id
        row = self._oauth_db.get_binding_legacy_redeem(binding_id=binding_id)
        if not row or row.get("legacy_redeem_url_ciphertext") is None or row.get("legacy_redeem_token_ciphertext") is None:
            return None
        try:
            url = decrypt_secret(
                owner_id=binding_id, kind=KIND_LEGACY_REDEEM_URL,
                ciphertext=row["legacy_redeem_url_ciphertext"], key_id=row.get("legacy_redeem_key_id"), settings=self._settings,
            )
            token = decrypt_secret(
                owner_id=binding_id, kind=KIND_LEGACY_REDEEM_TOKEN,
                ciphertext=row["legacy_redeem_token_ciphertext"], key_id=row.get("legacy_redeem_key_id"), settings=self._settings,
            )
        except OAuthSecretError:
            return None
        return LegacyRedeemConfig(url=url, token=token)


__all__ = ["CACHE_TTL_SECONDS", "DatabaseConnectionSource", "evaluate_binding_row", "invalidate_connection_cache"]
