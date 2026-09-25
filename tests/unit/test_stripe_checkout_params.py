"""Checkout Session parameters carry the evidence later Stripe events are resolved by."""

from __future__ import annotations

import pytest

from src.Util.billing.provider import BillingCheckoutIntent, BillingProviderPriceRef
from src.Util.stripe.checkout import build_checkout_metadata, build_checkout_session_params


USER_HASH = "usr-5b8c7c1e-7f3a-4d2b-9c61-0a1b2c3d4e5f"
# Real project hashes are secrets.token_hex(32).upper(): 64 hex characters.
PROJECT_HASH = "7CCC926F2F5FEB07C973606EB2DF02BC3607C9C5B80A104DF5AAC9A1991F6173"


def _intent(intent_type: str) -> BillingCheckoutIntent:
    subscription = intent_type == "subscription"
    return BillingCheckoutIntent(
        user_id="usr-1",
        project_id="proj-1",
        user_hash=USER_HASH,
        project_hash=PROJECT_HASH,
        provider="stripe",
        intent_type=intent_type,
        price_ref=BillingProviderPriceRef(ref_type="lookup_key", value="magic_worlds_plus_monthly"),
        quantity=1,
        checkout_ref="bco-0123456789abcdef0123456789abcdef",
        subscription_ref="bsub-0123456789abcdef0123456789abcdef" if subscription else None,
        purchase_ref=None if subscription else "bpur-0123456789abcdef0123456789abcdef",
        plan_code="magic_worlds_plus" if subscription else None,
        tier_code="artisan" if subscription else None,
        credit_product_code=None if subscription else "credits_small",
        success_url="https://app.example.test/billing/success",
        cancel_url="https://app.example.test/billing/cancel",
        safe_metadata={"customer_ref": "bcust-0123456789abcdef0123456789abcdef"},
    )


def test_checkout_metadata_sends_the_real_project_hash_to_stripe():
    """The 64-hex project hash used to be masked to ***FILTERED***, so no event could resolve its project."""

    metadata = build_checkout_metadata(_intent("subscription"))

    assert metadata["project_hash"] == PROJECT_HASH
    assert metadata["user_hash"] == USER_HASH
    assert metadata["api_auth_customer_ref"] == "bcust-0123456789abcdef0123456789abcdef"


def test_subscription_checkout_copies_metadata_onto_the_subscription():
    params = build_checkout_session_params(intent=_intent("subscription"), stripe_customer_id="cus_x", resolved_price_id="price_x")

    assert params["mode"] == "subscription"
    assert params["subscription_data"] == {"metadata": params["metadata"]}
    assert params["subscription_data"]["metadata"]["api_auth_subscription_ref"] == "bsub-0123456789abcdef0123456789abcdef"
    assert "payment_intent_data" not in params


def test_credit_purchase_checkout_copies_metadata_onto_the_payment_intent():
    params = build_checkout_session_params(intent=_intent("credit_purchase"), stripe_customer_id="cus_x", resolved_price_id="price_x")

    assert params["mode"] == "payment"
    assert params["payment_intent_data"] == {"metadata": params["metadata"]}
    assert params["payment_intent_data"]["metadata"]["api_auth_purchase_ref"] == "bpur-0123456789abcdef0123456789abcdef"
    assert "subscription_data" not in params


@pytest.mark.parametrize("intent_type", ["subscription", "credit_purchase"])
def test_copied_metadata_is_a_separate_mapping(intent_type: str):
    params = build_checkout_session_params(intent=_intent(intent_type), stripe_customer_id="cus_x", resolved_price_id="price_x")
    copied = (params.get("subscription_data") or params.get("payment_intent_data"))["metadata"]

    copied["user_hash"] = "changed"

    assert params["metadata"]["user_hash"] == USER_HASH
