"""Boundary tests for the assistant's reviewed application tool bridge."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI, Form, Query, Request
from pydantic import BaseModel

from src.assistant.catalog import SKILLS, build_catalog, public_catalog, skill_files
from src.assistant import tools


class _ProjectUpdate(BaseModel):
    name: str
    description: str | None = None


def _register(app, method, path, fn, module, name):
    fn.__name__ = name
    fn.__module__ = f"src.routes.{module}"
    app.add_api_route(path, fn, methods=[method])


@pytest.fixture
def tool_app():
    app = FastAPI()
    app.state.calls = []

    async def read_users(request: Request, limit: int = Query(500, ge=1, le=500), offset: int = 0):
        app.state.calls.append(("read", request.headers.get("authorization"), limit, offset))
        return {"users": [{"user_hash": "u1", "password_hash": "never-expose", "profile": {"api_key": "private-key"}}]}

    async def reset_password(user_hash: str, request: Request, new_password: str = Form(...)):
        app.state.calls.append(("write", user_hash, new_password, request.headers.get("authorization")))
        return {"changed": True, "password": new_password, "detail": f"set password={new_password}"}

    async def update_project(project_hash: str, body: _ProjectUpdate):
        app.state.calls.append(("json", project_hash, body.name))
        return {"project_hash": project_hash, "name": body.name}

    async def tier_map(refresh_catalog: bool = Query(True), limit: int = Query(100, ge=1, le=500)):
        app.state.calls.append(("tier_map", refresh_catalog))
        return {"refreshed": refresh_catalog, "limit": limit}

    async def future_tool():
        raise AssertionError("Unreviewed route must never be invoked")

    _register(app, "GET", "/users/list", read_users, "users", "list_all_users")
    _register(app, "POST", "/users/{user_hash}/reset-password", reset_password, "users", "reset_user_password")
    _register(app, "PUT", "/projects/{project_hash}", update_project, "projects", "update_project_details")
    _register(app, "GET", "/admin/patreon/tier-map", tier_map, "admin_patreon", "list_admin_patreon_tier_map")
    _register(app, "GET", "/users/future-tool", future_tool, "users", "future_tool")
    return app


@pytest.fixture
def boundary(monkeypatch, tool_app):
    auth = AsyncMock()
    monkeypatch.setattr(tools, "_require_live_root", auth)
    settings = {"enabled": True, "enabled_skills": list(SKILLS), "mutations_enabled": False}
    audit = AsyncMock()
    executor = tools.AssistantToolExecutor(tool_app, "root.jwt.session", "root-id", lambda: settings, audit)
    return executor, settings, auth, audit


def test_registry_is_explicit_and_has_complete_request_schemas(tool_app):
    catalog = build_catalog(tool_app)
    assert len(catalog) == 5
    assert not any("future" in name for name in catalog)
    form = catalog["users__reset_user_password"]
    assert form.content_type == "application/x-www-form-urlencoded"
    assert form.input_schema["required"] == ["path", "body"]
    assert "new_password" in form.input_schema["properties"]["body"]["properties"]
    schema = catalog["projects__update_project_details"].input_schema
    assert schema["properties"]["body"]["required"] == ["name"]
    assert "$ref" not in json.dumps(schema)
    assert all(len(tool.name) <= 64 for tool in catalog.values())


def test_catalog_default_reads_and_skills_are_consistent(tool_app):
    catalog = public_catalog(tool_app)
    assert len(catalog["skills"]) == 10
    assert all(tool["default_enabled"] is (not tool["mutates"]) for tool in catalog["tools"])
    for skill in catalog["skills"]:
        assert all(next(tool for tool in catalog["tools"] if tool["id"] == tool_id)["skill"] == skill["id"] for tool_id in skill["tools"])
    assert set(skill_files(["users", "security"])) == {"/skills/users/SKILL.md", "/skills/security/SKILL.md"}
    assert "ask_user" in skill_files(["users"])["/skills/users/SKILL.md"]


@pytest.mark.asyncio
async def test_read_defaults_use_root_session_existing_route_and_limit(boundary, tool_app):
    executor, settings, auth, audit = boundary
    result = await executor.execute("users__list_all_users", {"query": {"offset": 5}})
    assert result["ok"] and result["status"] == 200
    assert tool_app.state.calls == [("read", "Bearer root.jwt.session", 100, 5)]
    auth.assert_awaited_once_with("root.jwt.session", "root-id")
    assert "never-expose" not in json.dumps(result)
    assert "private-key" not in json.dumps(result)
    assert result["data"]["users"][0]["user_hash"] == "u1"
    audit.assert_awaited_once()
    assert "root.jwt.session" not in json.dumps(audit.call_args.args)


@pytest.mark.asyncio
async def test_mutation_requires_both_switch_and_individual_tool(boundary, tool_app):
    executor, settings, auth, audit = boundary
    operation = "users__reset_user_password"
    arguments = {"path": {"user_hash": "u1"}, "body": {"new_password": "strong-never-show"}}
    assert (await executor.execute(operation, arguments))["error"] == "tool_disabled"
    settings["enabled_tools"] = [operation]
    assert (await executor.execute(operation, arguments))["error"] == "mutations_disabled"
    assert not tool_app.state.calls
    settings["mutations_enabled"] = True
    result = await executor.execute(operation, arguments)
    assert result["ok"]
    assert tool_app.state.calls == [("write", "u1", "strong-never-show", "Bearer root.jwt.session")]
    assert "strong-never-show" not in json.dumps(result)
    settings["enabled_tools"] = []
    assert (await executor.execute(operation, arguments))["error"] == "tool_disabled"
    assert len(tool_app.state.calls) == 1


@pytest.mark.asyncio
async def test_disabling_skill_or_assistant_takes_effect_during_session(boundary):
    executor, settings, _, _ = boundary
    settings["enabled_skills"] = ["system"]
    assert (await executor.execute("users__list_all_users"))["error"] == "tool_disabled"
    settings["enabled"] = False
    assert (await executor.execute("users__list_all_users"))["error"] == "assistant_disabled"


@pytest.mark.asyncio
async def test_safe_tier_map_variant_cannot_be_promoted_to_write(boundary, tool_app):
    executor, settings, _, _ = boundary
    result = await executor.execute("admin_patreon__read_tier_map")
    assert result["ok"] and result["data"]["refreshed"] is False
    rejected = await executor.execute("admin_patreon__read_tier_map", {"query": {"refresh_catalog": True}})
    assert rejected["error"] == "invalid_arguments"
    assert (await executor.execute("admin_patreon__list_admin_patreon_tier_map"))["error"] == "tool_disabled"
    assert tool_app.state.calls == [("tier_map", False)]


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["../api-keys", "%2e%2e", "u1/x", "u1?admin=true", "u1#x", "u1\\x", ".."])
async def test_path_parameters_cannot_escape_registered_route(boundary, tool_app, value):
    executor, settings, _, _ = boundary
    settings.update(mutations_enabled=True, enabled_tools=["users__reset_user_password"])
    result = await executor.execute("users__reset_user_password", {"path": {"user_hash": value}, "body": {"new_password": "secret"}})
    assert result["error"] == "invalid_arguments"
    assert not tool_app.state.calls


@pytest.mark.asyncio
async def test_json_schema_uses_endpoint_validation_and_safe_error_outputs(boundary, tool_app):
    executor, settings, _, _ = boundary
    settings.update(mutations_enabled=True, enabled_tools=["projects__update_project_details"])
    operation = "projects__update_project_details"
    result = await executor.execute(operation, {"path": {"project_hash": "p1"}, "body": {"name": "Demo"}})
    assert result["ok"] and tool_app.state.calls == [("json", "p1", "Demo")]
    result = await executor.execute(operation, {"path": {"project_hash": "p1"}, "body": {"description": "missing name", "password": "never-show"}})
    assert result["status"] == 422 and not result["ok"]
    assert "never-show" not in json.dumps(result)
    assert len(tool_app.state.calls) == 1


@pytest.mark.asyncio
async def test_unknown_headers_and_oversized_reads_rejected(boundary, tool_app):
    executor, _, _, _ = boundary
    for args in ({"headers": {"Authorization": "other-session"}}, {"query": {"unknown": 1}}, {"query": {"limit": 501}}):
        assert (await executor.execute("users__list_all_users", args))["error"] == "invalid_arguments"
    assert (await executor.execute("users__future_tool"))["error"] == "unknown_tool"
    assert not tool_app.state.calls


@pytest.mark.asyncio
async def test_session_provider_can_refresh_and_revocation_fails_closed(boundary, tool_app):
    executor, _, auth, _ = boundary
    executor.session_token = lambda: "fresh.root.token"
    await executor.execute("users__list_all_users")
    auth.assert_awaited_once_with("fresh.root.token", "root-id")
    auth.side_effect = PermissionError("Session revoked")
    assert (await executor.execute("users__list_all_users"))["error"] == "root_session_required"
    assert len(tool_app.state.calls) == 1


@pytest.mark.asyncio
async def test_root_guard_checks_current_db_type_not_permission_names(monkeypatch):
    from src.Util.db import db_enhanced, db_users
    validate = Mock(return_value=SimpleNamespace(user_id="u1", user_type="root", permissions=["global_admin"]))
    monkeypatch.setattr(db_enhanced, "validate_session", validate)
    monkeypatch.setattr(db_users, "get_user_type", lambda user_id: "admin")
    with pytest.raises(PermissionError):
        await tools._require_live_root("token", "u1")
    monkeypatch.setattr(db_users, "get_user_type", lambda user_id: "root")
    await tools._require_live_root("token", "u1")
    with pytest.raises(PermissionError):
        await tools._require_live_root("token", "different-user")


def test_redaction_preserves_useful_status_and_scrubs_nested_audit_payloads():
    result = tools.redact({
        "credentials_status": "active", "token_count": 42, "user_hash": "abc",
        "body": '{"access_token":"never-leak","metadata":{"clientSecret":"also-private"}}',
        "message": "Authorization=Bearer abc.def.ghi password=third-secret",
        "items": list(range(105)),
        "credentials": {"value": "nested-private", "status": "configured"},
        "secrets": ["list-private"],
    })
    serialized = json.dumps(result)
    assert "never-leak" not in serialized and "also-private" not in serialized and "third-secret" not in serialized
    assert "nested-private" not in serialized and "list-private" not in serialized
    assert result["credentials"]["status"] == "configured"
    assert result["credentials_status"] == "active" and result["token_count"] == 42
    assert result["items"][-1] == {"_truncated_items": 5}


@pytest.mark.asyncio
async def test_real_patreon_read_switch_skips_catalog_refresh(monkeypatch):
    from src.routes import admin_patreon
    monkeypatch.setattr(admin_patreon, "is_root_user", lambda user_id: True)
    monkeypatch.setattr(admin_patreon, "load_patreon_config", lambda: SimpleNamespace(disabled=False))
    refresh = Mock()
    monkeypatch.setattr(admin_patreon, "ensure_patreon_catalog_safely", refresh)
    monkeypatch.setattr(admin_patreon.db_patreon, "list_patreon_tier_map_admin", lambda **kwargs: ([], 0))
    await admin_patreon.list_admin_patreon_tier_map.__wrapped__(
        refresh_catalog=False, limit=10, offset=0, active=None, credentials=None,
        log_context=SimpleNamespace(user_id="root-id"),
    )
    refresh.assert_not_called()
    await admin_patreon.list_admin_patreon_tier_map.__wrapped__(
        refresh_catalog=True, limit=10, offset=0, active=None, credentials=None,
        log_context=SimpleNamespace(user_id="root-id"),
    )
    refresh.assert_called_once()


def test_real_application_management_routes_have_reviewed_complete_schemas():
    import importlib
    from src.assistant.catalog import REVIEWED_OPERATIONS

    app = FastAPI()
    for module in sorted({entry[0] for entry in REVIEWED_OPERATIONS}):
        app.include_router(importlib.import_module(f"src.routes.{module}").router)
    catalog = build_catalog(app)
    assert len(catalog) == len(REVIEWED_OPERATIONS) + 1
    assert sum(not spec.mutates for spec in catalog.values()) >= 95
    assert len({spec.skill for spec in catalog.values()}) == 10
    assert all("$ref" not in json.dumps(spec.input_schema) for spec in catalog.values())
    assert catalog["audit_logs__export_logs"].input_schema["properties"]["body"]["properties"]["source"]["enum"]
    assert catalog["email_templates__preview_email_template"].mutates is False
    assert catalog["admin_billing__reconcile_catalog"].mutates is False
    assert catalog["admin_billing__sync_catalog"].mutates is True
    assert "projects__transfer_project_ownership" not in catalog
    assert "projects__archive_unarchive_project" not in catalog
    assert catalog["auth__register"].mutates is True
    assert catalog["auth__check_availability"].mutates is False
    assert catalog["admin_patreon__read_tier_map"].fixed_query == (("refresh_catalog", False),)


@pytest.mark.asyncio
async def test_selected_real_read_routes_through_asgi_and_form_preview(monkeypatch):
    from src.routes import auth, system, admin_oauth
    app = FastAPI()
    app.include_router(auth.router)
    app.include_router(system.router)
    app.include_router(admin_oauth.router)
    monkeypatch.setattr(tools, "_require_live_root", AsyncMock())
    root_session = SimpleNamespace(user_id="root-id", user_type="root", permissions=["admin"])
    monkeypatch.setattr(system, "validate_session", lambda token: root_session)
    monkeypatch.setattr(system, "count_users", lambda: 12)
    monkeypatch.setattr(system, "count_projects", lambda: 3)
    monkeypatch.setattr(system, "count_user_groups", lambda: 2)
    monkeypatch.setattr(system, "count_project_permission_groups", lambda: 1)
    monkeypatch.setattr(admin_oauth, "validate_session", lambda token: root_session)
    monkeypatch.setattr(admin_oauth, "is_root_user", lambda user_id: True)
    monkeypatch.setattr(admin_oauth.db_oauth_connections, "list_provider_catalog", lambda: [])
    monkeypatch.setattr(admin_oauth, "load_oauth_settings", lambda: SimpleNamespace(enabled=True))
    monkeypatch.setattr(auth, "check_username_email_available", lambda value: value == "new-user")
    executor = tools.AssistantToolExecutor(app, "root.jwt.session", "root-id", lambda: {"enabled": True})
    info = await executor.execute("system__get_system_info")
    assert info["ok"] and info["data"]["statistics"]["total_users"] == 12
    providers = await executor.execute("admin_oauth__list_providers")
    assert providers["ok"] and providers["data"] == {"success": True, "oauth_enabled": True, "providers": []}
    availability = await executor.execute("auth__check_availability", {"body": {"username": "new-user"}})
    assert availability["ok"] and availability["data"]["username_available"] is True


@pytest.mark.asyncio
async def test_identifiers_cannot_bypass_disabled_tools_by_shadowing_static_routes(monkeypatch):
    app = FastAPI()
    forbidden = Mock()

    async def list_keys():
        forbidden()
        return {"keys": []}

    async def user_detail(user_hash: str):
        return {"user_hash": user_hash}

    _register(app, "GET", "/users/api-keys", list_keys, "user_api_keys", "user_list_api_keys")
    _register(app, "GET", "/users/{user_hash}", user_detail, "users", "get_user_details")
    monkeypatch.setattr(tools, "_require_live_root", AsyncMock())
    executor = tools.AssistantToolExecutor(app, "root-token", "root", lambda: {
        "enabled": True, "enabled_skills": ["users"], "enabled_tools": ["users__get_user_details"],
    })
    result = await executor.execute("users__get_user_details", {"path": {"user_hash": "api-keys"}})
    assert result["error"] == "invalid_arguments"
    forbidden.assert_not_called()
    result = await executor.execute("users__get_user_details", {"path": {"user_hash": "u1"}})
    assert result["ok"] and result["data"]["user_hash"] == "u1"
