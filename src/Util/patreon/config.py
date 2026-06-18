"""Patreon account-link configuration parsing and readiness checks.

This module is intentionally configuration-only.  It never contacts Patreon,
Redis, the database, or any secret manager.  Secrets are read only inside
``load_patreon_config`` and are hidden from dataclass repr output.

Trace: SDD change ``patreon-account-link`` tasks 3.3 and requirements for
disabled-by-default config, multi-campaign tier maps, retention caps,
kill-switches, and non-secret readiness reporting.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.Util import auth_constants as constants


class PatreonConfigError(RuntimeError):
    """Raised when Patreon configuration is malformed or unsafe to enable."""


@dataclass(frozen=True)
class PatreonTierMapEntry:
    """One raw server-only campaign/tier mapping from configuration.

    Raw Patreon IDs are available to server-side classification code, but are
    excluded from repr so operator logs and readiness messages do not leak them
    by accident.
    """

    campaign_id: str = field(repr=False)
    tier_id: str = field(repr=False)
    plan_code: str
    tier_code: str
    tier_name: str | None = None
    priority: int = 0
    active: bool = True
    campaign_name: str | None = None


@dataclass(frozen=True)
class PatreonConfig:
    """Parsed Patreon runtime configuration.

    Secret-bearing fields use ``repr=False``.  Do not log this object with
    ``asdict``; readiness objects expose only names of missing configuration.
    """

    linking_enabled: bool
    webhooks_enabled: bool
    sync_enabled: bool
    s2s_entitlement_enabled: bool
    creator_token_refresh_enabled: bool
    raw_payload_capture_enabled: bool
    api_base_url: str
    oauth_token_url: str
    user_agent: str
    allowed_webhook_events: tuple[str, ...]
    campaign_tier_maps: tuple[PatreonTierMapEntry, ...] = field(repr=False)
    proof_token_ttl_seconds: int = constants.DEFAULT_PATREON_PROOF_TOKEN_TTL_SECONDS
    proof_retention_after_expiry_hours: int = (
        constants.DEFAULT_PATREON_PROOF_RETENTION_AFTER_EXPIRY_HOURS
    )
    webhook_delivery_retention_days: int = constants.DEFAULT_PATREON_WEBHOOK_DELIVERY_RETENTION_DAYS
    raw_payload_retention_days: int = constants.DEFAULT_PATREON_RAW_PAYLOAD_RETENTION_DAYS
    api_timeout_seconds: int = constants.DEFAULT_PATREON_API_TIMEOUT_SECONDS
    api_connect_timeout_seconds: int = constants.DEFAULT_PATREON_API_CONNECT_TIMEOUT_SECONDS
    api_page_size: int = constants.DEFAULT_PATREON_API_PAGE_SIZE
    api_max_pages_per_sync: int = constants.DEFAULT_PATREON_API_MAX_PAGES_PER_SYNC
    api_retry_max_attempts: int = constants.DEFAULT_PATREON_API_RETRY_MAX_ATTEMPTS
    api_retry_backoff_seconds: tuple[int, ...] = constants.DEFAULT_PATREON_API_RETRY_BACKOFF_SECONDS
    api_retry_jitter_seconds: int = constants.DEFAULT_PATREON_API_RETRY_JITTER_SECONDS
    creator_token_refresh_margin_seconds: int = (
        constants.DEFAULT_PATREON_CREATOR_TOKEN_REFRESH_MARGIN_SECONDS
    )
    sync_interval_seconds: int = constants.DEFAULT_PATREON_SYNC_INTERVAL_SECONDS
    sync_jitter_seconds: int = constants.DEFAULT_PATREON_SYNC_JITTER_SECONDS
    sync_stale_after_seconds: int = constants.DEFAULT_PATREON_SYNC_STALE_AFTER_SECONDS
    sync_worker_poll_seconds: int = constants.DEFAULT_PATREON_SYNC_WORKER_POLL_SECONDS
    sync_worker_batch_size: int = constants.DEFAULT_PATREON_SYNC_WORKER_BATCH_SIZE
    sync_job_lease_seconds: int = constants.DEFAULT_PATREON_SYNC_JOB_LEASE_SECONDS
    sync_max_attempts: int = constants.DEFAULT_PATREON_SYNC_MAX_ATTEMPTS
    sync_backoff_seconds: tuple[int, ...] = constants.DEFAULT_PATREON_SYNC_BACKOFF_SECONDS
    webhook_signature_failure_alert_limit: int = (
        constants.DEFAULT_PATREON_WEBHOOK_SIGNATURE_FAILURE_ALERT_LIMIT
    )
    webhook_signature_failure_alert_window_seconds: int = (
        constants.DEFAULT_PATREON_WEBHOOK_SIGNATURE_FAILURE_ALERT_WINDOW_SECONDS
    )
    app_env: str = ""
    explicit_test_runtime: bool = False
    creator_access_token: str | None = field(default=None, repr=False)
    creator_refresh_token: str | None = field(default=None, repr=False)
    client_id: str | None = field(default=None, repr=False)
    client_secret: str | None = field(default=None, repr=False)
    webhook_secret: str | None = field(default=None, repr=False)
    webhook_id: str | None = field(default=None, repr=False)
    s2s_bearer_token: str | None = field(default=None, repr=False)
    provider_sub_pepper: str | None = field(default=None, repr=False)
    email_hash_pepper: str | None = field(default=None, repr=False)
    proof_token_pepper: str | None = field(default=None, repr=False)
    id_hmac_secret: str | None = field(default=None, repr=False)
    webhook_delivery_hash_pepper: str | None = field(default=None, repr=False)
    provider_token_encryption_key: str | None = field(default=None, repr=False)
    provider_token_encryption_key_id: str | None = field(default=None, repr=False)

    @property
    def linking(self) -> bool:
        return self.linking_enabled

    @property
    def webhooks(self) -> bool:
        return self.webhooks_enabled

    @property
    def sync(self) -> bool:
        return self.sync_enabled

    @property
    def s2s_entitlement(self) -> bool:
        return self.s2s_entitlement_enabled

    @property
    def disabled(self) -> bool:
        return not any(self.primary_feature_flags.values())

    @property
    def primary_feature_flags(self) -> dict[str, bool]:
        return {
            "linking": self.linking_enabled,
            "webhooks": self.webhooks_enabled,
            "sync": self.sync_enabled,
            "s2s_entitlement": self.s2s_entitlement_enabled,
        }

    @property
    def kill_switches(self) -> dict[str, bool]:
        return {
            **self.primary_feature_flags,
            "creator_token_refresh": self.creator_token_refresh_enabled,
            "raw_payload_capture": self.raw_payload_capture_enabled,
        }

    @property
    def tier_map_entries(self) -> tuple[PatreonTierMapEntry, ...]:
        return self.campaign_tier_maps

    @property
    def tier_maps(self) -> tuple[PatreonTierMapEntry, ...]:
        return self.campaign_tier_maps

    @property
    def campaign_ids(self) -> tuple[str, ...]:
        seen: set[str] = set()
        ordered: list[str] = []
        for entry in self.campaign_tier_maps:
            if entry.campaign_id not in seen:
                seen.add(entry.campaign_id)
                ordered.append(entry.campaign_id)
        return tuple(ordered)

    def is_feature_enabled(self, feature: str) -> bool:
        normalized = str(feature or "").strip().lower()
        if normalized not in self.kill_switches:
            raise PatreonConfigError(f"unknown Patreon feature kill-switch: {normalized or '<empty>'}")
        return self.kill_switches[normalized]

    def is_webhook_event_allowed(self, event_type: str) -> bool:
        return str(event_type or "").strip() in self.allowed_webhook_events


@dataclass(frozen=True)
class PatreonReadiness:
    """Non-secret readiness result for health/routes/runbooks."""

    ready: bool
    status: str
    missing: list[str] = field(default_factory=list)
    degraded: list[str] = field(default_factory=list)
    provider: str = constants.PATREON_PROVIDER_NAME


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
        raise PatreonConfigError(f"{key} must be an integer") from exc


def _bounded_int(
    env: Mapping[str, str],
    key: str,
    default: int,
    *,
    minimum: int = 0,
    maximum: int,
) -> int:
    value = _int(env, key, default)
    if value < minimum or value > maximum:
        raise PatreonConfigError(f"{key} must be between {minimum} and {maximum}")
    return value


def _int_tuple(env: Mapping[str, str], key: str, default: tuple[int, ...]) -> tuple[int, ...]:
    raw = _get(env, key, ",".join(str(item) for item in default))
    if not raw:
        return default
    try:
        values = tuple(int(part.strip()) for part in raw.split(",") if part.strip())
    except ValueError as exc:
        raise PatreonConfigError(f"{key} must be a comma-separated integer list") from exc
    return values or default


def _csv_tuple(raw: str) -> tuple[str, ...]:
    values: list[str] = []
    seen: set[str] = set()
    for item in str(raw or "").split(","):
        normalized = item.strip()
        if not normalized or normalized in seen:
            continue
        values.append(normalized)
        seen.add(normalized)
    return tuple(values)


def is_explicit_test_runtime(env: Mapping[str, str] | None = None) -> bool:
    values = _env(env)
    runtime = _get(values, constants.APP_ENV_ENV).lower()
    if runtime in constants.TEST_ENV_NAMES:
        return True
    if runtime in constants.NON_TEST_ENV_NAMES:
        return False
    return bool(_get(values, constants.PYTEST_CURRENT_TEST_ENV)) or "pytest" in sys.modules


def _required_text(item: Mapping[str, Any], key: str, *, source: str, index: str) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PatreonConfigError(f"{source} tier-map entry {index} is missing required field {key}")
    return value.strip()


def _optional_text(item: Mapping[str, Any], key: str) -> str | None:
    value = item.get(key)
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _priority(item: Mapping[str, Any], *, source: str, index: str) -> int:
    value = item.get("priority", 0)
    if isinstance(value, bool) or not isinstance(value, int):
        raise PatreonConfigError(f"{source} tier-map entry {index} priority must be an integer")
    return value


def _active(item: Mapping[str, Any], *, source: str, index: str) -> bool:
    value = item.get("active", True)
    if not isinstance(value, bool):
        raise PatreonConfigError(f"{source} tier-map entry {index} active must be a boolean")
    return value


def _iter_raw_entries(parsed: Any, *, source: str) -> Sequence[tuple[str, Mapping[str, Any]]]:
    """Return normalized raw entry mappings from supported config shapes."""

    if isinstance(parsed, dict) and isinstance(parsed.get("campaigns"), list):
        entries: list[tuple[str, Mapping[str, Any]]] = []
        for campaign_index, campaign in enumerate(parsed["campaigns"], start=1):
            if not isinstance(campaign, Mapping):
                raise PatreonConfigError(f"{source} campaigns[{campaign_index}] must be an object")
            campaign_id = _required_text(
                campaign,
                "campaign_id",
                source=source,
                index=f"campaigns[{campaign_index}]",
            )
            campaign_name = _optional_text(campaign, "campaign_name") or _optional_text(campaign, "name")
            tiers = campaign.get("tiers")
            if not isinstance(tiers, list) or not tiers:
                raise PatreonConfigError(
                    f"{source} campaigns[{campaign_index}] must contain a non-empty tiers array"
                )
            for tier_index, tier in enumerate(tiers, start=1):
                if not isinstance(tier, Mapping):
                    raise PatreonConfigError(
                        f"{source} campaigns[{campaign_index}].tiers[{tier_index}] must be an object"
                    )
                merged = dict(tier)
                merged["campaign_id"] = campaign_id
                if campaign_name is not None:
                    merged.setdefault("campaign_name", campaign_name)
                entries.append((f"campaigns[{campaign_index}].tiers[{tier_index}]", merged))
        return entries

    if isinstance(parsed, dict) and isinstance(parsed.get("entries"), list):
        parsed = parsed["entries"]

    if not isinstance(parsed, list):
        raise PatreonConfigError(f"{source} must be a JSON object with campaigns[] or a JSON array")

    entries = []
    for index, item in enumerate(parsed, start=1):
        if not isinstance(item, Mapping):
            raise PatreonConfigError(f"{source} entry #{index} must be an object")
        entries.append((f"entries[{index}]", item))
    return entries


def _parse_tier_map(raw: str, *, source: str) -> tuple[PatreonTierMapEntry, ...]:
    if not raw.strip():
        return ()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PatreonConfigError(f"{source} must be valid JSON at byte offset {exc.pos}") from exc

    entries: list[PatreonTierMapEntry] = []
    for index, item in _iter_raw_entries(parsed, source=source):
        entries.append(
            PatreonTierMapEntry(
                campaign_id=_required_text(item, "campaign_id", source=source, index=index),
                tier_id=_required_text(item, "tier_id", source=source, index=index),
                plan_code=_required_text(item, "plan_code", source=source, index=index),
                tier_code=_required_text(item, "tier_code", source=source, index=index),
                tier_name=_optional_text(item, "tier_name"),
                priority=_priority(item, source=source, index=index),
                active=_active(item, source=source, index=index),
                campaign_name=_optional_text(item, "campaign_name"),
            )
        )
    _validate_tier_map(entries, source=source)
    return tuple(_dedupe_tier_map(entries))


def _dedupe_tier_map(entries: Sequence[PatreonTierMapEntry]) -> list[PatreonTierMapEntry]:
    seen: set[tuple[str, str, str, str, int, bool]] = set()
    deduped: list[PatreonTierMapEntry] = []
    for entry in entries:
        key = (
            entry.campaign_id,
            entry.tier_id,
            entry.plan_code,
            entry.tier_code,
            entry.priority,
            entry.active,
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(entry)
    return deduped


def _validate_tier_map(entries: Sequence[PatreonTierMapEntry], *, source: str) -> None:
    by_campaign_tier: dict[tuple[str, str], PatreonTierMapEntry] = {}
    active_priority_by_campaign: dict[tuple[str, int], PatreonTierMapEntry] = {}
    active_resolution_by_campaign: dict[tuple[str, str, str, int], PatreonTierMapEntry] = {}

    for index, entry in enumerate(entries, start=1):
        pair = (entry.campaign_id, entry.tier_id)
        prior = by_campaign_tier.get(pair)
        if prior and (
            prior.plan_code != entry.plan_code
            or prior.tier_code != entry.tier_code
            or prior.priority != entry.priority
            or prior.active != entry.active
        ):
            raise PatreonConfigError(
                f"{source} contains ambiguous duplicate campaign/tier mapping at entry #{index}; "
                "priority and plan resolution must be unique"
            )
        by_campaign_tier[pair] = entry

        if not entry.active:
            continue

        priority_key = (entry.campaign_id, entry.priority)
        prior_priority = active_priority_by_campaign.get(priority_key)
        if prior_priority and prior_priority.tier_id != entry.tier_id:
            raise PatreonConfigError(
                f"{source} contains ambiguous active priority within a campaign at entry #{index}"
            )
        active_priority_by_campaign[priority_key] = entry

        resolution_key = (entry.campaign_id, entry.plan_code, entry.tier_code, entry.priority)
        prior_resolution = active_resolution_by_campaign.get(resolution_key)
        if prior_resolution and prior_resolution.tier_id != entry.tier_id:
            raise PatreonConfigError(
                f"{source} contains ambiguous plan resolution within a campaign at entry #{index}"
            )
        active_resolution_by_campaign[resolution_key] = entry


def _tier_map_from_env(values: Mapping[str, str]) -> tuple[PatreonTierMapEntry, ...]:
    direct = _get(values, constants.PATREON_CAMPAIGN_TIER_MAP_ENV)
    if direct:
        return _parse_tier_map(direct, source=constants.PATREON_CAMPAIGN_TIER_MAP_ENV)

    json_value = _get(values, constants.PATREON_TIER_MAP_JSON_ENV)
    if json_value:
        return _parse_tier_map(json_value, source=constants.PATREON_TIER_MAP_JSON_ENV)

    file_path = _get(values, constants.PATREON_TIER_MAP_FILE_ENV)
    if file_path:
        try:
            file_value = Path(file_path).read_text(encoding="utf-8")
        except OSError as exc:
            raise PatreonConfigError(f"{constants.PATREON_TIER_MAP_FILE_ENV} could not be read") from exc
        return _parse_tier_map(file_value, source=constants.PATREON_TIER_MAP_FILE_ENV)

    return ()


def load_patreon_config(*, env: Mapping[str, str] | None = None) -> PatreonConfig:
    """Parse Patreon environment configuration without provider side effects."""

    values = _env(env)
    app_env = _get(values, constants.APP_ENV_ENV)
    allowed_webhook_events = _csv_tuple(
        _get(
            values,
            constants.PATREON_ALLOWED_WEBHOOK_EVENTS_ENV,
            constants.DEFAULT_PATREON_ALLOWED_WEBHOOK_EVENTS_CSV,
        )
    ) or constants.DEFAULT_PATREON_ALLOWED_WEBHOOK_EVENTS

    api_page_size = _bounded_int(
        values,
        constants.PATREON_API_PAGE_SIZE_ENV,
        constants.DEFAULT_PATREON_API_PAGE_SIZE,
        minimum=1,
        maximum=constants.MAX_PATREON_API_PAGE_SIZE,
    )

    return PatreonConfig(
        linking_enabled=_bool(
            _get(values, constants.PATREON_LINKING_ENABLED_ENV),
            default=constants.DEFAULT_PATREON_LINKING_ENABLED,
        ),
        webhooks_enabled=_bool(
            _get(values, constants.PATREON_WEBHOOKS_ENABLED_ENV),
            default=constants.DEFAULT_PATREON_WEBHOOKS_ENABLED,
        ),
        sync_enabled=_bool(
            _get(values, constants.PATREON_SYNC_ENABLED_ENV),
            default=constants.DEFAULT_PATREON_SYNC_ENABLED,
        ),
        s2s_entitlement_enabled=_bool(
            _get(values, constants.PATREON_S2S_ENTITLEMENT_ENABLED_ENV),
            default=constants.DEFAULT_PATREON_S2S_ENTITLEMENT_ENABLED,
        ),
        creator_token_refresh_enabled=_bool(
            _get(values, constants.PATREON_CREATOR_TOKEN_REFRESH_ENABLED_ENV),
            default=constants.DEFAULT_PATREON_CREATOR_TOKEN_REFRESH_ENABLED,
        ),
        raw_payload_capture_enabled=_bool(
            _get(values, constants.PATREON_RAW_PAYLOAD_CAPTURE_ENABLED_ENV),
            default=constants.DEFAULT_PATREON_RAW_PAYLOAD_CAPTURE_ENABLED,
        ),
        api_base_url=_get(
            values, constants.PATREON_API_BASE_URL_ENV, constants.DEFAULT_PATREON_API_BASE_URL
        ),
        oauth_token_url=_get(
            values, constants.PATREON_OAUTH_TOKEN_URL_ENV, constants.DEFAULT_PATREON_OAUTH_TOKEN_URL
        ),
        user_agent=_get(values, constants.PATREON_USER_AGENT_ENV, constants.DEFAULT_PATREON_USER_AGENT),
        allowed_webhook_events=allowed_webhook_events,
        campaign_tier_maps=_tier_map_from_env(values),
        proof_token_ttl_seconds=_int(
            values,
            constants.PATREON_PROOF_TOKEN_TTL_SECONDS_ENV,
            constants.DEFAULT_PATREON_PROOF_TOKEN_TTL_SECONDS,
        ),
        proof_retention_after_expiry_hours=_bounded_int(
            values,
            constants.PATREON_PROOF_RETENTION_AFTER_EXPIRY_HOURS_ENV,
            constants.DEFAULT_PATREON_PROOF_RETENTION_AFTER_EXPIRY_HOURS,
            maximum=constants.MAX_PATREON_PROOF_RETENTION_AFTER_EXPIRY_HOURS,
        ),
        webhook_delivery_retention_days=_bounded_int(
            values,
            constants.PATREON_WEBHOOK_DELIVERY_RETENTION_DAYS_ENV,
            constants.DEFAULT_PATREON_WEBHOOK_DELIVERY_RETENTION_DAYS,
            maximum=constants.MAX_PATREON_WEBHOOK_DELIVERY_RETENTION_DAYS,
        ),
        raw_payload_retention_days=_bounded_int(
            values,
            constants.PATREON_RAW_PAYLOAD_RETENTION_DAYS_ENV,
            constants.DEFAULT_PATREON_RAW_PAYLOAD_RETENTION_DAYS,
            maximum=constants.MAX_PATREON_RAW_PAYLOAD_RETENTION_DAYS,
        ),
        api_timeout_seconds=_int(
            values,
            constants.PATREON_API_TIMEOUT_SECONDS_ENV,
            constants.DEFAULT_PATREON_API_TIMEOUT_SECONDS,
        ),
        api_connect_timeout_seconds=_int(
            values,
            constants.PATREON_API_CONNECT_TIMEOUT_SECONDS_ENV,
            constants.DEFAULT_PATREON_API_CONNECT_TIMEOUT_SECONDS,
        ),
        api_page_size=api_page_size,
        api_max_pages_per_sync=_int(
            values,
            constants.PATREON_API_MAX_PAGES_PER_SYNC_ENV,
            constants.DEFAULT_PATREON_API_MAX_PAGES_PER_SYNC,
        ),
        api_retry_max_attempts=_int(
            values,
            constants.PATREON_API_RETRY_MAX_ATTEMPTS_ENV,
            constants.DEFAULT_PATREON_API_RETRY_MAX_ATTEMPTS,
        ),
        api_retry_backoff_seconds=_int_tuple(
            values,
            constants.PATREON_API_RETRY_BACKOFF_SECONDS_ENV,
            constants.DEFAULT_PATREON_API_RETRY_BACKOFF_SECONDS,
        ),
        api_retry_jitter_seconds=_int(
            values,
            constants.PATREON_API_RETRY_JITTER_SECONDS_ENV,
            constants.DEFAULT_PATREON_API_RETRY_JITTER_SECONDS,
        ),
        creator_token_refresh_margin_seconds=_int(
            values,
            constants.PATREON_CREATOR_TOKEN_REFRESH_MARGIN_SECONDS_ENV,
            constants.DEFAULT_PATREON_CREATOR_TOKEN_REFRESH_MARGIN_SECONDS,
        ),
        sync_interval_seconds=_int(
            values,
            constants.PATREON_SYNC_INTERVAL_SECONDS_ENV,
            constants.DEFAULT_PATREON_SYNC_INTERVAL_SECONDS,
        ),
        sync_jitter_seconds=_int(
            values,
            constants.PATREON_SYNC_JITTER_SECONDS_ENV,
            constants.DEFAULT_PATREON_SYNC_JITTER_SECONDS,
        ),
        sync_stale_after_seconds=_int(
            values,
            constants.PATREON_SYNC_STALE_AFTER_SECONDS_ENV,
            constants.DEFAULT_PATREON_SYNC_STALE_AFTER_SECONDS,
        ),
        sync_worker_poll_seconds=_int(
            values,
            constants.PATREON_SYNC_WORKER_POLL_SECONDS_ENV,
            constants.DEFAULT_PATREON_SYNC_WORKER_POLL_SECONDS,
        ),
        sync_worker_batch_size=_int(
            values,
            constants.PATREON_SYNC_WORKER_BATCH_SIZE_ENV,
            constants.DEFAULT_PATREON_SYNC_WORKER_BATCH_SIZE,
        ),
        sync_job_lease_seconds=_int(
            values,
            constants.PATREON_SYNC_JOB_LEASE_SECONDS_ENV,
            constants.DEFAULT_PATREON_SYNC_JOB_LEASE_SECONDS,
        ),
        sync_max_attempts=_int(
            values,
            constants.PATREON_SYNC_MAX_ATTEMPTS_ENV,
            constants.DEFAULT_PATREON_SYNC_MAX_ATTEMPTS,
        ),
        sync_backoff_seconds=_int_tuple(
            values,
            constants.PATREON_SYNC_BACKOFF_SECONDS_ENV,
            constants.DEFAULT_PATREON_SYNC_BACKOFF_SECONDS,
        ),
        webhook_signature_failure_alert_limit=_int(
            values,
            constants.PATREON_WEBHOOK_SIGNATURE_FAILURE_ALERT_LIMIT_ENV,
            constants.DEFAULT_PATREON_WEBHOOK_SIGNATURE_FAILURE_ALERT_LIMIT,
        ),
        webhook_signature_failure_alert_window_seconds=_int(
            values,
            constants.PATREON_WEBHOOK_SIGNATURE_FAILURE_ALERT_WINDOW_SECONDS_ENV,
            constants.DEFAULT_PATREON_WEBHOOK_SIGNATURE_FAILURE_ALERT_WINDOW_SECONDS,
        ),
        app_env=app_env,
        explicit_test_runtime=is_explicit_test_runtime(values),
        creator_access_token=_get(values, constants.PATREON_CREATOR_ACCESS_TOKEN_ENV) or None,
        creator_refresh_token=_get(values, constants.PATREON_CREATOR_REFRESH_TOKEN_ENV) or None,
        client_id=_get(values, constants.PATREON_CLIENT_ID_ENV) or None,
        client_secret=_get(values, constants.PATREON_CLIENT_SECRET_ENV) or None,
        webhook_secret=_get(values, constants.PATREON_WEBHOOK_SECRET_ENV) or None,
        webhook_id=_get(values, constants.PATREON_WEBHOOK_ID_ENV) or None,
        s2s_bearer_token=_get(values, constants.PATREON_S2S_BEARER_TOKEN_ENV) or None,
        provider_sub_pepper=_get(values, constants.PATREON_PROVIDER_SUB_PEPPER_ENV) or None,
        email_hash_pepper=_get(values, constants.PATREON_EMAIL_HASH_PEPPER_ENV) or None,
        proof_token_pepper=_get(values, constants.PATREON_PROOF_TOKEN_PEPPER_ENV) or None,
        id_hmac_secret=(
            _get(values, constants.PATREON_ID_HMAC_SECRET_ENV)
            or _get(values, constants.PATREON_HMAC_SECRET_ENV)
            or None
        ),
        webhook_delivery_hash_pepper=(
            _get(values, constants.PATREON_WEBHOOK_DELIVERY_HASH_PEPPER_ENV) or None
        ),
        provider_token_encryption_key=(
            _get(values, constants.PATREON_PROVIDER_TOKEN_ENCRYPTION_KEY_ENV) or None
        ),
        provider_token_encryption_key_id=(
            _get(values, constants.PATREON_PROVIDER_TOKEN_ENCRYPTION_KEY_ID_ENV) or None
        ),
    )


def validate_patreon_readiness(config: PatreonConfig) -> PatreonReadiness:
    """Return a non-secret readiness state for configured Patreon behavior."""

    if config.disabled:
        return PatreonReadiness(ready=False, status="disabled")

    missing: list[str] = []
    required: list[tuple[str, Any]] = []

    if config.linking_enabled or config.sync_enabled:
        required.extend(
            [
                (constants.PATREON_CREATOR_ACCESS_TOKEN_ENV, config.creator_access_token),
                (constants.PATREON_PROVIDER_SUB_PEPPER_ENV, config.provider_sub_pepper),
                (constants.PATREON_EMAIL_HASH_PEPPER_ENV, config.email_hash_pepper),
            ]
        )

    if config.linking_enabled:
        required.append((constants.PATREON_PROOF_TOKEN_PEPPER_ENV, config.proof_token_pepper))

    if config.webhooks_enabled:
        required.append((constants.PATREON_WEBHOOK_SECRET_ENV, config.webhook_secret))

    if config.s2s_entitlement_enabled:
        required.append((constants.PATREON_S2S_BEARER_TOKEN_ENV, config.s2s_bearer_token))

    if config.creator_token_refresh_enabled:
        required.extend(
            [
                (constants.PATREON_CREATOR_REFRESH_TOKEN_ENV, config.creator_refresh_token),
                (constants.PATREON_CLIENT_ID_ENV, config.client_id),
                (constants.PATREON_CLIENT_SECRET_ENV, config.client_secret),
                (constants.PATREON_PROVIDER_TOKEN_ENCRYPTION_KEY_ENV, config.provider_token_encryption_key),
                (
                    constants.PATREON_PROVIDER_TOKEN_ENCRYPTION_KEY_ID_ENV,
                    config.provider_token_encryption_key_id,
                ),
            ]
        )

    if config.raw_payload_capture_enabled:
        required.extend(
            [
                (constants.PATREON_PROVIDER_TOKEN_ENCRYPTION_KEY_ENV, config.provider_token_encryption_key),
                (
                    constants.PATREON_PROVIDER_TOKEN_ENCRYPTION_KEY_ID_ENV,
                    config.provider_token_encryption_key_id,
                ),
            ]
        )

    if any(config.primary_feature_flags.values()) and not config.campaign_tier_maps:
        missing.append(constants.PATREON_CAMPAIGN_TIER_MAP_ENV)

    for name, value in required:
        if not value and name not in missing:
            missing.append(name)

    if missing:
        return PatreonReadiness(ready=False, status="not_ready", missing=missing)

    disabled_features = [name for name, enabled in config.primary_feature_flags.items() if not enabled]
    if disabled_features:
        return PatreonReadiness(
            ready=False,
            status="partially_disabled",
            degraded=[f"{name}_disabled" for name in disabled_features],
        )

    return PatreonReadiness(ready=True, status="ready")


def patreon_disabled_or_not_ready_status(config: PatreonConfig) -> str:
    """Return a neutral posture label for route/worker checks."""

    return validate_patreon_readiness(config).status


def is_patreon_feature_enabled(config: PatreonConfig, feature: str) -> bool:
    """Return whether a Patreon kill switch allows a specific feature."""

    return config.is_feature_enabled(feature)
