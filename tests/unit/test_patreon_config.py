"""RED unit contracts for Patreon provider configuration.

Trace: `.dev/sdd/changes/patreon-account-link/tasks.md` task 1.3 and
spec/design requirements for disabled defaults, readiness, multi-campaign tier
mapping, retention caps, kill switches, and secret-safe configuration output.

Future implementation imports happen inside test bodies so collection stays
green while Phase 3 production modules are still missing.
"""

from __future__ import annotations

import importlib
import json
import re
from pathlib import Path
from types import ModuleType
from typing import Any, Mapping

import pytest


MODULE_NAME = "src.Util.patreon.config"
ROOT = Path(__file__).resolve().parents[2]

_MISSING = object()


def _future_config_module() -> ModuleType:
    try:
        return importlib.import_module(MODULE_NAME)
    except ModuleNotFoundError as exc:
        if exc.name and MODULE_NAME.startswith(exc.name):
            pytest.fail(
                f"missing implementation module: {MODULE_NAME}; "
                "Phase 3.3 must provide the Patreon config loader",
                pytrace=False,
            )
        pytest.fail(f"{MODULE_NAME} import failed due to missing dependency: {exc.name}", pytrace=False)


def _field(value: Any, name: str, default: Any = _MISSING) -> Any:
    if isinstance(value, Mapping):
        if name in value:
            return value[name]
    elif hasattr(value, name):
        return getattr(value, name)
    if default is not _MISSING:
        return default
    pytest.fail(f"Patreon config/readiness object missing field `{name}`")


def _loader(module: ModuleType):
    loader = getattr(module, "load_patreon_config", None)
    assert callable(loader), "expected load_patreon_config(env=...) contract"
    return loader


def _readiness_validator(module: ModuleType):
    validator = getattr(module, "validate_patreon_readiness", None)
    assert callable(validator), "expected validate_patreon_readiness(config) contract"
    return validator


def _config_error(module: ModuleType) -> type[BaseException]:
    error_type = getattr(module, "PatreonConfigError", None)
    assert isinstance(error_type, type), "expected PatreonConfigError exception type"
    return error_type


def _tier_map_json(*, ambiguous: bool = False) -> str:
    tier_map = {
        "campaigns": [
            {
                "campaign_id": "campaign-mw-alpha",
                "tiers": [
                    {
                        "tier_id": "tier-mw-alpha-artisan",
                        "plan_code": "plus",
                        "tier_code": "artisan",
                        "tier_name": "Artisan",
                        "priority": 10,
                    },
                    {
                        "tier_id": "tier-mw-alpha-legend",
                        "plan_code": "pro",
                        "tier_code": "legend",
                        "tier_name": "Legend",
                        "priority": 50,
                    },
                ],
            },
            {
                "campaign_id": "campaign-mw-beta",
                "tiers": [
                    {
                        "tier_id": "tier-mw-beta-legend",
                        "plan_code": "pro",
                        "tier_code": "beta_legend",
                        "tier_name": "Beta Legend",
                        "priority": 40,
                    }
                ],
            },
        ]
    }
    if ambiguous:
        tier_map["campaigns"][0]["tiers"].append(
            {
                "tier_id": "tier-mw-alpha-legend",
                "plan_code": "enterprise",
                "tier_code": "legend_conflict",
                "tier_name": "Conflicting Legend",
                "priority": 50,
            }
        )
    return json.dumps(tier_map, separators=(",", ":"), sort_keys=True)


def _base_env(**overrides: str) -> dict[str, str]:
    env = {
        "APP_ENV": "test",
        "PATREON_LINKING_ENABLED": "true",
        "PATREON_WEBHOOKS_ENABLED": "true",
        "PATREON_SYNC_ENABLED": "true",
        "PATREON_S2S_ENTITLEMENT_ENABLED": "true",
        "PATREON_CREATOR_ACCESS_TOKEN": "test-patreon-creator-access-token-not-real",
        "PATREON_CREATOR_REFRESH_TOKEN": "test-patreon-creator-refresh-token-not-real",
        "PATREON_CLIENT_ID": "test-patreon-client-id-not-real",
        "PATREON_CLIENT_SECRET": "test-patreon-client-secret-not-real",
        "PATREON_WEBHOOK_SECRET": "test-patreon-webhook-secret-not-real",
        "PATREON_PROVIDER_SUB_PEPPER": "test-patreon-provider-sub-pepper-not-real-min-32-bytes!!",
        "PATREON_EMAIL_HASH_PEPPER": "test-patreon-email-hash-pepper-not-real-min-32-bytes!!",
        "PATREON_PROOF_TOKEN_PEPPER": "test-patreon-proof-token-pepper-not-real-min-32-bytes!!",
        "PATREON_ID_HMAC_SECRET": "test-patreon-id-hmac-secret-not-real-min-32-bytes!!",
        "PATREON_S2S_BEARER_TOKEN": "test-patreon-s2s-bearer-token-not-real",
        "PATREON_USER_AGENT": "api.auth Patreon tests (no real provider calls)",
        "PATREON_CAMPAIGN_TIER_MAP": _tier_map_json(),
        "PATREON_ALLOWED_WEBHOOK_EVENTS": "members:create,members:update,members:delete,members:pledge:create,members:pledge:update,members:pledge:delete",
        "PATREON_PROOF_RETENTION_AFTER_EXPIRY_HOURS": "24",
        "PATREON_WEBHOOK_DELIVERY_RETENTION_DAYS": "90",
        "PATREON_RAW_PAYLOAD_RETENTION_DAYS": "30",
        "PATREON_RAW_PAYLOAD_CAPTURE_ENABLED": "false",
    }
    env.update(overrides)
    return env


def _entries_from_config(config: Any) -> list[Any]:
    for attr in ("campaign_tier_maps", "tier_map_entries", "tier_maps"):
        entries = _field(config, attr, None)
        if entries is not None:
            if isinstance(entries, Mapping):
                return list(entries.values())
            return list(entries)
    pytest.fail("Patreon config must expose parsed campaign tier-map entries")


def _flag(config: Any, name: str) -> bool:
    candidates = (name, f"{name}_enabled", f"is_{name}_enabled")
    for candidate in candidates:
        value = _field(config, candidate, _MISSING)
        if value is _MISSING:
            continue
        return bool(value() if callable(value) else value)
    pytest.fail(f"Patreon config missing kill-switch flag for `{name}`")


def test_disabled_by_default_config_is_not_ready_and_does_not_require_provider_secrets():
    module = _future_config_module()
    config = _loader(module)(env={"APP_ENV": "test"})
    readiness = _readiness_validator(module)(config)

    assert _flag(config, "linking") is False
    assert _flag(config, "webhooks") is False
    assert _flag(config, "sync") is False
    assert _flag(config, "s2s_entitlement") is False
    assert _field(readiness, "ready") is False
    assert _field(readiness, "status") == "disabled"
    assert _field(readiness, "missing", []) == []


def test_enabled_readiness_requires_all_server_only_patreon_secrets_without_leaking_values():
    module = _future_config_module()
    config = _loader(module)(
        env=_base_env(
            PATREON_CREATOR_ACCESS_TOKEN="",
            PATREON_WEBHOOK_SECRET="",
            PATREON_PROVIDER_SUB_PEPPER="",
            PATREON_EMAIL_HASH_PEPPER="",
            PATREON_PROOF_TOKEN_PEPPER="",
            PATREON_ID_HMAC_SECRET="",
            PATREON_S2S_BEARER_TOKEN="",
        )
    )
    readiness = _readiness_validator(module)(config)

    assert _field(readiness, "ready") is False
    assert _field(readiness, "status") == "not_ready"
    assert set(_field(readiness, "missing")) >= {
        "PATREON_CREATOR_ACCESS_TOKEN",
        "PATREON_WEBHOOK_SECRET",
        "PATREON_PROVIDER_SUB_PEPPER",
        "PATREON_EMAIL_HASH_PEPPER",
        "PATREON_PROOF_TOKEN_PEPPER",
        "PATREON_ID_HMAC_SECRET",
        "PATREON_S2S_BEARER_TOKEN",
    }
    serialized = repr(readiness)
    assert "test-patreon" not in serialized


def test_creator_token_refresh_requires_encrypted_global_token_state_config():
    module = _future_config_module()
    config = _loader(module)(
        env=_base_env(
            PATREON_CREATOR_TOKEN_REFRESH_ENABLED="true",
            PATREON_PROVIDER_TOKEN_ENCRYPTION_KEY="",
            PATREON_PROVIDER_TOKEN_ENCRYPTION_KEY_ID="",
        )
    )
    readiness = _readiness_validator(module)(config)

    assert _field(readiness, "ready") is False
    assert _field(readiness, "status") == "not_ready"
    assert set(_field(readiness, "missing")) >= {
        "PATREON_PROVIDER_TOKEN_ENCRYPTION_KEY",
        "PATREON_PROVIDER_TOKEN_ENCRYPTION_KEY_ID",
    }


def test_valid_multi_campaign_tier_map_is_parsed_and_ready():
    module = _future_config_module()
    config = _loader(module)(env=_base_env())
    readiness = _readiness_validator(module)(config)
    entries = _entries_from_config(config)

    assert _field(readiness, "ready") is True
    assert _field(readiness, "status") == "ready"
    assert len(entries) >= 3
    serialized_entries = json.dumps(entries, default=lambda value: getattr(value, "__dict__", repr(value)))
    assert "campaign-mw-alpha" in serialized_entries
    assert "campaign-mw-beta" in serialized_entries
    assert "tier-mw-alpha-legend" in serialized_entries


def test_campaign_ids_env_is_parsed_as_server_only_allow_list_without_replacing_tier_map():
    module = _future_config_module()
    config = _loader(module)(
        env=_base_env(PATREON_CAMPAIGN_IDS="campaign-mw-beta,campaign-mw-gamma,campaign-mw-alpha")
    )

    assert _field(config, "configured_campaign_ids") == (
        "campaign-mw-beta",
        "campaign-mw-gamma",
        "campaign-mw-alpha",
    )
    assert _field(config, "campaign_ids") == (
        "campaign-mw-alpha",
        "campaign-mw-beta",
        "campaign-mw-gamma",
    )


def test_enabled_readiness_requires_id_hmac_secret_for_stable_provider_identity():
    module = _future_config_module()
    config = _loader(module)(env=_base_env(PATREON_ID_HMAC_SECRET="", PATREON_HMAC_SECRET=""))
    readiness = _readiness_validator(module)(config)

    assert _field(readiness, "ready") is False
    assert _field(readiness, "status") == "not_ready"
    assert "PATREON_ID_HMAC_SECRET" in _field(readiness, "missing")


def test_ambiguous_tier_mapping_refuses_enablement():
    module = _future_config_module()
    loader = _loader(module)
    error_type = _config_error(module)

    with pytest.raises(error_type, match="PATREON_CAMPAIGN_TIER_MAP|ambiguous|priority"):
        loader(env=_base_env(PATREON_CAMPAIGN_TIER_MAP=_tier_map_json(ambiguous=True)))


@pytest.mark.parametrize(
    ("env_name", "bad_value"),
    [
        ("PATREON_PROOF_RETENTION_AFTER_EXPIRY_HOURS", "25"),
        ("PATREON_WEBHOOK_DELIVERY_RETENTION_DAYS", "91"),
        ("PATREON_RAW_PAYLOAD_RETENTION_DAYS", "31"),
    ],
)
def test_retention_caps_refuse_values_beyond_the_specified_maximums(env_name: str, bad_value: str):
    module = _future_config_module()
    loader = _loader(module)
    error_type = _config_error(module)

    with pytest.raises(error_type, match=env_name):
        loader(env=_base_env(**{env_name: bad_value}))


def test_individual_kill_switches_disable_new_behavior_without_erasing_config():
    module = _future_config_module()
    config = _loader(module)(
        env=_base_env(
            PATREON_LINKING_ENABLED="false",
            PATREON_WEBHOOKS_ENABLED="false",
            PATREON_SYNC_ENABLED="false",
            PATREON_S2S_ENTITLEMENT_ENABLED="false",
        )
    )
    readiness = _readiness_validator(module)(config)

    assert _flag(config, "linking") is False
    assert _flag(config, "webhooks") is False
    assert _flag(config, "sync") is False
    assert _flag(config, "s2s_entitlement") is False
    assert _field(readiness, "ready") is False
    assert _field(readiness, "status") in {"disabled", "not_ready", "partially_disabled"}
    assert _entries_from_config(config), "tier-map config should remain parseable while behavior is disabled"


def test_config_and_readiness_repr_do_not_expose_raw_secret_values():
    module = _future_config_module()
    config = _loader(module)(env=_base_env())
    readiness = _readiness_validator(module)(config)

    rendered = f"{config!r}\n{readiness!r}"
    for secret_value in (
        "test-patreon-creator-access-token-not-real",
        "test-patreon-creator-refresh-token-not-real",
        "test-patreon-client-secret-not-real",
        "test-patreon-webhook-secret-not-real",
        "test-patreon-provider-sub-pepper-not-real-min-32-bytes!!",
        "test-patreon-email-hash-pepper-not-real-min-32-bytes!!",
        "test-patreon-proof-token-pepper-not-real-min-32-bytes!!",
        "test-patreon-s2s-bearer-token-not-real",
    ):
        assert secret_value not in rendered


def test_env_example_documents_every_patreon_runtime_environment_name():
    module = _future_config_module()
    constants = module.constants
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    documented = set(re.findall(r"^\s*#?\s*([A-Z][A-Z0-9_]+)\s*=", env_example, flags=re.MULTILINE))

    expected = {
        value
        for name, value in vars(constants).items()
        if name.endswith("_ENV")
        and isinstance(value, str)
        and (value.startswith("PATREON_") or value.startswith("RUN_PATREON_"))
    }
    for names in constants.PATREON_RATE_LIMIT_ENV_NAMES.values():
        expected.update(names)

    assert expected - documented == set()
    assert "PATREON_PROOF_HMAC_SECRET" not in documented
