"""Contract tests for the admin billing metrics aggregate endpoint.

Verifies ``GET /admin/billing/metrics`` returns the aggregate counts row, that the literal
``metrics`` path is routed to the metrics handler (not captured as a ``{group_hash}``), and
that the response carries counts only — never secrets/ciphertext/fingerprints.
"""

from __future__ import annotations

import importlib
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI


ROUTE_MODULE = "src.routes.admin_billing"
METRICS_PATH = "/admin/billing/metrics"

_FIXTURE = {
    "groups_total": 3,
    "groups_active": 2,
    "groups_suspended": 1,
    "groups_archived": 0,
    "credentials_active": 1,
    "credentials_absent": 2,
    "credentials_rotating": 0,
    "credentials_revoked": 0,
    "subscription_plans": 4,
    "credit_packages": 3,
    "catalog_active": 5,
    "catalog_pending": 2,
    "catalog_failed": 1,
    "catalog_archived": 0,
    "projects_mapped": 6,
}


def _route_module():
    return importlib.import_module(ROUTE_MODULE)


@asynccontextmanager
async def _client(module):
    app = FastAPI(title="admin billing metrics contract test")
    app.include_router(module.router)

    async def _billing_admin():
        return SimpleNamespace(user_id="usr-1", permissions=["admin"])

    app.dependency_overrides[module.require_billing_admin] = _billing_admin
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_admin_metrics_returns_counts(monkeypatch):
    module = _route_module()
    monkeypatch.setattr(module.db_billing, "get_billing_admin_metrics", lambda: dict(_FIXTURE))
    async with _client(module) as client:
        resp = await client.get(METRICS_PATH)

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    metrics = body["metrics"]
    assert metrics["groups_total"] == 3
    assert metrics["groups_active"] == 2
    assert metrics["subscription_plans"] == 4
    assert metrics["credit_packages"] == 3
    assert metrics["catalog_failed"] == 1
    assert metrics["projects_mapped"] == 6

    # The schema deliberately has count names mentioning webhook-secret
    # readiness. Prove the stronger property: every emitted metric is an integer,
    # so no credential, ciphertext, provider ID, or fingerprint can be returned.
    assert metrics
    assert all(type(value) is int for value in metrics.values())


@pytest.mark.asyncio
async def test_metrics_path_not_captured_as_group(monkeypatch):
    module = _route_module()
    called = {"metrics": False, "group": False}

    def _metrics():
        called["metrics"] = True
        return dict(_FIXTURE)

    def _group(**_kwargs):
        called["group"] = True
        return {"id": "bg-x"}

    monkeypatch.setattr(module.db_billing, "get_billing_admin_metrics", _metrics)
    monkeypatch.setattr(module.db_billing, "get_billing_group_by_hash", _group)
    async with _client(module) as client:
        resp = await client.get(METRICS_PATH)

    assert resp.status_code == 200
    assert called["metrics"] is True
    assert called["group"] is False  # /{group_hash} must NOT swallow /metrics


@pytest.mark.asyncio
async def test_admin_metrics_degrades_to_zero_when_db_empty(monkeypatch):
    module = _route_module()
    monkeypatch.setattr(module.db_billing, "get_billing_admin_metrics", lambda: None)
    async with _client(module) as client:
        resp = await client.get(METRICS_PATH)

    assert resp.status_code == 200
    metrics = resp.json()["metrics"]
    assert metrics["groups_total"] == 0
    assert metrics["subscription_plans"] == 0
