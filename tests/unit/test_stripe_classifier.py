"""RED unit contracts for Stripe event classification/status normalization.

Trace: `.dev/sdd/changes/provider-agnostic-billing-stripe/tasks.md` task 2.5.
"""

from __future__ import annotations

import copy
import importlib
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[2]
WEBHOOK_ROOT = ROOT / "tests" / "fixtures" / "stripe" / "webhooks"
CLASSIFIER_MODULE = "src.Util.stripe.classifier"

SUBSCRIPTION_STATUSES = {"free", "pending", "incomplete", "trialing", "active", "past_due", "unpaid", "paused", "canceled", "former", "stale", "unknown"}
PURCHASE_STATUSES = {"pending", "paid", "refunded", "partially_refunded", "disputed", "dispute_won", "dispute_lost", "stale", "unknown"}


def _future_classifier_module() -> ModuleType:
    try:
        return importlib.import_module(CLASSIFIER_MODULE)
    except ModuleNotFoundError as exc:
        if exc.name and CLASSIFIER_MODULE.startswith(exc.name):
            pytest.fail(f"missing implementation module: {CLASSIFIER_MODULE}; Phase 6.9 must classify approved Stripe events", pytrace=False)
        pytest.fail(f"{CLASSIFIER_MODULE} import failed due to missing dependency: {exc.name}", pytrace=False)


def _event(filename: str) -> dict[str, Any]:
    return json.loads((WEBHOOK_ROOT / filename).read_text(encoding="utf-8"))


def _classify(module: ModuleType, event: dict[str, Any]) -> Any:
    last_error: TypeError | None = None
    for name in ("classify_stripe_event", "classify_event", "classify_webhook_event"):
        func = getattr(module, name, None)
        if not callable(func):
            continue
        for kwargs in ({"event": event}, {"stripe_event": event}, {"payload": event}):
            try:
                return func(**kwargs)
            except TypeError as exc:
                last_error = exc
                continue
    detail = f"; last TypeError: {last_error}" if last_error else ""
    pytest.fail(f"expected Stripe classifier callable{detail}", pytrace=False)


def _status(result: Any, *names: str) -> str | None:
    if isinstance(result, dict):
        for name in names:
            if name in result:
                return result[name]
            if isinstance(result.get("billing"), dict) and name in result["billing"]:
                return result["billing"][name]
            if isinstance(result.get("purchase"), dict) and name in result["purchase"]:
                return result["purchase"][name]
    for name in names:
        if hasattr(result, name):
            return getattr(result, name)
        child = getattr(result, "billing", None) or getattr(result, "purchase", None)
        if child is not None and hasattr(child, name):
            return getattr(child, name)
    return None


@pytest.mark.parametrize(
    ("filename", "expected_status"),
    [
        ("checkout_session_completed_subscription.json", "pending"),
        ("customer_subscription_created.json", "trialing"),
        ("customer_subscription_updated.json", "active"),
        ("customer_subscription_deleted.json", "canceled"),
        ("invoice_paid.json", "active"),
        ("invoice_payment_failed.json", "past_due"),
    ],
)
def test_approved_subscription_events_normalize_to_subscription_vocabulary(filename: str, expected_status: str):
    module = _future_classifier_module()
    result = _classify(module, _event(filename))
    status = _status(result, "subscription_status", "billing_status", "status")
    assert status == expected_status
    assert status in SUBSCRIPTION_STATUSES


@pytest.mark.parametrize(
    ("filename", "expected_status"),
    [
        ("checkout_session_completed_payment.json", "paid"),
        ("charge_refunded.json", "refunded"),
        ("charge_dispute_created.json", "disputed"),
        ("charge_dispute_closed.json", "dispute_won"),
    ],
)
def test_approved_purchase_events_normalize_to_purchase_vocabulary(filename: str, expected_status: str):
    module = _future_classifier_module()
    result = _classify(module, _event(filename))
    status = _status(result, "purchase_status", "status")
    assert status == expected_status
    assert status in PURCHASE_STATUSES


def test_partial_refund_normalizes_to_partially_refunded_without_credit_ledger_side_effect():
    module = _future_classifier_module()
    event = _event("charge_refunded.json")
    event = copy.deepcopy(event)
    event["data"]["object"]["amount_refunded"] = 200
    event["data"]["object"]["refunded"] = False

    result = _classify(module, event)
    status = _status(result, "purchase_status", "status")
    serialized = json.dumps(result, default=str).lower()
    assert status == "partially_refunded"
    assert "credit_ledger" not in serialized
    assert "delta_credits" not in serialized


def test_valid_unsupported_event_is_ignored_noop_without_mutation():
    module = _future_classifier_module()
    result = _classify(module, _event("unsupported_customer_updated.json"))
    serialized = json.dumps(result, default=str).lower()
    assert "ignored" in serialized or "unsupported" in serialized or "noop" in serialized
    assert "mutation" not in serialized or "no_mutation" in serialized


def test_label_or_price_evidence_mismatch_fails_closed_to_unknown_or_stale():
    module = _future_classifier_module()
    event = _event("customer_subscription_updated.json")
    event = copy.deepcopy(event)
    event["data"]["object"]["metadata"]["plan_code"] = "magic_worlds_plus"
    event["data"]["object"]["items"]["data"][0]["price"]["lookup_key"] = "different_product_evidence"

    result = _classify(module, event)
    status = _status(result, "subscription_status", "billing_status", "status")
    assert status in {"unknown", "stale"}
