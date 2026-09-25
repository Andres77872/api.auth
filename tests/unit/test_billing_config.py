"""Billing configuration keeps only settings that change behavior."""

from __future__ import annotations

import dataclasses

from src.Util.billing.config import BillingConfig, load_billing_config, validate_billing_readiness


_READY_ENV = {
    "BILLING_ENABLED": "true",
    "BILLING_S2S_ENABLED": "true",
    "BILLING_SYNC_ENABLED": "true",
    "BILLING_S2S_BEARER_TOKEN": "bearer",
    "BILLING_ID_HMAC_SECRET": "hmac-secret",
    "BILLING_PROVIDER_REF_ENCRYPTION_KEY": "key",
    "BILLING_PROVIDER_REF_ENCRYPTION_KEY_ID": "key-1",
}


def test_removed_raw_capture_and_stale_window_settings_are_not_modelled():
    fields = {field.name for field in dataclasses.fields(BillingConfig)}

    assert not fields & {
        "raw_payload_capture_enabled",
        "raw_payload_encryption_key",
        "raw_payload_encryption_key_id",
        "sync_stale_after_seconds",
    }


def test_a_leftover_raw_capture_flag_no_longer_changes_readiness():
    """The flag only made readiness demand a key for a capture path that never existed."""

    config = load_billing_config(env={**_READY_ENV, "BILLING_RAW_PAYLOAD_CAPTURE_ENABLED": "true"})

    readiness = validate_billing_readiness(config)

    assert readiness.ready is True
    assert not [name for name in readiness.missing if "RAW_PAYLOAD" in name]


def test_checkout_without_return_url_allowlist_is_not_ready():
    config = load_billing_config(env={**_READY_ENV, "BILLING_CHECKOUT_ENABLED": "true"})

    readiness = validate_billing_readiness(config)

    assert readiness.ready is False
    assert "BILLING_RETURN_URL_ALLOWLIST" in readiness.missing
