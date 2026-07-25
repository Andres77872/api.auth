"""Readiness is per-group: the global env Stripe secrets no longer gate readiness.

Per-group billing accounts own the real secret/webhook/portal credentials, so an operator
running multi-account with no env secrets must NOT be marked ``not_ready``. SDK/API version
pins stay fail-closed.
"""

from __future__ import annotations

from src.Util.stripe.config import (
    SUPPORTED_STRIPE_API_VERSION,
    SUPPORTED_STRIPE_SDK_VERSION,
    validate_stripe_runtime_readiness,
)


def test_all_flags_enabled_without_env_secrets_is_ready():
    readiness = validate_stripe_runtime_readiness(
        installed_sdk_version=SUPPORTED_STRIPE_SDK_VERSION,
        configured_api_version=SUPPORTED_STRIPE_API_VERSION,
        stripe_enabled=True,
        webhooks_enabled=True,
        checkout_enabled=True,
        portal_enabled=True,
        sync_enabled=True,
        # deliberately no secret_key / webhook_secret / portal_configuration_id
    )

    assert readiness.status != "not_ready"
    assert "STRIPE_SECRET_KEY" not in readiness.missing
    assert "STRIPE_WEBHOOK_SECRET" not in readiness.missing
    assert "STRIPE_PORTAL_CONFIGURATION_ID" not in readiness.missing


def test_sdk_version_mismatch_still_fails_closed_without_env_secret():
    readiness = validate_stripe_runtime_readiness(
        installed_sdk_version="15.2.0",  # != supported pin
        configured_api_version=SUPPORTED_STRIPE_API_VERSION,
        stripe_enabled=True,
        checkout_enabled=True,
    )

    assert readiness.status == "not_ready"
    assert readiness.critical_mismatches  # mismatch is what fails it, not the absent env secret
