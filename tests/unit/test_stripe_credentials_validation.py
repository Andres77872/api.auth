"""Unit tests for live Stripe credential validation (no live Stripe / DB).

Covers: format rejection, live auth-probe failure (401 -> invalid; network/None -> fail-closed reject),
portal-config validation, the happy path, and the StripeBillingClient.retrieve_account auth probe.
Never leaks key material.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.Util.error_handler import ErrorCode, ValidationError
from src.Util.stripe import credentials as creds
from src.Util.stripe.client import StripeAPIError, StripeBillingClient


def _body(secret_key="sk_test_valid", webhook_secret=None, portal_configuration_id=None):
    return SimpleNamespace(
        secret_key=secret_key,
        webhook_secret=webhook_secret,
        portal_configuration_id=portal_configuration_id,
    )


class _FakeClient:
    def __init__(self, *, account=None, account_error=None, portal=None, portal_error=None):
        self._account = account if account is not None else {"id": "acct_123", "livemode": False}
        self._account_error = account_error
        self._portal = portal
        self._portal_error = portal_error

    def retrieve_account(self):
        if self._account_error is not None:
            raise self._account_error
        return self._account

    def retrieve_portal_configuration(self, configuration_id):
        if self._portal_error is not None:
            raise self._portal_error
        return self._portal


def _factory(client):
    return lambda secret_key: client


# --------------------------------------------------------------------------- format checks


@pytest.mark.parametrize(
    "body",
    [
        _body(secret_key="not_a_key"),
        _body(secret_key=""),
        _body(webhook_secret="nope"),
        _body(portal_configuration_id="cfg_123"),
    ],
)
def test_bad_format_is_rejected_before_any_network(body):
    called = {"factory": False}

    def factory(_secret):
        called["factory"] = True
        return _FakeClient()

    with pytest.raises(ValidationError) as exc:
        creds.validate_stripe_credentials(body, client_factory=factory)
    assert exc.value.error_code == ErrorCode.INVALID_INPUT
    # Format failures short-circuit before building the client / hitting Stripe.
    assert called["factory"] is False


# --------------------------------------------------------------------------- live auth probe


def test_invalid_key_401_is_rejected():
    client = _FakeClient(account_error=StripeAPIError(status_code=401))
    with pytest.raises(ValidationError) as exc:
        creds.validate_stripe_credentials(_body(), client_factory=_factory(client))
    assert exc.value.error_code == ErrorCode.INVALID_INPUT


def test_network_error_fails_closed():
    # No status code (network/unknown) -> we cannot confirm -> reject, do not store.
    client = _FakeClient(account_error=StripeAPIError(status_code=None))
    with pytest.raises(ValidationError):
        creds.validate_stripe_credentials(_body(), client_factory=_factory(client))


def test_valid_key_passes_and_reports_livemode():
    client = _FakeClient(account={"id": "acct_live", "livemode": True})
    result = creds.validate_stripe_credentials(_body(secret_key="sk_live_x"), client_factory=_factory(client))
    assert result.valid is True
    assert result.secret_key_valid is True
    assert result.livemode is True
    assert result.portal_configuration_valid is None  # none submitted


# --------------------------------------------------------------------------- portal config


def _portal_ok():
    return {
        "features": {
            "payment_method_update": {"enabled": True},
            "subscription_cancel": {"enabled": True},
            "subscription_update": {"enabled": False},
        }
    }


def test_portal_config_valid():
    client = _FakeClient(portal=_portal_ok())
    result = creds.validate_stripe_credentials(
        _body(portal_configuration_id="bpc_123"), client_factory=_factory(client)
    )
    assert result.portal_configuration_valid is True


def test_portal_config_restricted_violation_is_rejected():
    bad = {"features": {"subscription_update": {"enabled": True}, "payment_method_update": {"enabled": True}, "subscription_cancel": {"enabled": True}}}
    client = _FakeClient(portal=bad)
    with pytest.raises(ValidationError) as exc:
        creds.validate_stripe_credentials(_body(portal_configuration_id="bpc_123"), client_factory=_factory(client))
    assert exc.value.error_code == ErrorCode.STRIPE_PORTAL_CONFIGURATION_INVALID


def test_portal_config_not_found_is_rejected():
    client = _FakeClient(portal_error=StripeAPIError(status_code=404))
    with pytest.raises(ValidationError) as exc:
        creds.validate_stripe_credentials(_body(portal_configuration_id="bpc_404"), client_factory=_factory(client))
    assert exc.value.error_code == ErrorCode.STRIPE_PORTAL_CONFIGURATION_INVALID


# --------------------------------------------------------------------------- retrieve_account probe (wrapper -> SDK)


class _FakeV1:
    def __init__(self, accounts):
        self.accounts = accounts


class _FakeAccounts:
    def __init__(self, *, result=None, raise_exc=None):
        self._result = result
        self._raise = raise_exc

    def retrieve_current(self, params=None, *, options=None):
        if self._raise is not None:
            raise self._raise
        return self._result


def test_retrieve_account_maps_result():
    sdk = SimpleNamespace(v1=_FakeV1(_FakeAccounts(result={"id": "acct_X", "livemode": False})))
    client = StripeBillingClient(secret_key="sk_test_x", stripe_client=sdk)
    out = client.retrieve_account()
    assert out["id"] == "acct_X"


def test_retrieve_account_redacts_errors():
    boom = RuntimeError("leak sk_live_should_not_appear")
    sdk = SimpleNamespace(v1=_FakeV1(_FakeAccounts(raise_exc=boom)))
    client = StripeBillingClient(secret_key="sk_test_x", stripe_client=sdk)
    with pytest.raises(StripeAPIError) as exc:
        client.retrieve_account()
    assert "sk_live_should_not_appear" not in str(exc.value)
