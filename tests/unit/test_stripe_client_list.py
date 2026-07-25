"""Unit tests for the StripeBillingClient native list reads (catalog pull).

Fakes the underlying ``stripe.StripeClient`` so we exercise the wrapper's auto-pagination,
param building, max_items cap, and error redaction without a live Stripe account.
"""

from __future__ import annotations

import pytest

from src.Util.stripe.client import StripeBillingClient, StripeAPIError


class _FakeList:
    def __init__(self, items):
        self._items = items

    def auto_paging_iter(self):
        return iter(self._items)


class _FakeResource:
    def __init__(self, items, *, raise_exc=None):
        self._items = items
        self._raise = raise_exc
        self.calls = []

    def list(self, params=None, *, options=None):
        self.calls.append((params, options))
        if self._raise is not None:
            raise self._raise
        return _FakeList(self._items)


class _FakeV1:
    def __init__(self, products=None, prices=None):
        self.products = products
        self.prices = prices


class _FakeSDKClient:
    def __init__(self, v1):
        self.v1 = v1


def _client(*, products=None, prices=None) -> StripeBillingClient:
    sdk = _FakeSDKClient(_FakeV1(products=products, prices=prices))
    return StripeBillingClient(secret_key="sk_test_x", stripe_client=sdk)


def test_list_products_pages_and_maps():
    products = _FakeResource([{"id": "prod_1", "name": "A"}, {"id": "prod_2", "name": "B"}])
    client = _client(products=products)

    out = client.list_products(active=True, limit=50)

    assert [p["id"] for p in out] == ["prod_1", "prod_2"]
    params, options = products.calls[0]
    assert params == {"limit": 50, "active": True}
    assert "stripe_version" in options


def test_list_prices_expand_and_active_none_omits_active():
    prices = _FakeResource([{"id": "price_1", "product": {"id": "prod_1"}}])
    client = _client(prices=prices)

    out = client.list_prices(active=None, expand_product=True, limit=10)

    assert out[0]["id"] == "price_1"
    params, _ = prices.calls[0]
    assert params == {"limit": 10, "expand": ["data.product"]}  # active omitted when None


def test_list_honors_max_items_cap():
    products = _FakeResource([{"id": f"prod_{i}"} for i in range(10)])
    client = _client(products=products)

    out = client.list_products(max_items=3)

    assert len(out) == 3


def test_list_errors_are_redacted():
    boom = RuntimeError("boom sk_live_should_not_leak")
    products = _FakeResource([], raise_exc=boom)
    client = _client(products=products)

    with pytest.raises(StripeAPIError) as exc_info:
        client.list_products()

    assert "sk_live_should_not_leak" not in str(exc_info.value)
