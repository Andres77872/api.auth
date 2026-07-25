"""Unit tests for catalog -> Stripe provisioning (no live Stripe / DB).

Verifies that creating a catalog item provisions a Stripe Product + Price on the group's
account, stores encrypted refs (with non-secret fingerprints), and that failures roll the
row to ``failed`` with a redacted reason — never leaking raw Stripe ids/keys.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet

from src.Util.stripe import provisioning as prov
from src.Util.stripe.client import StripeAPIError


@dataclass
class _FakeStripeClient:
    fail_on_price: bool = False
    captured: dict | None = None

    def __post_init__(self):
        self.captured = {}

    def create_product(self, *, name, metadata=None, idempotency_key=None):
        self.captured["product_name"] = name
        self.captured["product_idem"] = idempotency_key
        return {"id": "prod_TEST123"}

    def create_price(self, **kwargs):
        self.captured["price_kwargs"] = kwargs
        if self.fail_on_price:
            raise StripeAPIError(message="Stripe provider request failed", status_code=402, code="card_declined")
        return {"id": "price_TEST456"}


class _FakeDB:
    def __init__(self):
        self.provisioned = None
        self.failed = None

    def set_catalog_item_provisioned(self, **kwargs):
        self.provisioned = kwargs
        return {"id": kwargs["id"], "provisioning_status": "active", "active": True,
                "provider_price_id_fingerprint": kwargs["provider_price_id_fingerprint"]}

    def set_catalog_item_failed(self, **kwargs):
        self.failed = kwargs
        return {"id": kwargs["id"], "provisioning_status": "failed", "active": False}


@pytest.fixture
def billing_config(monkeypatch):
    fernet_key = Fernet.generate_key().decode("utf-8")
    cfg = SimpleNamespace(
        provider_ref_encryption_key=fernet_key,
        provider_ref_encryption_key_id="key-test-1",
        id_hmac_secret="unit-test-hmac-secret",
        decryption_keys_by_id={"key-test-1": fernet_key},
    )
    monkeypatch.setattr(prov, "load_billing_config", lambda: cfg)
    return cfg


def _is_12_hex(value: str) -> bool:
    return isinstance(value, str) and len(value) == 12 and all(c in "0123456789abcdef" for c in value)


def test_provision_subscription_plan_creates_product_and_price(billing_config):
    client = _FakeStripeClient()
    db = _FakeDB()
    result = prov.provision_catalog_item(
        billing_group_id="bg-1",
        catalog_item_id="bcat-aaaaaa111111",
        item_type="subscription_plan",
        display_name="Plus",
        currency="usd",
        unit_amount=999,
        recurring_interval="month",
        lookup_key="plus_monthly",
        client=client,
        db=db,
    )
    assert result.provisioning_status == "active"
    assert client.captured["price_kwargs"]["recurring"] == {"interval": "month"}
    assert client.captured["price_kwargs"]["lookup_key"] == "plus_monthly"
    # encrypted refs stored with a non-secret 12-hex fingerprint, never the raw id
    assert db.provisioned is not None
    assert db.provisioned["provider_ref_key_id"] == "key-test-1"
    assert _is_12_hex(db.provisioned["provider_price_id_fingerprint"])
    assert b"price_TEST456" not in bytes(db.provisioned["provider_price_id_ciphertext"])


def test_provision_credit_package_is_one_time_price(billing_config):
    client = _FakeStripeClient()
    db = _FakeDB()
    result = prov.provision_catalog_item(
        billing_group_id="bg-1",
        catalog_item_id="bcat-bbbbbb222222",
        item_type="credit_package",
        display_name="100 credits",
        currency="usd",
        unit_amount=500,
        recurring_interval=None,
        lookup_key="payg_100",
        client=client,
        db=db,
    )
    assert result.provisioning_status == "active"
    assert "recurring" not in client.captured["price_kwargs"]


def test_provision_failure_marks_failed_and_redacts(billing_config):
    client = _FakeStripeClient(fail_on_price=True)
    db = _FakeDB()
    result = prov.provision_catalog_item(
        billing_group_id="bg-1",
        catalog_item_id="bcat-cccccc333333",
        item_type="subscription_plan",
        display_name="Pro",
        currency="usd",
        unit_amount=2499,
        recurring_interval="month",
        lookup_key="pro_monthly",
        client=client,
        db=db,
    )
    assert result.provisioning_status == "failed"
    assert db.provisioned is None and db.failed is not None
    reason = db.failed["provisioning_error_redacted"]
    assert "price_" not in reason and "sk_" not in reason


def test_provision_missing_price_fails_fast(billing_config):
    client = _FakeStripeClient()
    db = _FakeDB()
    result = prov.provision_catalog_item(
        billing_group_id="bg-1",
        catalog_item_id="bcat-dddddd444444",
        item_type="subscription_plan",
        display_name="NoPrice",
        currency=None,
        unit_amount=None,
        recurring_interval="month",
        lookup_key=None,
        client=client,
        db=db,
    )
    assert result.provisioning_status == "failed"
    assert db.failed is not None
