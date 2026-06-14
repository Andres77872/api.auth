"""Unit tests for DB-managed, safely-rendered transactional email templates.

Covers the security-critical core: the string.Template engine (no SSTI), the
placeholder allowlist, the DB→in-code resolver fallback, the single render
funnel (preview == prod), and the admin save-time validator.
"""

from __future__ import annotations

import pytest

from src.Util.email import mailpit
from src.Util.email.templates import (
    EmailTemplateError,
    TEMPLATES,
    TransactionalEmailTemplate,
    allowed_variables,
    render_email_template,
    render_template_parts,
    render_transactional_template,
    resolve_template,
    sample_variables,
)
from src.Util.email.template_validation import (
    TemplateValidationError,
    validate_html_body,
    validate_template_draft,
)


ACTIVATION_LINK = "https://app.example.com/auth/email/verify?token=lookupabcdef0123.secretabcdef0123456"


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

    row = {
        "template_code": "email_activation",
        "version": 7,
        "subject_template": "Custom $app_name activation",
        "html_template": TEMPLATES["email_activation"].html_template,
        "text_template": "$activation_link",
        "is_active": 1,
    }
    monkeypatch.setattr(db_email_templates, "get_active_template", lambda code: row)
    resolved = resolve_template("email_activation")
    assert resolved.source == "db"
    assert resolved.version == 7
    assert "Custom" in resolved.subject_template

    rendered = render_transactional_template("email_activation", {"activation_link": ACTIVATION_LINK})
    assert rendered.headers.get("X-Template-Version") == "7"


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


def test_invalid_db_row_falls_back(monkeypatch):
    from src.Util.db import db_email_templates

    monkeypatch.setattr(
        db_email_templates,
        "get_active_template",
        lambda code: {"version": 3, "subject_template": "", "html_template": "", "text_template": ""},
    )
    resolved = resolve_template("email_activation")
    assert resolved.source == "code"


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


def test_router_and_app_wire_up():
    # Catches import/registration errors in the admin router and main app.
    import importlib

    importlib.import_module("src.routes.email_templates")
    main = importlib.import_module("src.main")
    paths = {route.path for route in main.app.routes if hasattr(route, "path")}
    assert "/admin/email-templates" in paths
    assert "/admin/email-templates/{template_code}" in paths
    assert "/admin/email-templates/{template_code}/send-test" in paths
