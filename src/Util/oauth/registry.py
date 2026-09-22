"""Provider adapter registry.

Registration is explicit (``register_default_adapters`` is called once at
application start-up), not an import-time side effect or entry-point discovery.
A provider type is usable only when it is BOTH registered here AND enabled in the
``oauth_provider_catalog`` table: this registry is the capability, the catalog is
the run-time kill switch.
"""

from __future__ import annotations

import threading

from src.Util.oauth.provider import OAuthProviderAdapter, OAuthProviderUnknown


_REGISTRY: dict[str, OAuthProviderAdapter] = {}
_LOCK = threading.Lock()


def register(adapter: OAuthProviderAdapter, *, replace: bool = False) -> None:
    provider_type = str(getattr(adapter, "provider_type", "") or "").strip().lower()
    if not provider_type:
        raise ValueError("adapter.provider_type is required")
    with _LOCK:
        if provider_type in _REGISTRY and not replace:
            raise ValueError(f"an adapter is already registered for provider type '{provider_type}'")
        _REGISTRY[provider_type] = adapter


def unregister(provider_type: str) -> None:
    with _LOCK:
        _REGISTRY.pop(str(provider_type).strip().lower(), None)


def get_adapter(provider_type: str) -> OAuthProviderAdapter:
    adapter = _REGISTRY.get(str(provider_type or "").strip().lower())
    if adapter is None:
        raise OAuthProviderUnknown(f"no adapter registered for provider type '{provider_type}'")
    return adapter


def is_registered(provider_type: str) -> bool:
    return str(provider_type or "").strip().lower() in _REGISTRY


def registered_provider_types() -> tuple[str, ...]:
    return tuple(sorted(_REGISTRY))


def register_default_adapters() -> None:
    """Register the built-in adapters. Idempotent."""

    from src.Util.oauth.adapters.discord import DiscordAdapter
    from src.Util.oauth.adapters.github import GitHubAdapter
    from src.Util.oauth.adapters.google import GoogleAdapter
    from src.Util.oauth.adapters.microsoft import MicrosoftAdapter
    from src.Util.oauth.adapters.oidc import GenericOIDCAdapter

    for adapter in (GoogleAdapter(), GitHubAdapter(), DiscordAdapter(), MicrosoftAdapter(), GenericOIDCAdapter()):
        if not is_registered(adapter.provider_type):
            register(adapter)


__all__ = [
    "get_adapter",
    "is_registered",
    "register",
    "register_default_adapters",
    "registered_provider_types",
    "unregister",
]
