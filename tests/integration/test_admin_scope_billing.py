"""Billing admin routes: a non-root admin only manages billing groups it fully owns.

A billing group spans projects and carries a Stripe account. An admin user may view or
manage a group only when every active project attached to it is one of its assigned
projects (an empty group only when it created the group). Consumers get no billing admin
scope, whatever permission names (`admin`, `manage_billing`) their global role carries.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from tests.integration.admin_scope_support import (
    ADMIN, AUTH, CONSUMER_ADMIN, PROJECT_A, PROJECT_B, ROOT, directory, router_client, session_for,
)


pytestmark = pytest.mark.usefixtures("patched_db_error_logger")

BILLING = "src.routes.admin_billing"


def _group(group_hash: str, *, owner_id: str, projects: list, status: str = "active", credential_status: str = "absent"):
    return {
        "id": f"id-{group_hash}", "billing_group_hash": group_hash, "name": group_hash, "description": None,
        "owner_id": owner_id, "provider": "stripe", "status": status, "checkout_enabled": 0, "portal_enabled": 0,
        "provisioning_enabled": 0, "webhooks_enabled": 0, "credential_status": credential_status,
        "has_secret_key": 0, "has_webhook_secret": 0, "_projects": projects,
    }


class FakeBillingDB:
    def __init__(self):
        self.groups = {
            "BG-A": _group("BG-A", owner_id=ROOT.id, projects=[PROJECT_A], credential_status="active"),
            "BG-B": _group("BG-B", owner_id=ADMIN.id, projects=[PROJECT_B]),
            "BG-AB": _group("BG-AB", owner_id=ADMIN.id, projects=[PROJECT_A, PROJECT_B]),
            "BG-EMPTY-MINE": _group("BG-EMPTY-MINE", owner_id=ADMIN.id, projects=[], status="suspended"),
            "BG-EMPTY-ROOT": _group("BG-EMPTY-ROOT", owner_id=ROOT.id, projects=[]),
        }
        self.catalog = {
            "id-BG-A": [{"item_type": "subscription_plan", "provisioning_status": "active", "catalog_item_hash": "I1",
                         "plan_code": "pro", "display_name": "Pro"}],
            "id-BG-B": [{"item_type": "credit_package", "provisioning_status": "failed", "catalog_item_hash": "I2",
                         "plan_code": "credits", "display_name": "Credits"}],
        }
        self.attach_project_to_billing_group = MagicMock(return_value={"project_hash": "ph", "status": "active"})
        self.detach_project_from_billing_group = MagicMock(return_value={"removed": 1})
        self.update_billing_group = MagicMock(return_value={})
        self.get_billing_admin_metrics = MagicMock(return_value={"groups_total": 99})

    def _by_id(self, group_id):
        return next(g for g in self.groups.values() if g["id"] == group_id)

    def get_billing_group_by_hash(self, *, billing_group_hash):
        return self.groups.get(billing_group_hash)

    def list_billing_groups(self, *, search, limit, offset):
        rows = list(self.groups.values())
        return rows[offset:offset + limit], len(rows)

    def list_billing_group_projects(self, *, billing_group_id):
        return [
            {"project_id": p.id, "project_hash": p.project_hash, "project_name": p.project_name, "status": "active"}
            for p in self._by_id(billing_group_id)["_projects"]
        ]

    def list_catalog_for_group(self, *, billing_group_id, include_archived=False):
        return list(self.catalog.get(billing_group_id, []))


@pytest.fixture
def billing_db(monkeypatch):
    import importlib

    module = importlib.import_module(BILLING)
    fake = FakeBillingDB()
    for name in (
        "get_billing_group_by_hash", "list_billing_groups", "list_billing_group_projects", "list_catalog_for_group",
        "attach_project_to_billing_group", "detach_project_from_billing_group", "update_billing_group",
        "get_billing_admin_metrics",
    ):
        monkeypatch.setattr(module.db_billing, name, getattr(fake, name))
    return fake


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "group_hash, expected",
    [("BG-A", 200), ("BG-B", 403), ("BG-AB", 403), ("BG-EMPTY-MINE", 200), ("BG-EMPTY-ROOT", 403)],
)
async def test_admin_reads_only_groups_it_fully_owns(billing_db, group_hash, expected):
    with directory(session_for(ADMIN)):
        async with router_client(BILLING) as client:
            response = await client.get(f"/admin/billing/{group_hash}", headers=AUTH)

    assert response.status_code == expected, response.text


@pytest.mark.asyncio
async def test_admin_cannot_modify_a_group_holding_a_foreign_project(billing_db):
    with directory(session_for(ADMIN)):
        async with router_client(BILLING) as client:
            updated = await client.put("/admin/billing/BG-AB", headers=AUTH, data={"group_name": "mine now"})
            projects = await client.get("/admin/billing/BG-B/projects", headers=AUTH)

    assert updated.status_code == 403, updated.text
    assert projects.status_code == 403, projects.text
    billing_db.update_billing_group.assert_not_called()


@pytest.mark.asyncio
async def test_admin_cannot_attach_or_detach_a_project_it_does_not_administer(billing_db):
    with directory(session_for(ADMIN)):
        async with router_client(BILLING) as client:
            attached = await client.post("/admin/billing/BG-A/projects", headers=AUTH, data={"project_hash": PROJECT_B.project_hash})
            detached = await client.delete(f"/admin/billing/BG-A/projects/{PROJECT_B.project_hash}", headers=AUTH)
            own = await client.post("/admin/billing/BG-EMPTY-MINE/projects", headers=AUTH, data={"project_hash": PROJECT_A.project_hash})

    assert attached.status_code == 403, attached.text
    assert detached.status_code == 403, detached.text
    assert own.status_code == 200, own.text
    billing_db.attach_project_to_billing_group.assert_called_once()
    billing_db.detach_project_from_billing_group.assert_not_called()


@pytest.mark.asyncio
async def test_admin_group_list_and_metrics_cover_only_its_groups(billing_db):
    with directory(session_for(ADMIN)):
        async with router_client(BILLING) as client:
            listed = await client.get("/admin/billing", headers=AUTH)
            metrics = await client.get("/admin/billing/metrics", headers=AUTH)

    assert listed.status_code == 200, listed.text
    assert {g["group_hash"] for g in listed.json()["billing_groups"]} == {"BG-A", "BG-EMPTY-MINE"}
    assert listed.json()["pagination"]["total"] == 2
    assert metrics.status_code == 200, metrics.text
    counts = metrics.json()["metrics"]
    billing_db.get_billing_admin_metrics.assert_not_called()
    assert counts["groups_total"] == 2
    assert counts["groups_active"] == 1 and counts["groups_suspended"] == 1
    assert counts["credentials_active"] == 1 and counts["credentials_absent"] == 1
    assert counts["subscription_plans"] == 1 and counts["catalog_active"] == 1
    assert counts["credit_packages"] == 0 and counts["catalog_failed"] == 0
    assert counts["projects_mapped"] == 1


@pytest.mark.asyncio
async def test_root_keeps_global_billing_access(billing_db):
    with directory(session_for(ROOT)):
        async with router_client(BILLING) as client:
            listed = await client.get("/admin/billing", headers=AUTH)
            metrics = await client.get("/admin/billing/metrics", headers=AUTH)
            foreign = await client.get("/admin/billing/BG-AB", headers=AUTH)

    assert len(listed.json()["billing_groups"]) == 5
    assert metrics.json()["metrics"]["groups_total"] == 99
    assert foreign.status_code == 200, foreign.text


@pytest.mark.asyncio
async def test_consumer_permission_names_grant_no_billing_scope(billing_db):
    with directory(session_for(CONSUMER_ADMIN)):
        async with router_client(BILLING) as client:
            listed = await client.get("/admin/billing", headers=AUTH)
            read = await client.get("/admin/billing/BG-A", headers=AUTH)
            created = await client.post("/admin/billing", headers=AUTH, data={"group_name": "x"})

    assert listed.status_code == 403, listed.text
    assert read.status_code == 403, read.text
    assert created.status_code == 403, created.text
