"""Unit tests for DB-managed, safely-rendered transactional email templates.

Covers the security-critical core: the string.Template engine (no SSTI), the
placeholder allowlist, the DB→in-code resolver fallback, the single render
funnel (preview == prod), and the admin save-time validator.
"""

from __future__ import annotations

import pytest

from src.Util.email import mailpit
from src.Util.email.templates import (
    EmailTemplateDisabled,
    EmailTemplateError,
    EmailTemplateLookupError,
    TEMPLATES,
    TransactionalEmailTemplate,
    allowed_variables,
    render_email_template,
    render_template_parts,
    render_transactional_template,
    resolve_template,
    sample_variables,
)
from src.Util.error_handler import ValidationError
from src.Util.email.template_validation import (
    TemplateValidationError,
    validate_html_body,
    validate_template_draft,
)


ACTIVATION_LINK = "https://app.example.com/auth/email/verify?token=lookupabcdef0123.secretabcdef0123456"


def _catalog_row(code: str, **overrides):
    tpl = TEMPLATES[code]
    row = {
        "template_code": code,
        "purpose": tpl.purpose,
        "allowed_variables": sorted(allowed_variables(code)),
        "required_variables": list(tpl.required_variables),
        "is_builtin": True,
        "is_enabled": True,
        "revision": 3,
        "version": 7,
        "subject_template": tpl.subject_template,
        "html_template": tpl.html_template,
        "text_template": tpl.text_template,
        "is_active": 1,
    }
    row.update(overrides)
    return row


# --------------------------------------------------------------------------- #
# Engine: rendering, best-practice markup, token extractability
# --------------------------------------------------------------------------- #
def test_activation_renders_with_best_practice_markup():
    rendered = render_email_template("email_activation", {"activation_link": ACTIVATION_LINK})
    assert "Activate" in rendered.subject
    assert "<!DOCTYPE html>" in rendered.html
    assert 'role="presentation"' in rendered.html
    assert "prefers-color-scheme" in rendered.html
    assert "color-scheme" in rendered.html
    # required link is escaped but intact; sensitive var redacted for logs
    assert ACTIVATION_LINK in rendered.html
    assert rendered.redaction_safe_variables.get("activation_link") == "[REDACTED]"


@pytest.mark.parametrize("code", sorted(TEMPLATES))
def test_every_template_renders_with_sample_data(code):
    rendered = render_email_template(code, sample_variables(code))
    assert rendered.subject
    assert "<!DOCTYPE html>" in rendered.html
    assert rendered.text


def test_activation_link_is_extractable_like_e2e():
    # The mailpit e2e gate extracts the token from rendered HTML/text; the new
    # engine + upgraded HTML must keep it matchable.
    rendered = render_email_template("email_activation", {"activation_link": ACTIVATION_LINK})
    for part in (rendered.html, rendered.text):
        assert mailpit.TOKEN_RE.search(part) or mailpit.BARE_SPLIT_TOKEN_RE.search(part)


# --------------------------------------------------------------------------- #
# SSTI / injection: format-style and attribute access must be inert
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "evil_html",
    [
        "<p>$app_name {0.__class__.__mro__}</p>",          # str.format payload -> literal
        "<p>$app_name {activation_link.__globals__}</p>",  # format attr access -> literal
        "<p>$app_name {{7*7}}</p>",                        # jinja-ish -> literal
        "<p>$app_name $activation_link.__class__</p>",     # dotted $ -> attr stays literal
    ],
)
def test_format_style_payloads_are_inert(monkeypatch, evil_html):
    # Simulate an admin-authored body flowing through the real funnel.
    tpl = TransactionalEmailTemplate(
        code="email_activation",
        purpose="email_activation",
        subject_template="Activate your $app_name email",
        html_template=evil_html,
        text_template="$activation_link",
        required_variables=("activation_link",),
    )
    rendered = render_template_parts(tpl, {"activation_link": ACTIVATION_LINK, "app_name": "Magic Auth"})
    # No evaluation happened: no python type/class repr leaked into output.
    assert "<class" not in rendered.html
    assert "__main__" not in rendered.html
    assert "function" not in rendered.html
    # Braces / dotted access remain literal text.
    assert ("{" in rendered.html) or (".__class__" in rendered.html)


def test_unknown_placeholder_rejected():
    tpl = TransactionalEmailTemplate(
        code="email_activation",
        purpose="email_activation",
        subject_template="$evil",
        html_template="$activation_link",
        text_template="$activation_link",
        required_variables=("activation_link",),
    )
    with pytest.raises(EmailTemplateError):
        render_template_parts(tpl, {"activation_link": ACTIVATION_LINK})


def test_missing_required_variable_raises():
    with pytest.raises(EmailTemplateError):
        render_email_template("email_activation", {})  # no activation_link


# --------------------------------------------------------------------------- #
# Resolver: DB active version vs in-code fallback (resilience)
# --------------------------------------------------------------------------- #
def test_resolver_uses_db_active_version(monkeypatch):
    from src.Util.db import db_email_templates

    row = _catalog_row(
        "email_activation",
        subject_template="Custom $app_name activation",
        revision=9,
    )
    monkeypatch.setattr(db_email_templates, "get_active_template", lambda code: row)
    resolved = resolve_template("email_activation")
    assert resolved.source == "db"
    assert resolved.version == 7
    assert resolved.revision == 9
    assert "Custom" in resolved.subject_template

    rendered = render_transactional_template("email_activation", {"activation_link": ACTIVATION_LINK})
    assert rendered.headers.get("X-Template-Version") == "7"
    assert rendered.headers.get("X-Template-Revision") == "9"


def test_resolver_falls_back_when_db_empty(monkeypatch):
    from src.Util.db import db_email_templates

    monkeypatch.setattr(db_email_templates, "get_active_template", lambda code: None)
    resolved = resolve_template("email_activation")
    assert resolved.source == "code"
    assert resolved.version is None


def test_resolver_falls_back_on_db_error(monkeypatch):
    from src.Util.db import db_email_templates

    def boom(code):
        raise RuntimeError("db down")

    monkeypatch.setattr(db_email_templates, "get_active_template", boom)
    # Must NOT raise into the render path — delivery cannot depend on the table.
    resolved = resolve_template("email_activation")
    assert resolved.source == "code"
    rendered = render_email_template("email_activation", {"activation_link": ACTIVATION_LINK})
    assert "Activate" in rendered.subject


def test_resolver_raises_retryable_lookup_error_in_worker_mode(monkeypatch):
    from src.Util.db import db_email_templates

    def boom(code):
        raise RuntimeError("db down")

    monkeypatch.setattr(db_email_templates, "get_active_template", boom)
    with pytest.raises(EmailTemplateLookupError):
        resolve_template("email_activation", fail_closed_on_db_error=True)


def test_invalid_db_row_falls_back(monkeypatch):
    from src.Util.db import db_email_templates

    monkeypatch.setattr(
        db_email_templates,
        "get_active_template",
        lambda code: {"version": 3, "subject_template": "", "html_template": "", "text_template": ""},
    )
    resolved = resolve_template("email_activation")
    assert resolved.source == "code"


def test_dynamic_enabled_template_resolves_and_renders(monkeypatch):
    from src.Util.db import db_email_templates

    row = {
        "template_code": "ops_notice",
        "purpose": "delivery_operation",
        "allowed_variables": ["notice"],
        "required_variables": ["notice"],
        "is_builtin": False,
        "is_enabled": True,
        "revision": 12,
        "version": 4,
        "subject_template": "Notice $notice",
        "html_template": "<p>$notice</p>",
        "text_template": "$notice",
        "is_active": 1,
    }
    monkeypatch.setattr(db_email_templates, "get_active_template", lambda code: row)

    rendered = render_email_template(
        "ops_notice",
        {"notice": "Template update"},
        fail_closed_on_db_error=True,
    )

    assert rendered.subject == "Notice Template update"
    assert rendered.headers["X-Template-Version"] == "4"
    assert rendered.headers["X-Template-Revision"] == "12"


def test_disabled_template_raises_disabled_even_if_body_is_invalid(monkeypatch):
    from src.Util.db import db_email_templates

    row = _catalog_row(
        "email_activation",
        is_enabled=False,
        subject_template="",
        html_template="",
        text_template="",
    )
    monkeypatch.setattr(db_email_templates, "get_active_template", lambda code: row)

    with pytest.raises(EmailTemplateDisabled):
        resolve_template("email_activation", fail_closed_on_db_error=True)

    disabled = resolve_template("email_activation", fail_closed_on_db_error=True, allow_disabled=True)
    assert disabled.is_enabled is False
    assert disabled.source == "code"


def test_invalid_db_row_dead_letters_in_worker_mode(monkeypatch):
    from src.Util.db import db_email_templates

    monkeypatch.setattr(
        db_email_templates,
        "get_active_template",
        lambda code: _catalog_row(
            "email_activation",
            version=3,
            subject_template="Custom",
            html_template="<p>No activation link</p>",
            text_template="No activation link",
        ),
    )

    with pytest.raises(EmailTemplateError):
        resolve_template("email_activation", fail_closed_on_db_error=True)


# --------------------------------------------------------------------------- #
# Single render funnel: preview == prod
# --------------------------------------------------------------------------- #
def test_preview_matches_worker_render(monkeypatch):
    from src.Util.db import db_email_templates

    monkeypatch.setattr(db_email_templates, "get_active_template", lambda code: None)
    variables = sample_variables("password_reset")
    worker = render_transactional_template("password_reset", variables)
    template = resolve_template("password_reset")
    preview = render_template_parts(template, variables)
    assert preview.html == worker.html
    assert preview.subject == worker.subject
    assert preview.text == worker.text


# --------------------------------------------------------------------------- #
# Save-time validation
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("code", sorted(TEMPLATES))
def test_all_default_templates_validate(code):
    tpl = TEMPLATES[code]
    summary = validate_template_draft(
        template_code=code,
        subject_template=tpl.subject_template,
        html_template=tpl.html_template,
        text_template=tpl.text_template,
    )
    assert set(tpl.required_variables).issubset(set(summary["used_variables"]))
    assert summary["allowed_variables"] == sorted(allowed_variables(code))


def _activation_draft(**overrides):
    base = dict(
        template_code="email_activation",
        subject_template="Activate your $app_name email",
        html_template=TEMPLATES["email_activation"].html_template,
        text_template="$activation_link",
    )
    base.update(overrides)
    return base


@pytest.mark.parametrize(
    "label, overrides",
    [
        ("script", {"html_template": "<p>$activation_link</p><script>alert(1)</script>"}),
        ("event handler", {"html_template": '<p onclick="x()">$activation_link</p>'}),
        ("javascript url", {"html_template": '<a href="javascript:alert(1)">$activation_link</a>'}),
        ("data url", {"html_template": '<img src="data:text/html,x">$activation_link'}),
        ("iframe", {"html_template": '<iframe src="https://x"></iframe>$activation_link'}),
        ("meta refresh", {"html_template": '<meta http-equiv="refresh" content="0">$activation_link'}),
        ("css expression", {"html_template": '<p style="x:expression(alert(1))">$activation_link</p>'}),
        ("unknown var", {"subject_template": "$evil"}),
        ("missing required", {"html_template": "<p>hi $app_name</p>", "text_template": "hi $app_name"}),
        ("multiline subject", {"subject_template": "a\nb $app_name"}),
    ],
)
def test_validator_rejects(label, overrides):
    with pytest.raises(TemplateValidationError):
        validate_template_draft(**_activation_draft(**overrides))


def test_validator_accepts_reasonable_edit():
    html = TEMPLATES["email_activation"].html_template.replace("Activate email", "Confirm your email")
    summary = validate_template_draft(**_activation_draft(html_template=html))
    assert "activation_link" in summary["used_variables"]


def test_validate_html_body_allows_structure():
    # The full best-practice document must pass the HTML guard unchanged.
    validate_html_body(TEMPLATES["email_activation"].html_template)


def test_dynamic_validator_uses_catalog_allowlist_and_required_vars():
    summary = validate_template_draft(
        template_code="ops_notice",
        purpose="delivery_operation",
        allowed_variable_names=("notice", "ticket_id"),
        required_variable_names=("notice",),
        subject_template="Notice $ticket_id",
        html_template="<p>$notice</p>",
        text_template="$notice",
    )

    assert summary["used_variables"] == ["notice", "ticket_id"]
    assert summary["required_variables"] == ["notice"]


def test_dynamic_validator_rejects_required_var_outside_allowlist():
    with pytest.raises(TemplateValidationError):
        validate_template_draft(
            template_code="ops_notice",
            purpose="delivery_operation",
            allowed_variable_names=("notice",),
            required_variable_names=("ticket_id",),
            subject_template="Notice",
            html_template="<p>$notice</p>",
            text_template="$notice",
        )


def test_dynamic_validator_allows_static_template_with_empty_variable_lists():
    summary = validate_template_draft(
        template_code="ops_static_notice",
        purpose="delivery_operation",
        allowed_variable_names=(),
        required_variable_names=(),
        subject_template="Static notice",
        html_template="<p>Static notice</p>",
        text_template="Static notice",
    )

    assert summary["used_variables"] == []
    assert summary["allowed_variables"] == []
    assert summary["required_variables"] == []


@pytest.mark.asyncio
async def test_route_create_dynamic_template_rejects_non_internal_purpose(monkeypatch):
    from src.routes import email_templates as route

    monkeypatch.setattr(route, "is_root_user", lambda user_id: True)
    body = route.TemplateCreateRequest(
        template_code="customer_reset_notice",
        purpose="password_reset",
        allowed_variables=["reset_link"],
        required_variables=["reset_link"],
        subject_template="Reset",
        html_template='<p><a href="$reset_link">Reset</a></p>',
        text_template="$reset_link",
    )

    with pytest.raises(ValidationError):
        await route.create_email_template.__wrapped__(
            body=body,
            credentials=None,
            log_context=type("Ctx", (), {"user_id": "root"})(),
        )


@pytest.mark.asyncio
async def test_route_create_dynamic_template_persists_catalog_metadata(monkeypatch):
    from src.routes import email_templates as route

    captured = {}
    monkeypatch.setattr(route, "is_root_user", lambda user_id: True)
    monkeypatch.setattr(route, "_audit", lambda *args, **kwargs: None)

    def create_dynamic_template(**kwargs):
        captured["kwargs"] = kwargs
        return {"version": 1, "revision": 1}

    monkeypatch.setattr(route.db_email_templates, "create_dynamic_template", create_dynamic_template)

    body = route.TemplateCreateRequest(
        template_code="ops_notice",
        purpose="delivery_operation",
        allowed_variables=["notice", "ticket_id"],
        required_variables=["notice"],
        subject_template="Notice $ticket_id",
        html_template="<p>$notice</p>",
        text_template="$notice",
    )

    response = await route.create_email_template.__wrapped__(
        body=body,
        credentials=None,
        log_context=type("Ctx", (), {"user_id": "root"})(),
    )

    assert response["success"] is True
    assert response["is_dynamic"] is True
    assert captured["kwargs"]["template_code"] == "ops_notice"
    assert captured["kwargs"]["purpose"] == "delivery_operation"
    assert captured["kwargs"]["allowed_variables"] == ("notice", "ticket_id")
    assert captured["kwargs"]["required_variables"] == ("notice",)


@pytest.mark.asyncio
async def test_route_disable_preserves_versions_by_calling_disable(monkeypatch):
    from src.routes import email_templates as route

    calls = {}
    monkeypatch.setattr(route, "is_root_user", lambda user_id: True)
    monkeypatch.setattr(route, "_audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        route,
        "_load_template",
        lambda code, allow_disabled=True: TEMPLATES["delivery_operation"],
    )

    def disable_template(**kwargs):
        calls["kwargs"] = kwargs
        return {"revision": 6}

    monkeypatch.setattr(route.db_email_templates, "disable_template", disable_template)

    response = await route.disable_email_template.__wrapped__(
        template_code="delivery_operation",
        credentials=None,
        log_context=type("Ctx", (), {"user_id": "root-user"})(),
    )

    assert response["is_enabled"] is False
    assert response["revision"] == 6
    assert calls["kwargs"] == {"template_code": "delivery_operation", "disabled_by": "root-user"}


@pytest.mark.asyncio
async def test_route_put_after_disable_reenables_with_new_version(monkeypatch):
    from src.routes import email_templates as route

    disabled = TransactionalEmailTemplate(
        code="ops_notice",
        purpose="delivery_operation",
        subject_template="Old $notice",
        html_template="<p>$notice</p>",
        text_template="$notice",
        required_variables=("notice",),
        allowed_variables=("notice",),
        version=1,
        source="db",
        is_dynamic=True,
        is_enabled=False,
        revision=4,
    )
    captured = {}
    monkeypatch.setattr(route, "is_root_user", lambda user_id: True)
    monkeypatch.setattr(route, "_audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(route, "_load_template", lambda code, allow_disabled=True: disabled)

    def save_and_activate_template(**kwargs):
        captured["kwargs"] = kwargs
        return {"version": 2, "revision": 5}

    monkeypatch.setattr(route.db_email_templates, "save_and_activate_template", save_and_activate_template)

    response = await route.update_email_template.__wrapped__(
        template_code="ops_notice",
        body=route.TemplateDraft(
            subject_template="New $notice",
            html_template="<p>$notice</p>",
            text_template="$notice",
        ),
        credentials=None,
        log_context=type("Ctx", (), {"user_id": "root-user"})(),
    )

    assert response["is_enabled"] is True
    assert response["version"] == 2
    assert response["revision"] == 5
    assert captured["kwargs"]["template_code"] == "ops_notice"


@pytest.mark.asyncio
async def test_route_rollback_rejects_invalid_target_before_reenabling(monkeypatch):
    from src.routes import email_templates as route

    state = TransactionalEmailTemplate(
        code="ops_notice",
        purpose="delivery_operation",
        subject_template="Current $notice",
        html_template="<p>$notice</p>",
        text_template="$notice",
        required_variables=("notice",),
        allowed_variables=("notice",),
        version=2,
        source="db",
        is_dynamic=True,
        is_enabled=False,
        revision=4,
    )
    rollback_called = False
    monkeypatch.setattr(route, "is_root_user", lambda user_id: True)
    monkeypatch.setattr(route, "_load_template", lambda code, allow_disabled=True: state)
    monkeypatch.setattr(
        route.db_email_templates,
        "get_template_version",
        lambda code, version: {
            "version": version,
            "subject_template": "Broken",
            "html_template": "<p>No required placeholder</p>",
            "text_template": "No required placeholder",
        },
    )

    def rollback_template(**kwargs):
        nonlocal rollback_called
        rollback_called = True
        return {"revision": 5}

    monkeypatch.setattr(route.db_email_templates, "rollback_template", rollback_template)

    with pytest.raises(ValidationError):
        await route.rollback_email_template.__wrapped__(
            template_code="ops_notice",
            body=route.TemplateRollbackRequest(version=1),
            credentials=None,
            log_context=type("Ctx", (), {"user_id": "root-user"})(),
        )

    assert rollback_called is False


@pytest.mark.asyncio
async def test_route_rollback_reenables_valid_existing_version(monkeypatch):
    from src.routes import email_templates as route

    state = TransactionalEmailTemplate(
        code="ops_notice",
        purpose="delivery_operation",
        subject_template="Current $notice",
        html_template="<p>$notice</p>",
        text_template="$notice",
        required_variables=("notice",),
        allowed_variables=("notice",),
        version=2,
        source="db",
        is_dynamic=True,
        is_enabled=False,
        revision=4,
    )
    calls = {}
    monkeypatch.setattr(route, "is_root_user", lambda user_id: True)
    monkeypatch.setattr(route, "_audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(route, "_load_template", lambda code, allow_disabled=True: state)
    monkeypatch.setattr(
        route.db_email_templates,
        "get_template_version",
        lambda code, version: {
            "version": version,
            "subject_template": "Restored $notice",
            "html_template": "<p>$notice</p>",
            "text_template": "$notice",
        },
    )

    def rollback_template(**kwargs):
        calls["kwargs"] = kwargs
        return {"revision": 5}

    monkeypatch.setattr(route.db_email_templates, "rollback_template", rollback_template)

    response = await route.rollback_email_template.__wrapped__(
        template_code="ops_notice",
        body=route.TemplateRollbackRequest(version=1),
        credentials=None,
        log_context=type("Ctx", (), {"user_id": "root-user"})(),
    )

    assert response["is_enabled"] is True
    assert response["revision"] == 5
    assert calls["kwargs"] == {"template_code": "ops_notice", "version": 1}


def test_router_and_app_wire_up():
    # Catches import/registration errors in the admin router and main app.
    import importlib

    importlib.import_module("src.routes.email_templates")
    main = importlib.import_module("src.main")
    paths = {route.path for route in main.app.routes if hasattr(route, "path")}
    assert "/admin/email-templates" in paths
    assert "/admin/email-templates/{template_code}" in paths
    assert "/admin/email-templates/{template_code}/send-test" in paths
