"""Contract tests for admin billing group creation provider handling."""

from __future__ import annotations

import importlib
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from src.middleware.error_handler import register_exception_handlers


ROUTE_MODULE = "src.routes.admin_billing"
CREATE_PATH = "/admin/billing"
CAPABILITIES_PATH = "/admin/billing/BG_HASH_1/capabilities"


def _route_module():
    return importlib.import_module(ROUTE_MODULE)


@asynccontextmanager
async def _client(module, monkeypatch):
    error_middleware = importlib.import_module("src.middleware.error_handler")
    monkeypatch.setattr(error_middleware, "log_app_exception_to_db", lambda **_kwargs: None)

    app = FastAPI(title="admin billing create group contract test")
    register_exception_handlers(app)
    app.include_router(module.router)

    async def _billing_admin():
        return SimpleNamespace(user_id="usr-admin", permissions=["admin"])

    app.dependency_overrides[module.require_billing_admin] = _billing_admin
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        yield client


def _group_row(provider: str = "stripe") -> dict[str, object]:
    return {
        "id": "bg-1",
        "billing_group_hash": "BG_HASH_1",
        "name": "Test Group",
        "description": None,
        "owner_id": "usr-admin",
        "provider": provider,
        "status": "active",
        "checkout_enabled": 0,
        "portal_enabled": 0,
        "provisioning_enabled": 0,
        "webhooks_enabled": 0,
        "credential_status": "absent",
        "has_secret_key": 0,
        "has_webhook_secret": 0,
    }


def _ready_group_row(provider: str = "stripe") -> dict[str, object]:
    row = _group_row(provider)
    row.update(
        {
            "credential_status": "active",
            "has_secret_key": 1,
            "checkout_enabled": 0,
            "portal_enabled": 0,
            "provisioning_enabled": 0,
            "webhooks_enabled": 0,
        }
    )
    return row


@pytest.mark.asyncio
async def test_create_group_normalizes_provider_before_insert(monkeypatch):
    module = _route_module()
    captured: dict[str, object] = {}

    monkeypatch.setattr(module.db_billing, "billing_provider_exists", lambda **kwargs: kwargs["provider"] == "stripe")
    monkeypatch.setattr(module.db_billing, "create_billing_group", lambda **kwargs: captured.update(kwargs) or {})
    monkeypatch.setattr(module.db_billing, "get_billing_group_by_hash", lambda **_kwargs: _group_row())

    async with _client(module, monkeypatch) as client:
        resp = await client.post(CREATE_PATH, data={"group_name": "Test Group", "provider": "Stripe"})

    assert resp.status_code == 200
    assert captured["provider"] == "stripe"
    assert resp.json()["billing_group"]["provider"] == "stripe"


@pytest.mark.asyncio
async def test_create_group_rejects_unsupported_provider(monkeypatch):
    module = _route_module()
    async with _client(module, monkeypatch) as client:
        resp = await client.post(CREATE_PATH, data={"group_name": "Test Group", "provider": "paypal"})

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "VAL_3012"


@pytest.mark.asyncio
async def test_create_group_reports_missing_provider_seed(monkeypatch):
    module = _route_module()
    monkeypatch.setattr(module.db_billing, "billing_provider_exists", lambda **_kwargs: False)

    async with _client(module, monkeypatch) as client:
        resp = await client.post(CREATE_PATH, data={"group_name": "Test Group", "provider": "stripe"})

    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "EXT_8200"


@pytest.mark.asyncio
async def test_capability_enable_checkout_requires_active_catalog_price(monkeypatch):
    module = _route_module()
    monkeypatch.setenv("BILLING_ENABLED", "true")
    monkeypatch.setenv("BILLING_CHECKOUT_ENABLED", "true")
    monkeypatch.setenv("STRIPE_BILLING_ENABLED", "true")
    monkeypatch.setenv("STRIPE_CHECKOUT_ENABLED", "true")
    monkeypatch.setattr(module.db_billing, "get_billing_group_by_hash", lambda **_kwargs: _ready_group_row())
    monkeypatch.setattr(module.db_billing, "list_catalog_for_group", lambda **_kwargs: [])

    async with _client(module, monkeypatch) as client:
        resp = await client.put(CAPABILITIES_PATH, json={"checkout_enabled": True})

    assert resp.status_code == 400
    assert "active_catalog_price" in json.dumps(resp.json())


@pytest.mark.asyncio
async def test_capability_disable_is_allowed_without_prerequisites(monkeypatch):
    module = _route_module()
    captured: dict[str, object] = {}
    monkeypatch.setattr(module.db_billing, "get_billing_group_by_hash", lambda **_kwargs: _group_row())
    monkeypatch.setattr(module.db_billing, "set_billing_group_capabilities", lambda **kwargs: captured.update(kwargs) or _group_row())

    async with _client(module, monkeypatch) as client:
        resp = await client.put(CAPABILITIES_PATH, json={"checkout_enabled": False})

    assert resp.status_code == 200
    assert captured["checkout_enabled"] is False
