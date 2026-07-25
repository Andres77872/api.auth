"""Contract tests for the per-project billing catalog listing S2S endpoint.

Verifies bearer auth, project->group->catalog projection, safe-field allow-list (no raw
Stripe ids/ciphertext/fingerprints), opaque ``features`` passthrough, and graceful empty
results for a project with no billing group.
"""

from __future__ import annotations

import importlib
import json
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
from fastapi import FastAPI


ROUTE_MODULE = "src.routes.internal_billing"
S2S_TOKEN = "test-billing-s2s-bearer-token-not-real"
PROJECT_HASH = "prjh_magic_worlds"
CATALOG_PATH = f"/internal/projects/{PROJECT_HASH}/billing/catalog"

# Real leak sentinels: the fixture's fingerprint values + ciphertext/hmac/secret tokens.
# (The safe field name ``provider_price_lookup_key`` legitimately contains "price_", so we
# do not treat bare "price_" as a leak — we assert the actual secret/fingerprint values.)
RAW_SENTINELS = ("abc123abc123", "def456def456", "_ciphertext", "_hmac", "provider_price_id", "secret")

_FIXTURE_ROWS = [
    {
        "project_hash": PROJECT_HASH,
        "billing_group_hash": "BG_HASH_1",
        "provider": "stripe",
        "catalog_item_hash": "CAT_PLUS",
        "item_type": "subscription_plan",
        "plan_code": "plus",
        "tier_code": "plus",
        "tier_name": "Plus",
        "display_name": "Plus",
        "currency": "usd",
        "unit_amount": 999,
        "recurring_interval": "month",
        "lookup_key": "plus_monthly",
        "provider_price_id_fingerprint": "abc123abc123",  # must NOT leak into response
        "features": {"daily_credit_limit": 100},
        "metadata": {},
        "sort_order": 10,
        "active": 1,
    },
    {
        "project_hash": PROJECT_HASH,
        "billing_group_hash": "BG_HASH_1",
        "provider": "stripe",
        "catalog_item_hash": "CAT_PAYG",
        "item_type": "credit_package",
        "plan_code": "payg_100",
        "tier_code": None,
        "tier_name": None,
        "display_name": "100 credits",
        "currency": "usd",
        "unit_amount": 500,
        "recurring_interval": None,
        "lookup_key": "payg_100",
        "provider_price_id_fingerprint": "def456def456",
        "features": {"credits": 100},
        "metadata": {},
        "sort_order": 20,
        "active": 1,
    },
]


def _route_module():
    return importlib.import_module(ROUTE_MODULE)


@asynccontextmanager
async def _client():
    app = FastAPI(title="Catalog listing contract test app")
    app.include_router(_route_module().router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client


def _headers(token: str = S2S_TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "User-Agent": "catalog-listing-contract-test"}


def _assert_no_raw_leaks(payload: Any) -> None:
    serialized = json.dumps(payload, sort_keys=True, default=str).lower()
    leaked = [s for s in RAW_SENTINELS if s in serialized]
    assert leaked == [], f"raw provider internals leaked: {leaked}"


@pytest.mark.asyncio
async def test_catalog_listing_requires_bearer(monkeypatch):
    monkeypatch.setenv("BILLING_ENABLED", "true")
    monkeypatch.setenv("BILLING_S2S_ENABLED", "true")
    monkeypatch.setenv("BILLING_S2S_BEARER_TOKEN", S2S_TOKEN)
    async with _client() as client:
        no_auth = await client.get(CATALOG_PATH, headers={"User-Agent": "x"})
        wrong = await client.get(CATALOG_PATH, headers=_headers("nope"))
    assert no_auth.status_code in {401, 403}
    assert wrong.status_code in {401, 403}


@pytest.mark.asyncio
async def test_catalog_listing_projects_group_catalog(monkeypatch):
    monkeypatch.setenv("BILLING_ENABLED", "true")
    monkeypatch.setenv("BILLING_S2S_ENABLED", "true")
    monkeypatch.setenv("BILLING_S2S_BEARER_TOKEN", S2S_TOKEN)
    route = _route_module()
    monkeypatch.setattr(route, "list_catalog_for_project", lambda **kwargs: list(_FIXTURE_ROWS))
    async with _client() as client:
        resp = await client.get(CATALOG_PATH, headers=_headers())

    assert resp.status_code == 200
    body = resp.json()
    _assert_no_raw_leaks(body)
    assert body["project_hash"] == PROJECT_HASH
    assert body["billing_group_hash"] == "BG_HASH_1"
    assert len(body["subscriptions"]) == 1
    assert len(body["credit_packs"]) == 1

    sub = body["subscriptions"][0]
    assert sub["plan_code"] == "plus"
    assert sub["amount_cents"] == 999
    assert sub["interval"] == "month"
    assert sub["provider_price_lookup_key"] == "plus_monthly"
    assert sub["features"] == {"daily_credit_limit": 100}
    assert "provider_price_id_fingerprint" not in sub  # fingerprint never exposed

    pack = body["credit_packs"][0]
    assert pack["credit_product_code"] == "payg_100"
    assert pack["credits"] == 100
    assert pack["features"] == {"credits": 100}


@pytest.mark.asyncio
async def test_catalog_listing_empty_for_unmapped_project(monkeypatch):
    monkeypatch.setenv("BILLING_ENABLED", "true")
    monkeypatch.setenv("BILLING_S2S_ENABLED", "true")
    monkeypatch.setenv("BILLING_S2S_BEARER_TOKEN", S2S_TOKEN)
    route = _route_module()
    monkeypatch.setattr(route, "list_catalog_for_project", lambda **kwargs: [])
    async with _client() as client:
        resp = await client.get(CATALOG_PATH, headers=_headers())

    assert resp.status_code == 200
    body = resp.json()
    assert body["subscriptions"] == []
    assert body["credit_packs"] == []
    assert body["project_hash"] == PROJECT_HASH
