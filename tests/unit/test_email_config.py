"""RED contract tests for email delivery config and no-real-send guard.

Trace: `.dev/sdd/changes/email-activation/tasks.md` task 1.2 and the
spec/design no-real-send test guard requirements.
"""

from __future__ import annotations

import pytest


def _config_module():
    from src.Util.email import config

    return config


def _base_env(**overrides):
    env = {
        "APP_ENV": "test",
        "PYTEST_CURRENT_TEST": "tests/unit/test_email_config.py::test_guard (call)",
        "EMAIL_DELIVERY_ENABLED": "true",
        "EMAIL_PROVIDER": "fake",
        "EMAIL_FROM_ADDRESS": "Auth <auth@example.com>",
        "EMAIL_TOKEN_PEPPER": "test-token-pepper",
        "EMAIL_HASH_PEPPER": "test-hash-pepper",
        "EMAIL_PAYLOAD_KEY": "MTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTE=",
    }
    env.update(overrides)
    return env


def test_real_provider_credentials_in_test_without_opt_in_fail_fast(monkeypatch):
    config = _config_module()

    for key, value in _base_env(
        EMAIL_PROVIDER="resend",
        RESEND_API_KEY="re_test_real_credential",
        EMAIL_ALLOW_REAL_SEND_IN_TESTS="false",
    ).items():
        monkeypatch.setenv(key, value)

    with pytest.raises(config.EmailConfigError, match="real email sends.*test"):
        config.load_email_config()


def test_fake_provider_is_allowed_in_explicit_test_runtime(monkeypatch):
    config = _config_module()

    for key, value in _base_env(EMAIL_PROVIDER="fake").items():
        monkeypatch.setenv(key, value)

    loaded = config.load_email_config()

    assert loaded.provider == "fake"
    assert loaded.delivery_enabled is True
    assert loaded.real_send_allowed is False


def test_mailpit_local_provider_is_allowed_in_explicit_test_runtime(monkeypatch):
    config = _config_module()

    for key, value in _base_env(
        EMAIL_PROVIDER="mailpit",
        MAILPIT_SMTP_HOST="127.0.0.1",
        MAILPIT_SMTP_PORT="1025",
    ).items():
        monkeypatch.setenv(key, value)

    loaded = config.load_email_config()

    assert loaded.provider == "mailpit"
    assert loaded.mailpit_smtp_host == "127.0.0.1"
    assert loaded.mailpit_smtp_port == 1025


def test_missing_production_prerequisites_report_not_ready(monkeypatch):
    config = _config_module()

    for key, value in _base_env(
        APP_ENV="production",
        PYTEST_CURRENT_TEST="",
        EMAIL_PROVIDER="resend",
        RESEND_API_KEY="",
        RESEND_WEBHOOK_SECRET="",
        EMAIL_FROM_ADDRESS="",
        EMAIL_DELIVERY_ENABLED="true",
    ).items():
        monkeypatch.setenv(key, value)

    readiness = config.validate_email_readiness(config.load_email_config(validate_real_send_guard=False))

    assert readiness.ready is False
    assert "RESEND_API_KEY" in readiness.missing
    assert "RESEND_WEBHOOK_SECRET" in readiness.missing
    assert "EMAIL_FROM_ADDRESS" in readiness.missing


def test_delivery_disabled_is_safe_not_ready_without_real_send(monkeypatch):
    config = _config_module()

    for key, value in _base_env(
        EMAIL_DELIVERY_ENABLED="false",
        EMAIL_PROVIDER="resend",
        RESEND_API_KEY="re_would_be_real_but_disabled",
    ).items():
        monkeypatch.setenv(key, value)

    loaded = config.load_email_config()
    readiness = config.validate_email_readiness(loaded)

    assert loaded.delivery_enabled is False
    assert readiness.status == "disabled"
    assert readiness.ready is False


def test_enabled_fake_provider_is_not_ready_outside_explicit_test_runtime(monkeypatch):
    config = _config_module()

    for key, value in _base_env(
        APP_ENV="development",
        PYTEST_CURRENT_TEST="",
        EMAIL_DELIVERY_ENABLED="true",
        EMAIL_PROVIDER="fake",
    ).items():
        monkeypatch.setenv(key, value)

    readiness = config.validate_email_readiness(config.load_email_config())

    assert readiness.ready is False
    assert readiness.status == "not_ready"
    assert "EMAIL_PROVIDER" in readiness.missing
