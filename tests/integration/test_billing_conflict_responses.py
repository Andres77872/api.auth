"""Regression tests: admin billing conflict paths answer 409, not 500 (no live Stripe / DB).

Both paths built their ``ConflictError`` with ``ErrorCode.CONFLICT``. ``CONFLICT`` is a member of
``ErrorCategory``, not ``ErrorCode``, so evaluating it raised ``AttributeError`` inside the
``except`` block and the client got a generic 500 instead of the conflict it could act on.
The database is stubbed with the real SIGNAL the stored procedures raise.
"""

from __future__ import annotations

import importlib
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import pymysql
import pytest
from fastapi import FastAPI

from src.middleware.error_handler import register_exception_handlers
from src.Util.error_handler import ErrorCode


ROUTE_MODULE = "src.routes.admin_billing"
GROUP_PATH = "/admin/billing/BG_HASH_1"
ATTACH_PATH = f"{GROUP_PATH}/projects"


def _route_module():
    return importlib.import_module(ROUTE_MODULE)


@asynccontextmanager
async def _client(module, monkeypatch):
    error_middleware = importlib.import_module("src.middleware.error_handler")
    monkeypatch.setattr(error_middleware, "log_app_exception_to_db", lambda **_kwargs: None)

    app = FastAPI(title="admin billing conflict contract test")
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


def _signal(message: str):
    def _raise(**_kwargs):
        raise pymysql.err.OperationalError(1644, message)

    return _raise


def _assert_conflict(resp, *, message_fragment: str) -> None:
    assert resp.status_code == 409, resp.text
    error = resp.json()["error"]
    assert error["code"] == ErrorCode.STATE_CONFLICT.value == "CONF_5005"
    assert error["category"] == "conflict"
    # The dashboard recognises this case by its wording (isAttachConflict), not by the code.
    assert message_fragment in error["message"].lower()


@pytest.mark.asyncio
async def test_attaching_a_project_already_attached_to_another_group_is_a_409(monkeypatch):
    module = _route_module()
    monkeypatch.setattr(module, "_require_group", lambda group_hash: {"id": "bg-1"})
    monkeypatch.setattr(module, "get_project_by_hash", lambda project_hash: SimpleNamespace(id="prj-1"))
    monkeypatch.setattr(
        module.db_billing,
        "attach_project_to_billing_group",
        _signal("Project already attached to another billing group"),
    )

    async with _client(module, monkeypatch) as client:
        resp = await client.post(ATTACH_PATH, data={"project_hash": "PRJ_HASH_1"})

    _assert_conflict(resp, message_fragment="already attached to another billing group")


@pytest.mark.asyncio
async def test_deleting_a_group_that_still_has_dependants_is_a_409(monkeypatch):
    module = _route_module()
    monkeypatch.setattr(module, "_require_group", lambda group_hash: {"id": "bg-1"})
    monkeypatch.setattr(
        module.db_billing,
        "delete_billing_group",
        _signal("Cannot delete billing group with active subscriptions"),
    )

    async with _client(module, monkeypatch) as client:
        resp = await client.delete(GROUP_PATH)

    _assert_conflict(resp, message_fragment="active subscriptions")


def test_the_billing_routes_name_only_real_error_codes():
    """``ErrorCode.<NAME>`` with a name the enum lacks only fails when that line finally runs."""
    import re
    from pathlib import Path

    source = Path(_route_module().__file__).read_text(encoding="utf-8")
    unknown = sorted({name for name in re.findall(r"\bErrorCode\.([A-Z][A-Z0-9_]*)\b", source) if not hasattr(ErrorCode, name)})
    assert unknown == []
