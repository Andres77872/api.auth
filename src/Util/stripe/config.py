"""Stripe billing adapter configuration and fail-closed readiness.

Trace: `.dev/sdd/changes/provider-agnostic-billing-stripe/tasks.md` task 6.2.

The module parses configuration only when explicitly called. Importing it never
creates a Stripe client, contacts Stripe, or logs secret values.
"""

from __future__ import annotations

import importlib.metadata
import os
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from src.Util import auth_constants as constants
from src.Util.billing.provider import ProviderReadiness


SUPPORTED_STRIPE_SDK_VERSION = constants.SUPPORTED_STRIPE_SDK_VERSION
SUPPORTED_STRIPE_API_VERSION = constants.SUPPORTED_STRIPE_API_VERSION
DEFAULT_STRIPE_WEBHOOK_SIGNATURE_TOLERANCE_SECONDS = 300
STRIPE_WEBHOOK_SIGNATURE_TOLERANCE_SECONDS_ENV = "STRIPE_WEBHOOK_SIGNATURE_TOLERANCE_SECONDS"


class StripeConfigError(RuntimeError):
    """Raised for malformed Stripe billing configuration."""


@dataclass(frozen=True)
class StripeConfig:
    """Parsed Stripe adapter configuration.

    Secret-bearing fields use ``repr=False``. Readiness results expose only
    missing variable names and mismatch labels, never values.
    """

    billing_enabled: bool = False
    stripe_billing_enabled: bool = False
    webhooks_enabled: bool = False
    checkout_enabled: bool = False
    portal_enabled: bool = False
    sync_enabled: bool = False
    secret_key: str | None = field(default=None, repr=False)
    webhook_secret: str | None = field(default=None, repr=False)
    api_version: str = SUPPORTED_STRIPE_API_VERSION
    portal_configuration_id: str | None = field(default=None, repr=False)
    allowed_webhook_events: tuple[str, ...] = constants.DEFAULT_STRIPE_ALLOWED_WEBHOOK_EVENTS
    webhook_signature_tolerance_seconds: int = DEFAULT_STRIPE_WEBHOOK_SIGNATURE_TOLERANCE_SECONDS
    installed_sdk_version: str | None = None

    @property
    def disabled(self) -> bool:
        return not any(self.primary_feature_flags.values())

    @property
    def primary_feature_flags(self) -> dict[str, bool]:
        return {
            "billing": self.billing_enabled,
            "stripe_billing": self.stripe_billing_enabled,
            "webhooks": self.webhooks_enabled,
            "checkout": self.checkout_enabled,
            "portal": self.portal_enabled,
            "sync": self.sync_enabled,
        }

    def is_feature_enabled(self, feature: str) -> bool:
        normalized = str(feature or "").strip().lower()
        if normalized not in self.primary_feature_flags:
            raise StripeConfigError(f"unknown Stripe feature flag: {normalized or '<empty>'}")
        return self.primary_feature_flags[normalized]

    def is_webhook_event_allowed(self, event_type: str) -> bool:
        return str(event_type or "").strip() in self.allowed_webhook_events


@dataclass(frozen=True)
class StripeReadiness:
    provider: str = constants.STRIPE_PROVIDER_NAME
    ready: bool = False
    status: str = "disabled"
    enabled: bool = False
    missing: tuple[str, ...] = ()
    degraded: tuple[str, ...] = ()
    critical_mismatches: tuple[str, ...] = ()
    sdk_version: str | None = None
    api_version: str | None = None
    capabilities: Mapping[str, bool] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "ready": self.ready,
            "status": self.status,
            "enabled": self.enabled,
            "missing": list(self.missing),
            "degraded": list(self.degraded),
            "critical_mismatches": list(self.critical_mismatches),
            "sdk_version": self.sdk_version,
            "api_version": self.api_version,
            "capabilities": dict(self.capabilities),
        }


def _env(env: Mapping[str, str] | None = None) -> Mapping[str, str]:
    return env if env is not None else os.environ


def _get(env: Mapping[str, str], key: str, default: str = "") -> str:
    value = env.get(key, default)
    return "" if value is None else str(value).strip()


def _bool(value: str | bool | None, *, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _int(env: Mapping[str, str], key: str, default: int) -> int:
    raw = _get(env, key, str(default))
    try:
        return int(raw)
    except ValueError as exc:
        raise StripeConfigError(f"{key} must be an integer") from exc


def _positive_int(env: Mapping[str, str], key: str, default: int) -> int:
    value = _int(env, key, default)
    if value < 1:
        raise StripeConfigError(f"{key} must be positive")
    return value


def _csv_tuple(raw: str | Sequence[str] | None) -> tuple[str, ...]:
    if raw is None:
        items: Sequence[str] = ()
    elif isinstance(raw, str):
        items = raw.split(",")
    else:
        items = raw
    values: list[str] = []
    seen: set[str] = set()
    for item in items:
        normalized = str(item or "").strip()
        if normalized and normalized not in seen:
            values.append(normalized)
            seen.add(normalized)
    return tuple(values)


def get_installed_stripe_sdk_version() -> str | None:
    """Return installed stripe package version, or None when unavailable."""

    try:
        return importlib.metadata.version("stripe")
    except importlib.metadata.PackageNotFoundError:
        return None


def validate_allowed_webhook_events(
    allowed_events: Sequence[str] | str | None,
    *,
    approved_events: Sequence[str] = constants.STRIPE_MVP_ALLOWED_WEBHOOK_EVENTS,
) -> tuple[str, ...]:
    """Return a deduped allow-list that cannot widen beyond the MVP contract."""

    configured = _csv_tuple(allowed_events)
    if not configured:
        configured = tuple(approved_events)
    approved = set(approved_events)
    unsupported = [event for event in configured if event not in approved]
    if unsupported:
        raise StripeConfigError("STRIPE_ALLOWED_WEBHOOK_EVENTS may not widen the approved MVP allow-list")
    return configured


def load_stripe_config(*, env: Mapping[str, str] | None = None) -> StripeConfig:
    values = _env(env)
    allowed_events = validate_allowed_webhook_events(
        _get(
            values,
            constants.STRIPE_ALLOWED_WEBHOOK_EVENTS_ENV,
            constants.DEFAULT_STRIPE_ALLOWED_WEBHOOK_EVENTS_CSV,
        )
    )
    return StripeConfig(
        billing_enabled=_bool(_get(values, constants.BILLING_ENABLED_ENV), default=False),
        stripe_billing_enabled=_bool(_get(values, constants.STRIPE_BILLING_ENABLED_ENV), default=False),
        webhooks_enabled=_bool(_get(values, constants.STRIPE_WEBHOOKS_ENABLED_ENV), default=False),
        checkout_enabled=_bool(_get(values, constants.STRIPE_CHECKOUT_ENABLED_ENV), default=False),
        portal_enabled=_bool(_get(values, constants.STRIPE_PORTAL_ENABLED_ENV), default=False),
        sync_enabled=_bool(_get(values, constants.STRIPE_SYNC_ENABLED_ENV), default=False),
        secret_key=_get(values, constants.STRIPE_SECRET_KEY_ENV) or None,
        webhook_secret=_get(values, constants.STRIPE_WEBHOOK_SECRET_ENV) or None,
        api_version=_get(values, constants.STRIPE_API_VERSION_ENV, SUPPORTED_STRIPE_API_VERSION)
        or SUPPORTED_STRIPE_API_VERSION,
        portal_configuration_id=_get(values, constants.STRIPE_PORTAL_CONFIGURATION_ID_ENV) or None,
        allowed_webhook_events=allowed_events,
        webhook_signature_tolerance_seconds=_positive_int(
            values,
            STRIPE_WEBHOOK_SIGNATURE_TOLERANCE_SECONDS_ENV,
            DEFAULT_STRIPE_WEBHOOK_SIGNATURE_TOLERANCE_SECONDS,
        ),
        installed_sdk_version=get_installed_stripe_sdk_version(),
    )


def _readiness_config_from_kwargs(
    *,
    installed_sdk_version: str | None = None,
    configured_api_version: str | None = None,
    stripe_enabled: bool | None = None,
    webhooks_enabled: bool | None = None,
    checkout_enabled: bool | None = None,
    portal_enabled: bool | None = None,
    sync_enabled: bool | None = None,
    secret_key: str | None = None,
    webhook_secret: str | None = None,
    portal_configuration_id: str | None = None,
    allowed_webhook_events: Sequence[str] | str | None = None,
) -> StripeConfig:
    return StripeConfig(
        billing_enabled=bool(stripe_enabled),
        stripe_billing_enabled=bool(stripe_enabled),
        webhooks_enabled=bool(webhooks_enabled if webhooks_enabled is not None else stripe_enabled),
        checkout_enabled=bool(checkout_enabled if checkout_enabled is not None else stripe_enabled),
        portal_enabled=bool(portal_enabled if portal_enabled is not None else False),
        sync_enabled=bool(sync_enabled if sync_enabled is not None else False),
        secret_key=secret_key,
        webhook_secret=webhook_secret,
        api_version=configured_api_version or SUPPORTED_STRIPE_API_VERSION,
        portal_configuration_id=portal_configuration_id,
        allowed_webhook_events=validate_allowed_webhook_events(allowed_webhook_events),
        installed_sdk_version=installed_sdk_version,
    )


def validate_stripe_runtime_readiness(
    config: StripeConfig | None = None,
    *,
    installed_sdk_version: str | None = None,
    configured_api_version: str | None = None,
    stripe_enabled: bool | None = None,
    webhooks_enabled: bool | None = None,
    checkout_enabled: bool | None = None,
    portal_enabled: bool | None = None,
    sync_enabled: bool | None = None,
    secret_key: str | None = None,
    webhook_secret: str | None = None,
    portal_configuration_id: str | None = None,
    portal_configuration_verified: bool | None = None,
    allowed_webhook_events: Sequence[str] | str | None = None,
) -> StripeReadiness:
    """Return fail-closed Stripe readiness with non-secret diagnostics.

    Callers may pass a parsed ``StripeConfig`` or explicit keyword values. Tests
    use the keyword seam to prove SDK/API mismatches fail closed.
    """

    cfg = config or _readiness_config_from_kwargs(
        installed_sdk_version=installed_sdk_version,
        configured_api_version=configured_api_version,
        stripe_enabled=stripe_enabled,
        webhooks_enabled=webhooks_enabled,
        checkout_enabled=checkout_enabled,
        portal_enabled=portal_enabled,
        sync_enabled=sync_enabled,
        secret_key=secret_key,
        webhook_secret=webhook_secret,
        portal_configuration_id=portal_configuration_id,
        allowed_webhook_events=allowed_webhook_events,
    )

    enabled = bool(cfg.billing_enabled or cfg.stripe_billing_enabled or cfg.webhooks_enabled or cfg.checkout_enabled or cfg.portal_enabled or cfg.sync_enabled)
    if not enabled:
        return StripeReadiness(
            ready=False,
            status="disabled",
            enabled=False,
            sdk_version=cfg.installed_sdk_version or installed_sdk_version,
            api_version=cfg.api_version,
            capabilities=_capabilities(cfg, portal_configuration_verified=portal_configuration_verified),
        )

    missing: list[str] = []
    mismatches: list[str] = []
    degraded: list[str] = []
    sdk_version = installed_sdk_version if installed_sdk_version is not None else cfg.installed_sdk_version
    api_version = configured_api_version or cfg.api_version

    if sdk_version != SUPPORTED_STRIPE_SDK_VERSION:
        mismatches.append(constants.STRIPE_SECRET_KEY_ENV.replace("SECRET_KEY", "SDK_VERSION"))
    if api_version != SUPPORTED_STRIPE_API_VERSION:
        mismatches.append(constants.STRIPE_API_VERSION_ENV)

    # Per-group Stripe accounts own the real secret key, webhook secret, and portal configuration
    # (set + encrypted per billing group; resolved via get_stripe_client_for_group). The global env
    # STRIPE_SECRET_KEY / STRIPE_WEBHOOK_SECRET / STRIPE_PORTAL_CONFIGURATION_ID are OPTIONAL,
    # single-account/migration-only values and no longer gate readiness — operational readiness is
    # reported per group via the admin/health rollup (system_metrics + /admin/billing/metrics). The
    # global feature flags below act purely as kill switches; SDK/API version pins stay fail-closed.
    if cfg.webhooks_enabled:
        try:
            validate_allowed_webhook_events(cfg.allowed_webhook_events)
        except StripeConfigError:
            degraded.append(constants.STRIPE_ALLOWED_WEBHOOK_EVENTS_ENV)
    if cfg.portal_enabled and cfg.portal_configuration_id:
        # Only verify the optional global/migration portal config when the operator actually set it;
        # per-group portal-config readiness is surfaced via the per-group rollup.
        if portal_configuration_verified is False:
            mismatches.append("STRIPE_PORTAL_CONFIGURATION_RESTRICTED")
        elif portal_configuration_verified is None:
            degraded.append("portal_configuration_unverified")

    status = "ready"
    ready = True
    if missing or mismatches:
        status = "not_ready"
        ready = False
    elif degraded:
        status = "degraded"
        ready = False

    return StripeReadiness(
        ready=ready,
        status=status,
        enabled=True,
        missing=tuple(dict.fromkeys(missing)),
        degraded=tuple(dict.fromkeys(degraded)),
        critical_mismatches=tuple(dict.fromkeys(mismatches)),
        sdk_version=sdk_version,
        api_version=api_version,
        capabilities=_capabilities(cfg, portal_configuration_verified=portal_configuration_verified),
    )


def _capabilities(cfg: StripeConfig, *, portal_configuration_verified: bool | None = None) -> dict[str, bool]:
    return {
        "webhooks": bool(cfg.webhooks_enabled),
        "checkout": bool(cfg.checkout_enabled),
        "portal": bool(cfg.portal_enabled and portal_configuration_verified is True),
        "sync": bool(cfg.sync_enabled),
    }


def stripe_runtime_readiness(**kwargs: Any) -> StripeReadiness:
    return validate_stripe_runtime_readiness(**kwargs)


def provider_readiness_from_stripe_config(config: StripeConfig) -> ProviderReadiness:
    readiness = validate_stripe_runtime_readiness(config)
    return ProviderReadiness(
        provider=constants.STRIPE_PROVIDER_NAME,
        ready=readiness.ready,
        status=readiness.status,
        missing=tuple(readiness.missing),
        degraded=tuple([*readiness.degraded, *readiness.critical_mismatches]),
        capabilities=readiness.capabilities,
    )


__all__ = [
    "DEFAULT_STRIPE_WEBHOOK_SIGNATURE_TOLERANCE_SECONDS",
    "STRIPE_WEBHOOK_SIGNATURE_TOLERANCE_SECONDS_ENV",
    "SUPPORTED_STRIPE_API_VERSION",
    "SUPPORTED_STRIPE_SDK_VERSION",
    "StripeConfig",
    "StripeConfigError",
    "StripeReadiness",
    "get_installed_stripe_sdk_version",
    "load_stripe_config",
    "provider_readiness_from_stripe_config",
    "stripe_runtime_readiness",
    "validate_allowed_webhook_events",
    "validate_stripe_runtime_readiness",
]
