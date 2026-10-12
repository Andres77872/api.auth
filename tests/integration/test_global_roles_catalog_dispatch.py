"""Exercise the actual role router's collection/detail dispatch used by the UI."""

from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from src.routes import global_roles


@pytest.mark.asyncio
async def test_static_role_catalogs_and_role_details_dispatch_independently(monkeypatch):
    app = FastAPI()
    app.include_router(global_roles.router)

    async def session():
        return SimpleNamespace(user_hash="operator", user_type="admin")

    app.dependency_overrides[global_roles.require_valid_session] = session
    db = global_roles.global_roles
    monkeypatch.setattr(db, "list_roles", lambda **kwargs: [{"role_hash": "role-1"}])
    monkeypatch.setattr(db, "list_permission_groups", lambda **kwargs: [{"group_hash": "group-1"}])
    monkeypatch.setattr(db, "list_permissions", lambda **kwargs: [{"permission_hash": "permission-1"}])
    requested_hashes = []

    def role_by_hash(role_hash):
        requested_hashes.append(role_hash)
        return {"id": "role-id", "role_hash": role_hash, "role_name": "reader"}

    monkeypatch.setattr(db, "get_role_by_hash", role_by_hash)
    monkeypatch.setattr(db, "get_role_permission_groups", lambda role_id: [])

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        for url, key, expected in (
            ("/roles", "roles", [{"role_hash": "role-1"}]),
            ("/roles/permission-groups", "permission_groups", [{"group_hash": "group-1"}]),
            ("/roles/permissions", "permissions", [{"permission_hash": "permission-1"}]),
        ):
            response = await client.get(url)
            assert response.status_code == 200
            assert response.json()[key] == expected
        assert requested_hashes == []

        response = await client.get("/roles/role-1")
        assert response.status_code == 200
        assert response.json()["role"]["role_hash"] == "role-1"
        assert response.json()["permission_groups"] == []
        assert requested_hashes == ["role-1"]
