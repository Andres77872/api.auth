"""Contract tests for the catalog reconcile/import admin endpoints (pull from Stripe).

ASGI-level (no live DB / Stripe): the per-group client + DB are stubbed via monkeypatch. Verifies
GET /catalog/reconcile is read-only, POST /catalog/sync repairs/writes, POST /catalog/import adopts
selected candidates, and that responses surface fingerprints only — never raw prod_/price_ ids.
"""

from __future__ import annotations

import importlib
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from src.Util.stripe.catalog_sync import (
    CatalogDriftEntry,
    CatalogImportCandidate,
    CatalogReconcileReport,
)


ROUTE_MODULE = "src.routes.admin_billing"


def _route_module():
    return importlib.import_module(ROUTE_MODULE)


@asynccontextmanager
async def _client(module):
    app = FastAPI(title="catalog reconcile contract test")
    app.include_router(module.router)

    async def _billing_admin():
        return SimpleNamespace(user_id="usr-1", permissions=["admin"])

    app.dependency_overrides[module.require_billing_admin] = _billing_admin
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client


def _report() -> CatalogReconcileReport:
    return CatalogReconcileReport(
        in_sync=2,
        missing_ref_repaired=1,
        drift=[
            CatalogDriftEntry(
                item_id="bcat-i3",
                plan_code="plus",
                item_type="subscription_plan",
                drift_kind="amount_mismatch",
                local_unit_amount=111,
                stripe_unit_amount=999,
                price_fingerprint="aaaaaaaaaaaa",
            )
        ],
        candidates=[
            CatalogImportCandidate(
                item_type="subscription_plan",
                plan_code="pro_monthly",
                display_name="Pro",
                currency="usd",
                unit_amount=1999,
                recurring_interval="month",
                lookup_key="pro_monthly",
                product_fingerprint="bbbbbbbbbbbb",
                price_fingerprint="cccccccccccc",
                plan_code_conflict=False,
                product_id="prod_SHOULD_NOT_LEAK",
                price_id="price_SHOULD_NOT_LEAK",
            )
        ],
        synced_at="2026-06-22T00:00:00+00:00",
    )


@pytest.mark.asyncio
async def test_reconcile_is_read_only(monkeypatch):
    module = _route_module()
    captured = {}

    def _reconcile(*, billing_group_id, write):
        captured["write"] = write
        captured["group"] = billing_group_id
        return _report()

    monkeypatch.setattr(module, "_require_group", lambda gh: {"id": "bg-x"})
    monkeypatch.setattr(module.stripe_catalog_sync, "reconcile_catalog_for_group", _reconcile)

    async with _client(module) as client:
        resp = await client.get("/admin/billing/grp_hash/catalog/reconcile")

    assert resp.status_code == 200
    assert captured["write"] is False  # GET reconcile never writes
    body = resp.json()
    assert body["success"] is True
    result = body["result"]
    assert result["in_sync"] == 2 and result["missing_ref_repaired"] == 1
    assert len(result["drift"]) == 1 and result["drift"][0]["drift_kind"] == "amount_mismatch"
    assert len(result["candidates"]) == 1 and result["candidates"][0]["plan_code"] == "pro_monthly"

    # Raw Stripe ids must never surface — fingerprints only.
    serialized = json.dumps(body).lower()
    for sentinel in ("prod_should_not_leak", "price_should_not_leak", "prod_", "ciphertext"):
        assert sentinel not in serialized, f"leaked sentinel: {sentinel}"


@pytest.mark.asyncio
async def test_sync_writes(monkeypatch):
    module = _route_module()
    captured = {}

    def _reconcile(*, billing_group_id, write):
        captured["write"] = write
        return _report()

    monkeypatch.setattr(module, "_require_group", lambda gh: {"id": "bg-x"})
    monkeypatch.setattr(module.stripe_catalog_sync, "reconcile_catalog_for_group", _reconcile)

    async with _client(module) as client:
        resp = await client.post("/admin/billing/grp_hash/catalog/sync")

    assert resp.status_code == 200
    assert captured["write"] is True  # POST sync repairs refs + records status
    assert resp.json()["result"]["missing_ref_repaired"] == 1


@pytest.mark.asyncio
async def test_import_returns_imported_skipped_conflicts(monkeypatch):
    module = _route_module()
    captured = {}

    def _import(*, billing_group_id, selected_price_fingerprints, plan_code_overrides, new_id, new_hash):
        captured["fps"] = selected_price_fingerprints
        captured["overrides"] = plan_code_overrides
        return {"imported": ["pro_monthly"], "skipped": [], "conflicts": ["plus"]}

    monkeypatch.setattr(module, "_require_group", lambda gh: {"id": "bg-x"})
    monkeypatch.setattr(module.stripe_catalog_sync, "import_selected_candidates", _import)

    async with _client(module) as client:
        resp = await client.post(
            "/admin/billing/grp_hash/catalog/import",
            json={"price_fingerprints": ["cccccccccccc", "dddddddddddd"], "plan_code_overrides": {"dddddddddddd": "alt"}},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["imported"] == ["pro_monthly"]
    assert body["conflicts"] == ["plus"]
    assert captured["fps"] == ["cccccccccccc", "dddddddddddd"]
    assert captured["overrides"] == {"dddddddddddd": "alt"}
