"""HTTP-level regression tests for the ROOT email-template admin router.

``src/routes/email_templates.py`` uses ``from __future__ import annotations`` and
wraps every handler in ``log_and_handle_errors``. FastAPI used to resolve the
string annotations against the decorator module, so the request models became
unresolved ForwardRefs: bodies were parsed as query params and ``/openapi.json``
crashed. These tests drive the router over HTTP with the documented flat JSON
bodies (docs/USAGE/email/reference.md) and build the full app's OpenAPI schema.
"""

from __future__ import annotations

from contextlib import ExitStack
from typing import AsyncIterator
from unittest.mock import patch

import httpx
import pytest
from fastapi import FastAPI

from src.Util.email.templates import TEMPLATES
from src.middleware.error_handler import register_exception_handlers
from src.routes import email_templates


AUTH_HEADERS = {"Authorization": "Bearer test-root-session"}


class _Session:
    user_id = "root-user"
    user_hash = "usr-root"
    username = "root"


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(email_templates.router)

    with ExitStack() as stack:
        stack.enter_context(patch("src.Util.decorators.validate_session", return_value=_Session()))
        stack.enter_context(patch.object(email_templates, "is_root_user", lambda user_id: True))
        stack.enter_context(patch.object(email_templates, "_audit", lambda *args, **kwargs: None))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as test_client:
            yield test_client


@pytest.mark.asyncio
async def test_create_accepts_flat_json_body(client, monkeypatch):
    captured = {}

    def create_dynamic_template(**kwargs):
        captured.update(kwargs)
        return {"version": 1, "revision": 1}

    monkeypatch.setattr(email_templates.db_email_templates, "create_dynamic_template", create_dynamic_template)

    resp = await client.post(
        "/admin/email-templates",
        headers=AUTH_HEADERS,
        json={
            "template_code": "ops_incident_notice",
            "purpose": "delivery_operation",
            "allowed_variables": ["notice", "ticket_id"],
            "required_variables": ["notice"],
            "subject_template": "Notice $ticket_id",
            "html_template": "<p>$notice</p>",
            "text_template": "$notice",
        },
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["template_code"] == "ops_incident_notice"
    assert captured["template_code"] == "ops_incident_notice"
    assert captured["allowed_variables"] == ("notice", "ticket_id")


@pytest.mark.asyncio
async def test_preview_accepts_flat_draft_and_empty_body(client, monkeypatch):
    monkeypatch.setattr(
        email_templates,
        "_load_template",
        lambda code, allow_disabled=False: TEMPLATES["email_activation"],
    )

    draft = await client.post(
        "/admin/email-templates/email_activation/preview",
        headers=AUTH_HEADERS,
        json={
            "subject_template": "Draft subject",
            "html_template": '<p><a href="$activation_link">Activate</a></p>',
            "text_template": "Activate: $activation_link",
        },
    )
    assert draft.status_code == 200, draft.text
    assert draft.json()["subject"] == "Draft subject"

    active = await client.post("/admin/email-templates/email_activation/preview", headers=AUTH_HEADERS)
    assert active.status_code == 200, active.text
    assert active.json()["subject"] != "Draft subject"


def test_app_openapi_uses_flat_email_template_bodies(app):
    app.openapi_schema = None
    schema = app.openapi()

    create = schema["paths"]["/admin/email-templates"]["post"]
    assert "parameters" not in create
    body_schema = create["requestBody"]["content"]["application/json"]["schema"]
    assert body_schema == {"$ref": "#/components/schemas/TemplateCreateRequest"}

    for path, operations in schema["paths"].items():
        if path.startswith("/admin/email-templates"):
            for operation in operations.values():
                assert "log_context" not in str(operation.get("requestBody", {}))
                assert all(param["in"] == "path" for param in operation.get("parameters", []))
