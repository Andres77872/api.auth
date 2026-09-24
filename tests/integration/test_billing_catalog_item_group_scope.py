"""Regression tests: catalog item routes only act on items of the billing group in the path.

The item routes looked the item up by ``item_hash`` alone, so an admin could address group B's
item through group A's path. A price change then re-provisioned the item on group A's Stripe
account (the path group's credentials) while the row still belonged to group B. No live Stripe
or DB: the DB layer and provisioning are stubbed and every write is recorded.
"""

from __future__ import annotations

import importlib
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from src.Util.admin_scope import AdminScope
from fastapi import FastAPI

from src.middleware.error_handler import register_exception_handlers


ROUTE_MODULE = "src.routes.admin_billing"
GROUP_A = {
    "id": "bg-A",
    "billing_group_hash": "BG_A",
    "name": "Group A",
    "provider": "stripe",
    "status": "active",
    "credential_status": "active",
    "provisioning_enabled": True,
}
ITEM_OF_B = {
    "id": "bcat-B1",
    "catalog_item_hash": "ITEM_B1",
    "billing_group_id": "bg-B",
    "provider": "stripe",
    "item_type": "subscription_plan",
    "plan_code": "plus",
    "display_name": "Plus",
    "currency": "usd",
    "unit_amount": 999,
    "recurring_interval": "month",
    "provisioning_status": "active",
    "active": True,
}
ITEM_PATH = "/admin/billing/BG_A/catalog/ITEM_B1"


def _route_module():
    return importlib.import_module(ROUTE_MODULE)


@asynccontextmanager
async def _client(module, monkeypatch):
    error_middleware = importlib.import_module("src.middleware.error_handler")
    monkeypatch.setattr(error_middleware, "log_app_exception_to_db", lambda **_kwargs: None)

    app = FastAPI(title="admin billing catalog group-scope test")
    register_exception_handlers(app)
    app.include_router(module.router)

    async def _billing_admin():
        return SimpleNamespace(user_id="usr-admin", permissions=["admin"])

    app.dependency_overrides[module.require_billing_admin] = _billing_admin
    # Root billing scope: these tests exercise route behavior, not group ownership.
    app.dependency_overrides[module.require_billing_scope] = lambda: AdminScope(user_id="usr-admin", user_type="root")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        yield client


def _stub_db(monkeypatch, module, *, item: dict[str, Any]) -> list[str]:
    writes: list[str] = []
    monkeypatch.setattr(module.db_billing, "get_billing_group_by_hash", lambda **_: dict(GROUP_A))
    monkeypatch.setattr(module.db_billing, "get_catalog_item_by_hash", lambda **_: dict(item))
    for name in ("update_catalog_item", "archive_catalog_item", "set_catalog_item_active"):
        monkeypatch.setattr(module.db_billing, name, lambda _name=name, **_kwargs: writes.append(_name) or {"id": item["id"]})
    monkeypatch.setattr(module.stripe_provisioning, "provisioning_allowed", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(module.stripe_provisioning, "reprovision_price", lambda **kwargs: writes.append("reprovision_price"))
    return writes


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "form"),
    [
        pytest.param("put", ITEM_PATH, {"amount_cents": "1299"}, id="update-reprices"),
        pytest.param("post", f"{ITEM_PATH}/archive", {"archived": "true"}, id="archive"),
        pytest.param("post", f"{ITEM_PATH}/archive", {"archived": "false"}, id="reactivate"),
        pytest.param("delete", ITEM_PATH, None, id="delete"),
    ],
)
async def test_item_of_another_group_is_404_and_untouched(monkeypatch, method: str, path: str, form: dict | None):
    module = _route_module()
    writes = _stub_db(monkeypatch, module, item=ITEM_OF_B)

    async with _client(module, monkeypatch) as client:
        kwargs = {"data": form} if form is not None else {}
        resp = await getattr(client, method)(path, **kwargs)

    assert resp.status_code == 404, resp.text
    assert resp.json()["error"]["message"] == "Catalog item not found"
    assert writes == [], "an item outside the path group must not be written or re-provisioned"


@pytest.mark.asyncio
async def test_item_of_the_path_group_is_still_updated(monkeypatch):
    module = _route_module()
    writes = _stub_db(monkeypatch, module, item={**ITEM_OF_B, "billing_group_id": "bg-A"})

    async with _client(module, monkeypatch) as client:
        resp = await client.put(ITEM_PATH, data={"amount_cents": "1299"})

    assert resp.status_code == 200, resp.text
    assert writes == ["update_catalog_item", "reprovision_price"]
