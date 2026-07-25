"""Unit tests for catalog reconcile + import (pull from Stripe). No live Stripe / DB.

Proves: the HMAC fingerprint JOIN matches local rows to Stripe prices (same kind/secret as
provisioning), drift classification, missing-ref repair, orphan import candidates (with conflict
flag), ownership (no money/plan_code mutation), and the gated path makes no Stripe call.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet

from src.Util.billing.security import hmac_provider_ref, provider_ref_fingerprint
from src.Util.stripe import catalog_sync as cs

HMAC = "unit-test-hmac-secret"


def fp(kind: str, raw_id: str) -> str:
    return provider_ref_fingerprint(digest=hmac_provider_ref(provider="stripe", kind=kind, raw_id=raw_id, secret=HMAC))


def _price(price_id, product_id, name, *, amount, interval="month", lookup_key=None, active=True, metadata=None):
    product = {"id": product_id, "name": name, "metadata": metadata or {}}
    out = {"id": price_id, "product": product, "currency": "usd", "unit_amount": amount, "active": active, "lookup_key": lookup_key}
    if interval:
        out["recurring"] = {"interval": interval}
    return out


def _local(item_id, plan_code, *, amount, interval="month", lookup_key=None, price_fp=None, active=True, status="active"):
    return {
        "id": item_id,
        "plan_code": plan_code,
        "item_type": "subscription_plan" if interval else "credit_package",
        "currency": "usd",
        "unit_amount": amount,
        "recurring_interval": interval,
        "lookup_key": lookup_key,
        "active": active,
        "provisioning_status": status,
        "provider_price_id_fingerprint": price_fp,
        "provider_product_id_fingerprint": None,
        "provider_ref_key_id": "key-test-1",
    }


def test_classify_covers_in_sync_repair_drift_and_orphans():
    prices = [
        _price("price_A", "prod_A", "Plus", amount=999, lookup_key="plus_monthly"),       # in_sync
        _price("price_R", "prod_R", "RepairMe", amount=300, lookup_key="repair_me"),       # repair (by lookup_key)
        _price("price_M", "prod_M", "Mism", amount=999, lookup_key="mism"),                # amount drift
        _price("price_C", "prod_C", "Old", amount=500, lookup_key="old", active=False),    # archived drift
        _price("price_B", "prod_B", "Pro Plan", amount=1999, lookup_key="pro_monthly"),    # orphan -> candidate
        _price("price_E", "prod_E", "Plus Dup", amount=999, lookup_key="plus"),            # orphan, plan_code conflict
    ]
    index = cs.build_stripe_index(prices, HMAC)

    local = [
        _local("i1", "plus", amount=999, lookup_key="plus_monthly", price_fp=fp("price_id", "price_A")),
        _local("i2", "repairme", amount=300, lookup_key="repair_me", price_fp=None),            # missing ref
        _local("i3", "mism", amount=111, lookup_key="mism", price_fp=fp("price_id", "price_M")),  # money differs
        _local("i4", "old", amount=500, lookup_key="old", price_fp=fp("price_id", "price_C")),    # stripe archived
    ]

    result = cs.classify_catalog(local, index)

    assert result.in_sync == 1
    assert [r.item_id for r in result.repairs] == ["i2"]
    drift_kinds = sorted(d.drift_kind for d in result.drift)
    assert drift_kinds == ["amount_mismatch", "price_archived"]

    by_plan = {c.plan_code: c for c in result.candidates}
    assert set(by_plan) == {"pro_monthly", "plus"}
    assert by_plan["pro_monthly"].item_type == "subscription_plan"
    assert by_plan["pro_monthly"].plan_code_conflict is False
    assert by_plan["plus"].plan_code_conflict is True  # collides with active local plan_code "plus"
    # raw ids retained in-memory for Phase B, never part of the serialized money fields
    assert by_plan["pro_monthly"].price_id == "price_B"


# --------------------------------------------------------------------------- orchestrator


class _FakeClient:
    def __init__(self, prices):
        self._prices = prices
        self.calls = 0

    def list_prices(self, *, active=True, expand_product=False, limit=100, max_items=2000):
        self.calls += 1
        return self._prices


class _FakeDB:
    def __init__(self, rows):
        self._rows = rows
        self.adopted = []
        self.status = None

    def list_catalog_refs_for_group(self, *, billing_group_id, include_archived=False):
        return self._rows

    def adopt_catalog_item_refs(self, **kwargs):
        self.adopted.append(kwargs)
        return {"id": kwargs["id"]}

    def set_billing_group_catalog_sync_status(self, **kwargs):
        self.status = kwargs
        return None


@pytest.fixture
def enc(monkeypatch):
    fernet_key = Fernet.generate_key().decode("utf-8")
    cfg = SimpleNamespace(
        provider_ref_encryption_key=fernet_key,
        provider_ref_encryption_key_id="key-test-1",
        id_hmac_secret=HMAC,
        decryption_keys_by_id={"key-test-1": fernet_key},
    )
    monkeypatch.setattr(cs, "load_billing_config", lambda: cfg)
    return cfg


def test_reconcile_gated_when_billing_disabled_makes_no_stripe_call(enc):
    client = _FakeClient([_price("price_A", "prod_A", "Plus", amount=999)])
    report = cs.reconcile_catalog_for_group(
        billing_group_id="bg-1", client=client, db=_FakeDB([]), stripe_config=SimpleNamespace(billing_enabled=False)
    )
    assert report.gated is True
    assert client.calls == 0


def test_reconcile_repairs_missing_ref_and_records_status(enc):
    prices = [
        _price("price_A", "prod_A", "Plus", amount=999, lookup_key="plus_monthly"),
        _price("price_R", "prod_R", "RepairMe", amount=300, lookup_key="repair_me"),
        _price("price_B", "prod_B", "Pro", amount=1999, lookup_key="pro_monthly"),
    ]
    rows = [
        _local("i1", "plus", amount=999, lookup_key="plus_monthly", price_fp=fp("price_id", "price_A")),
        _local("i2", "repairme", amount=300, lookup_key="repair_me", price_fp=None),
    ]
    db = _FakeDB(rows)
    report = cs.reconcile_catalog_for_group(
        billing_group_id="bg-1", client=_FakeClient(prices), db=db, stripe_config=SimpleNamespace(billing_enabled=True)
    )

    assert report.gated is False and report.error is None
    assert report.in_sync == 1
    assert report.missing_ref_repaired == 1
    assert len(db.adopted) == 1 and db.adopted[0]["id"] == "i2"
    assert db.adopted[0]["provider_price_id_fingerprint"] == fp("price_id", "price_R")
    assert [c.plan_code for c in report.candidates] == ["pro_monthly"]
    # status reflects drift (there are import candidates)
    assert db.status["status"] == "drift"


def test_reconcile_read_only_skips_writes(enc):
    prices = [_price("price_R", "prod_R", "RepairMe", amount=300, lookup_key="repair_me")]
    rows = [_local("i2", "repairme", amount=300, lookup_key="repair_me", price_fp=None)]
    db = _FakeDB(rows)
    report = cs.reconcile_catalog_for_group(
        billing_group_id="bg-1", client=_FakeClient(prices), db=db, write=False, stripe_config=SimpleNamespace(billing_enabled=True)
    )
    assert report.missing_ref_repaired == 0
    assert db.adopted == [] and db.status is None
