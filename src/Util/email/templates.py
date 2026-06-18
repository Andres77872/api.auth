"""Transactional-auth email templates.

Trace:
- SDD `email-activation` task 4.7.
- Spec requirement: auth transactional email only; no marketing/broadcast scope.
- Design requirement: templates omit one-click unsubscribe headers and keep
  template variables safe for redacted audit/admin surfaces.

Rendering engine
----------------
Templates are rendered with :class:`string.Template` (``$name`` / ``${name}``
placeholders), NOT ``str.format``/``str.format_map``. This is deliberate and a
security control: ``format``/``format_map`` evaluate attribute and index access
inside ``{...}`` (e.g. ``{x.__class__.__init__.__globals__[...]}``), which is a
server-side template-injection / secret-exfiltration vector once template text
becomes admin-editable (DB-backed templates, see :func:`resolve_template`).
``string.Template`` is logic-less: a placeholder is only ever a bare identifier
mapped to a pre-escaped string value, so there is no attribute/expression
surface. Every identifier used by a template is additionally checked against a
per-code allowlist before substitution.

Template source
---------------
``render_transactional_template`` resolves each ``template_code`` to its active
DB-managed version when present and falls back to the in-code :data:`TEMPLATES`
defaults below on an empty result OR any database error, so an empty/unavailable
``email_templates`` table never breaks delivery. The in-code defaults and the DB
seed are kept byte-identical (the seed inserts these very strings).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from html import escape
from string import Template
from typing import Any, Mapping

from src.Util.email.security import sanitize_email_log_value

logger = logging.getLogger(__name__)


AUTH_TRANSACTIONAL_SCOPE = "auth_transactional"
TRANSACTIONAL_TEMPLATE_CODES = frozenset(
    {
        "email_activation",
        "password_reset",
        "admin_password_reset",
        "security_notification",
        "delivery_operation",
        "patreon_link_proof",
        "free_credit_invite",
    }
)
SENSITIVE_TEMPLATE_VARIABLES = frozenset(
    {
        "activation_link",
        "reset_link",
        "patreon_link_proof_url",
        "action_url",
        "proof_token",
        "token",
        "secret",
        "lookup_id",
        "recipient_email",
        "email",
        "idempotency_key",
    }
)

# Default variables available to every transactional template. Optional values
# are always present (so a template never substitutes a missing key) while the
# per-template ``required_variables`` gate enforces the ones a workflow MUST
# supply.
BASE_TEMPLATE_VARIABLES: tuple[str, ...] = (
    "app_name",
    "recipient_masked",
    "expires_in",
    "support_email",
    "event_title",
    "message",
    "status_summary",
)

# Per-code allowlist of placeholder identifiers an editor may use in the
# subject/html/text of a template. This is the single source of truth shared by
# the render-time validator and the admin save-time validator, and is exposed to
# the dashboard editor's "insert variable" menu. New/arbitrary identifiers are
# rejected.
ALLOWED_TEMPLATE_VARIABLES: dict[str, frozenset[str]] = {
    "email_activation": frozenset(
        {"app_name", "recipient_masked", "expires_in", "support_email", "activation_link"}
    ),
    "password_reset": frozenset(
        {"app_name", "recipient_masked", "expires_in", "support_email", "reset_link"}
    ),
    "admin_password_reset": frozenset(
        {"app_name", "recipient_masked", "expires_in", "support_email", "reset_link"}
    ),
    "security_notification": frozenset(
        {"app_name", "support_email", "event_title", "message"}
    ),
    "delivery_operation": frozenset(
        {"app_name", "support_email", "status_summary"}
    ),
    "patreon_link_proof": frozenset(
        {
            "app_name",
            "recipient_masked",
            "expires_in",
            "expires_at",
            "support_email",
            "patreon_link_proof_url",
            "proof_token",
            "lookup_id",
        }
    ),
    "free_credit_invite": frozenset(
        {
            "app_name",
            "recipient_masked",
            "credits",
            "action_url",
            "expires_at",
            "support_email",
            "expires_in",
        }
    ),
}


class EmailTemplateError(ValueError):
    """Raised when a transactional template cannot be rendered safely."""


@dataclass(frozen=True)
class TransactionalEmailTemplate:
    code: str
    purpose: str
    subject_template: str
    html_template: str
    text_template: str
    required_variables: tuple[str, ...] = ()
    # Provenance of the resolved template. ``version`` is the DB version number
    # when sourced from the ``email_templates`` table, else ``None`` for the
    # in-code fallback.
    version: int | None = None
    source: str = "code"


@dataclass(frozen=True)
class RenderedEmailTemplate:
    template_code: str
    purpose: str
    subject: str
    html: str
    text: str
    headers: dict[str, str]
    tags: dict[str, str]
    redaction_safe_variables: dict[str, str]


def _clean_text(value: Any) -> str:
    """Render a value as single-line-ish text without header/control injection."""

    text = str(value if value is not None else "")
    return " ".join(text.replace("\r", " ").replace("\n", " ").split())


def allowed_variables(template_code: str) -> frozenset[str]:
    """Return the placeholder identifiers an editor may use for a template."""

    code = str(template_code or "").strip().lower()
    return ALLOWED_TEMPLATE_VARIABLES.get(code, frozenset(BASE_TEMPLATE_VARIABLES))


def template_identifiers(text: str) -> set[str]:
    """Return the ``$``-placeholder identifiers used in a template string.

    Raises :class:`EmailTemplateError` if the string contains a malformed
    placeholder (e.g. a stray ``$``), which is itself a rejection signal for
    admin-supplied template bodies.
    """

    tpl = Template(text)
    if not tpl.is_valid():
        raise EmailTemplateError("template contains an invalid $ placeholder")
    return set(tpl.get_identifiers())


def _template_fields(template: TransactionalEmailTemplate) -> set[str]:
    fields: set[str] = set()
    for raw_template in (template.subject_template, template.html_template, template.text_template):
        fields |= template_identifiers(raw_template)
    return fields


def validate_template_identifiers(
    *,
    template_code: str,
    subject_template: str,
    html_template: str,
    text_template: str,
) -> set[str]:
    """Reject any placeholder not in the per-code allowlist; return the used set.

    Shared by render-time resolution and the admin save path so a DB-managed
    template can never reference an identifier outside the vetted allowlist.
    """

    allowed = allowed_variables(template_code)
    used: set[str] = set()
    for raw_template in (subject_template, html_template, text_template):
        used |= template_identifiers(raw_template)
    unknown = used - set(allowed)
    if unknown:
        raise EmailTemplateError(
            "template uses variables outside the allowlist: " + ", ".join(sorted(unknown))
        )
    return used


def _base_variables(variables: Mapping[str, Any] | None) -> dict[str, str]:
    raw = dict(variables or {})
    raw.setdefault("app_name", "Magic Auth")
    raw.setdefault("recipient_masked", "your email address")
    raw.setdefault("expires_in", "24 hours")
    raw.setdefault("support_email", "support")
    raw.setdefault("event_title", "Security notification")
    raw.setdefault("message", "A security event occurred on your account.")
    raw.setdefault("status_summary", "A delivery operation was recorded.")
    return {key: _clean_text(value) for key, value in raw.items()}


def _html_variables(values: Mapping[str, str]) -> dict[str, str]:
    return {key: escape(value, quote=True) for key, value in values.items()}


def _substitute(template_text: str, values: Mapping[str, str]) -> str:
    """Render one template string with string.Template (strict substitution).

    Uses ``.substitute`` (not ``.safe_substitute``) so a missing identifier is a
    hard error rather than a silently-unrendered ``$token`` in delivered mail.
    """

    try:
        return Template(template_text).substitute(values)
    except KeyError as exc:
        raise EmailTemplateError(f"missing template variable: {exc.args[0]}") from exc
    except ValueError as exc:
        raise EmailTemplateError(f"invalid template placeholder: {exc}") from exc


def _redaction_safe_variables(values: Mapping[str, str]) -> dict[str, str]:
    safe: dict[str, str] = {}
    for key, value in values.items():
        normalized_key = key.lower()
        if normalized_key in SENSITIVE_TEMPLATE_VARIABLES or normalized_key.endswith("_link"):
            safe[key] = "[REDACTED]"
        else:
            safe[key] = sanitize_email_log_value(value)
    return safe


# ---------------------------------------------------------------------------
# Best-practice transactional layout (shared by the in-code defaults / DB seed)
# ---------------------------------------------------------------------------
# Notes:
# - Table-based, ~600px centered container with role="presentation" for AT.
# - Inlined element styles + a small <style> head for things that cannot be
#   inlined (dark-mode media query, mobile width). color-scheme meta opts in to
#   native dark rendering; off-white/off-dark palette avoids forced inversion.
# - Placeholders are ``$name``; literal ``{ }`` in CSS need no escaping.
_BASE_STYLE = (
    "<style>"
    "body{margin:0;padding:0;background:#f4f5f7;}"
    "a{color:#2563eb;}"
    "@media (prefers-color-scheme:dark){"
    ".email-bg{background:#0b0d12!important;}"
    ".email-card{background:#15181f!important;}"
    ".email-heading{color:#f3f4f6!important;}"
    ".email-text{color:#d1d5db!important;}"
    ".email-muted{color:#9aa4b2!important;}"
    "}"
    "@media (max-width:620px){.email-container{width:100%!important;}}"
    "</style>"
)


def _button(href_placeholder: str, label: str) -> str:
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" style="margin:24px 0;">'
        '<tr><td align="center" bgcolor="#2563eb" style="border-radius:8px;">'
        f'<a href="{href_placeholder}" '
        'style="display:inline-block;padding:13px 30px;font-family:Arial,Helvetica,sans-serif;'
        'font-size:16px;font-weight:bold;line-height:20px;color:#ffffff;text-decoration:none;'
        'border-radius:8px;">'
        f"{label}</a>"
        "</td></tr></table>"
    )


def _paragraph(content: str, *, muted: bool = False, margin: str = "0 0 16px") -> str:
    css_class = "email-muted" if muted else "email-text"
    color = "#6b7280" if muted else "#1f2933"
    return (
        f'<p class="{css_class}" style="margin:{margin};font-family:Arial,Helvetica,sans-serif;'
        f'font-size:15px;line-height:22px;color:{color};">{content}</p>'
    )


def _heading(text: str) -> str:
    return (
        f'<h1 class="email-heading" style="margin:0 0 18px;font-family:Arial,Helvetica,sans-serif;'
        f'font-size:22px;line-height:28px;color:#111827;">{text}</h1>'
    )


def _link_fallback(href_placeholder: str) -> str:
    return (
        _paragraph("Or copy and paste this link into your browser:", muted=True, margin="0 0 6px")
        + '<p style="margin:0 0 18px;font-family:Arial,Helvetica,sans-serif;font-size:13px;'
        'line-height:20px;word-break:break-all;">'
        f'<a href="{href_placeholder}">{href_placeholder}</a></p>'
    )


def _document(*, title: str, preheader: str, content_html: str) -> str:
    return (
        "<!DOCTYPE html>"
        '<html lang="en" style="margin:0;padding:0;">'
        "<head>"
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="x-apple-disable-message-reformatting" content="">'
        '<meta name="color-scheme" content="light dark">'
        '<meta name="supported-color-schemes" content="light dark">'
        f"<title>{title}</title>"
        + _BASE_STYLE
        + "</head>"
        '<body class="email-bg" style="margin:0;padding:0;background:#f4f5f7;">'
        '<div style="display:none;max-height:0;overflow:hidden;mso-hide:all;opacity:0;color:transparent;">'
        f"{preheader}"
        "</div>"
        '<div style="display:none;max-height:0;overflow:hidden;mso-hide:all;">'
        "&#8199;&#65279;&#8199;&#65279;&#8199;&#65279;&#8199;&#65279;&#8199;&#65279;"
        "</div>"
        '<table role="presentation" class="email-bg" width="100%" cellpadding="0" cellspacing="0" '
        'style="background:#f4f5f7;border-collapse:collapse;"><tr>'
        '<td align="center" style="padding:24px 12px;">'
        '<table role="presentation" class="email-container email-card" width="600" cellpadding="0" '
        'cellspacing="0" style="width:600px;max-width:600px;background:#ffffff;border-radius:12px;'
        'border-collapse:separate;"><tr>'
        '<td style="padding:32px 36px;">'
        + content_html
        + "</td></tr></table>"
        '<table role="presentation" class="email-container" width="600" cellpadding="0" cellspacing="0" '
        'style="width:600px;max-width:600px;border-collapse:collapse;"><tr>'
        '<td style="padding:16px 36px 4px;">'
        '<p class="email-muted" style="margin:0;font-family:Arial,Helvetica,sans-serif;font-size:12px;'
        'line-height:18px;color:#9aa4b2;">'
        "This is an automated message from $app_name. Please do not reply to this email."
        "</p>"
        "</td></tr></table>"
        "</td></tr></table>"
        "</body></html>"
    )


# ---------------------------------------------------------------------------
# In-code defaults (also the DB seed and the always-available fallback).
# ---------------------------------------------------------------------------
TEMPLATES: dict[str, TransactionalEmailTemplate] = {
    "email_activation": TransactionalEmailTemplate(
        code="email_activation",
        purpose="email_activation",
        subject_template="Activate your $app_name email",
        required_variables=("activation_link",),
        html_template=_document(
            title="Activate your email",
            preheader="Confirm your email address to finish setting up your account.",
            content_html=(
                _heading("Activate your email")
                + _paragraph("Use the button below to activate $recipient_masked for $app_name.")
                + _button("$activation_link", "Activate email")
                + _link_fallback("$activation_link")
                + _paragraph(
                    "This link expires in $expires_in. If you did not request this, you can safely "
                    "ignore this message.",
                    muted=True,
                    margin="0",
                )
            ),
        ),
        text_template=(
            "Activate your $app_name email\n"
            "=============================\n\n"
            "Use this link to activate $recipient_masked for $app_name:\n\n"
            "$activation_link\n\n"
            "This link expires in $expires_in. If you did not request this, you can safely ignore "
            "this message."
        ),
    ),
    "password_reset": TransactionalEmailTemplate(
        code="password_reset",
        purpose="password_reset",
        subject_template="Reset your $app_name password",
        required_variables=("reset_link",),
        html_template=_document(
            title="Reset your password",
            preheader="Use the link inside to choose a new password.",
            content_html=(
                _heading("Reset your password")
                + _paragraph("Use the button below to reset your $app_name password.")
                + _button("$reset_link", "Reset password")
                + _link_fallback("$reset_link")
                + _paragraph(
                    "This link expires in $expires_in. If you did not request this, you can safely "
                    "ignore this message.",
                    muted=True,
                    margin="0",
                )
            ),
        ),
        text_template=(
            "Reset your $app_name password\n"
            "=============================\n\n"
            "Use this link to reset your $app_name password:\n\n"
            "$reset_link\n\n"
            "This link expires in $expires_in. If you did not request this, you can safely ignore "
            "this message."
        ),
    ),
    "admin_password_reset": TransactionalEmailTemplate(
        code="admin_password_reset",
        purpose="admin_password_reset",
        subject_template="Reset your $app_name password",
        required_variables=("reset_link",),
        html_template=_document(
            title="Reset your password",
            preheader="An administrator requested a password reset for your account.",
            content_html=(
                _heading("Reset your password")
                + _paragraph(
                    "An authorized administrator requested a password reset for your $app_name account."
                )
                + _button("$reset_link", "Reset password")
                + _link_fallback("$reset_link")
                + _paragraph(
                    "This link expires in $expires_in. If this looks wrong, contact $support_email.",
                    muted=True,
                    margin="0",
                )
            ),
        ),
        text_template=(
            "Reset your $app_name password\n"
            "=============================\n\n"
            "An authorized administrator requested a password reset for your $app_name account:\n\n"
            "$reset_link\n\n"
            "This link expires in $expires_in. If this looks wrong, contact $support_email."
        ),
    ),
    "security_notification": TransactionalEmailTemplate(
        code="security_notification",
        purpose="security_notification",
        subject_template="$app_name security notification",
        required_variables=("message",),
        html_template=_document(
            title="Security notification",
            preheader="A security event was recorded on your account.",
            content_html=(
                _heading("$event_title")
                + _paragraph("$message")
                + _paragraph(
                    "If this was not you, review your account security immediately.",
                    muted=True,
                    margin="0",
                )
            ),
        ),
        text_template=(
            "$event_title\n\n"
            "$message\n\n"
            "If this was not you, review your account security immediately."
        ),
    ),
    "delivery_operation": TransactionalEmailTemplate(
        code="delivery_operation",
        purpose="delivery_operation",
        subject_template="$app_name delivery update",
        required_variables=("status_summary",),
        html_template=_document(
            title="Delivery update",
            preheader="A transactional email delivery update.",
            content_html=(
                _heading("Delivery update")
                + _paragraph("Transactional email delivery update:")
                + _paragraph("$status_summary", muted=True, margin="0")
            ),
        ),
        text_template=("Transactional email delivery update:\n\n$status_summary"),
    ),
    "free_credit_invite": TransactionalEmailTemplate(
        code="free_credit_invite",
        purpose="delivery_operation",
        subject_template="You have $credits Magic Worlds credits",
        required_variables=("credits", "action_url"),
        html_template=_document(
            title="Magic Worlds credits",
            preheader="A Magic Worlds administrator sent credits to this email address.",
            content_html=(
                _heading("Magic Worlds credits")
                + _paragraph(
                    "A Magic Worlds administrator sent <strong>$credits</strong> credits to "
                    "$recipient_masked."
                )
                + _paragraph(
                    "If this email is already linked to your account, the credits have been added. "
                    "Otherwise, open Magic Worlds and create or activate an account with this email "
                    "to receive them."
                )
                + _button("$action_url", "Open Magic Worlds")
                + _link_fallback("$action_url")
                + _paragraph("Expiration: $expires_at", muted=True, margin="0")
            ),
        ),
        text_template=(
            "Magic Worlds credits\n"
            "====================\n\n"
            "A Magic Worlds administrator sent $credits credits to $recipient_masked.\n\n"
            "If this email is already linked to your account, the credits have been added. "
            "Otherwise, open Magic Worlds and create or activate an account with this email to receive them:\n\n"
            "$action_url\n\n"
            "Expiration: $expires_at"
        ),
    ),
    "patreon_link_proof": TransactionalEmailTemplate(
        code="patreon_link_proof",
        purpose="patreon_link_proof",
        subject_template="Confirm your Patreon link",
        required_variables=("patreon_link_proof_url", "proof_token"),
        html_template=_document(
            title="Confirm your Patreon link",
            preheader="Use this one-time proof to confirm your Patreon membership link.",
            content_html=(
                _heading("Confirm your Patreon link")
                + _paragraph(
                    "Use the button below to confirm the Patreon membership link requested for "
                    "$recipient_masked."
                )
                + _button("$patreon_link_proof_url", "Confirm Patreon link")
                + _link_fallback("$patreon_link_proof_url")
                + _paragraph("One-time proof code: <strong>$proof_token</strong>")
                + _paragraph(
                    "This proof expires at $expires_at. If you did not request this, you can safely "
                    "ignore this message.",
                    muted=True,
                    margin="0",
                )
            ),
        ),
        text_template=(
            "Confirm your Patreon link\n"
            "=========================\n\n"
            "Use this one-time proof to confirm the Patreon membership link requested for "
            "$recipient_masked:\n\n"
            "$patreon_link_proof_url\n\n"
            "Proof code: $proof_token\n\n"
            "This proof expires at $expires_at. If you did not request this, you can safely ignore "
            "this message."
        ),
    ),
}


def _template_from_row(code: str, row: Mapping[str, Any]) -> TransactionalEmailTemplate:
    """Build a template from a DB ``email_templates`` row.

    ``required_variables`` are intrinsic to the workflow (which variables the
    enqueue path provides) and are taken from the in-code default, never from
    the editable DB row.
    """

    default = TEMPLATES[code]
    subject = str(row.get("subject_template") or "")
    html = str(row.get("html_template") or "")
    text = str(row.get("text_template") or "")
    if not (subject and html and text):
        raise EmailTemplateError("DB template row is missing subject/html/text")
    used = validate_template_identifiers(
        template_code=code,
        subject_template=subject,
        html_template=html,
        text_template=text,
    )
    missing_required = [name for name in default.required_variables if name not in used]
    if missing_required:
        raise EmailTemplateError(
            "DB template row is missing required variable references: "
            + ", ".join(sorted(missing_required))
        )
    version = row.get("version")
    return TransactionalEmailTemplate(
        code=code,
        purpose=default.purpose,
        subject_template=subject,
        html_template=html,
        text_template=text,
        required_variables=default.required_variables,
        version=int(version) if version is not None else None,
        source="db",
    )


def resolve_template(template_code: str) -> TransactionalEmailTemplate:
    """Resolve a template to its active DB version, falling back to in-code.

    Resilience contract: an empty ``email_templates`` table OR any database
    error falls back to the in-code default so transient DB issues never break
    delivery (a render failure would dead-letter the message).
    """

    code = str(template_code or "").strip().lower()
    if code not in TEMPLATES:
        raise EmailTemplateError("template is not allowed for transactional auth email")

    row: Mapping[str, Any] | None = None
    try:
        from src.Util.db import db_email_templates  # local import avoids import cycle

        row = db_email_templates.get_active_template(code)
    except Exception:  # pragma: no cover - defensive: DB unavailable
        logger.warning(
            "email template DB lookup failed; using in-code fallback for %s",
            sanitize_email_log_value(code),
            exc_info=True,
        )
        row = None

    if row:
        try:
            return _template_from_row(code, row)
        except Exception:
            logger.warning(
                "invalid DB email template row; using in-code fallback for %s",
                sanitize_email_log_value(code),
                exc_info=True,
            )
    return TEMPLATES[code]


def get_transactional_template(template_code: str) -> TransactionalEmailTemplate:
    """Return a template only if it belongs to the auth transactional scope."""

    code = str(template_code or "").strip().lower()
    if code not in TRANSACTIONAL_TEMPLATE_CODES or code not in TEMPLATES:
        raise EmailTemplateError("template is not allowed for transactional auth email")
    return resolve_template(code)


def render_template_parts(
    template: TransactionalEmailTemplate,
    variables: Mapping[str, Any] | None = None,
    *,
    message_id: str | None = None,
) -> RenderedEmailTemplate:
    """Render an explicit template object — the single render funnel.

    This is the one place subject/html/text are turned into a delivered message.
    The worker (via :func:`render_transactional_template`), the admin *preview*,
    and *send-test* all funnel through here so preview is byte-identical to the
    real send. It validates the placeholder allowlist, fills base-variable
    defaults, enforces required variables, HTML-escapes values, and substitutes
    with ``string.Template`` (no attribute/expression surface).

    The returned ``headers`` deliberately excludes ``List-Unsubscribe`` /
    ``List-Unsubscribe-Post``; this subsystem is auth/security email, not
    marketing preference management.
    """

    # Defense in depth: only allowlisted identifiers may appear in any part of
    # the (possibly admin-authored, DB-sourced) template.
    validate_template_identifiers(
        template_code=template.code,
        subject_template=template.subject_template,
        html_template=template.html_template,
        text_template=template.text_template,
    )

    values = _base_variables(variables)
    missing = [name for name in template.required_variables if not values.get(name)]
    if missing:
        raise EmailTemplateError(f"missing required template variables: {', '.join(missing)}")

    html_values = _html_variables(values)
    subject = _substitute(template.subject_template, values)
    html = _substitute(template.html_template, html_values)
    text = _substitute(template.text_template, values)

    headers = {
        "X-Transactional-Scope": AUTH_TRANSACTIONAL_SCOPE,
        "X-Template-Code": template.code,
    }
    if template.version is not None:
        headers["X-Template-Version"] = str(template.version)
    if message_id:
        headers["X-Entity-Ref-ID"] = _clean_text(message_id)
    headers.pop("List-Unsubscribe-Post", None)
    headers.pop("List-Unsubscribe", None)

    used_values = {key: values.get(key, "") for key in _template_fields(template) if key in values}
    return RenderedEmailTemplate(
        template_code=template.code,
        purpose=template.purpose,
        subject=subject,
        html=html,
        text=text,
        headers=headers,
        tags={
            "scope": AUTH_TRANSACTIONAL_SCOPE,
            "purpose": template.purpose,
            "template": template.code,
        },
        redaction_safe_variables=_redaction_safe_variables(used_values),
    )


def render_transactional_template(
    template_code: str,
    variables: Mapping[str, Any] | None = None,
    *,
    message_id: str | None = None,
) -> RenderedEmailTemplate:
    """Resolve a template (DB active version → in-code fallback) and render it."""

    template = get_transactional_template(template_code)
    return render_template_parts(template, variables, message_id=message_id)


def render_email_template(
    template_code: str,
    variables: Mapping[str, Any] | None = None,
    *,
    message_id: str | None = None,
) -> RenderedEmailTemplate:
    """Compatibility alias for callers that use a shorter name."""

    return render_transactional_template(template_code, variables, message_id=message_id)


# Realistic, non-sensitive sample values used to render previews / send-tests and
# to smoke-render a draft during validation. Links are obviously fake so a test
# email is never confused with a real one.
_SAMPLE_LINK = "https://example.com/auth/email/verify?token=sample0000000000.preview000000000000"
_SAMPLE_RESET_LINK = "https://example.com/auth/password/reset?token=sample0000000000.preview000000000000"
_SAMPLE_PATREON_LINK = "https://example.com/auth/patreon/link/confirm?token=sample0000000000.preview000000000000"
_SAMPLE_MAGIC_WORLDS_LINK = "https://example.com/"


def sample_variables(template_code: str) -> dict[str, str]:
    """Return safe placeholder sample values for previewing a template."""

    code = str(template_code or "").strip().lower()
    common = {
        "app_name": "Magic Auth",
        "recipient_masked": "j***@example.com",
        "expires_in": "24 hours" if code == "email_activation" else "1 hour",
        "support_email": "support@example.com",
    }
    if code == "email_activation":
        return {**common, "activation_link": _SAMPLE_LINK}
    if code in ("password_reset", "admin_password_reset"):
        return {**common, "reset_link": _SAMPLE_RESET_LINK}
    if code == "security_notification":
        return {
            "app_name": "Magic Auth",
            "support_email": "support@example.com",
            "event_title": "New sign-in to your account",
            "message": "A new sign-in was detected from a new device in San Francisco, US.",
        }
    if code == "delivery_operation":
        return {
            "app_name": "Magic Auth",
            "support_email": "support@example.com",
            "status_summary": "Your recent email was delivered successfully.",
        }
    if code == "patreon_link_proof":
        return {
            **common,
            "expires_in": "15 minutes",
            "expires_at": "2026-01-01T00:15:00Z",
            "patreon_link_proof_url": _SAMPLE_PATREON_LINK,
            "proof_token": "sample0000000000.preview000000000000",
            "lookup_id": "sample0000000000",
        }
    if code == "free_credit_invite":
        return {
            **common,
            "app_name": "Magic Worlds",
            "credits": "25",
            "action_url": _SAMPLE_MAGIC_WORLDS_LINK,
            "expires_at": "No expiration is configured.",
        }
    return common


__all__ = [
    "ALLOWED_TEMPLATE_VARIABLES",
    "AUTH_TRANSACTIONAL_SCOPE",
    "BASE_TEMPLATE_VARIABLES",
    "EmailTemplateError",
    "RenderedEmailTemplate",
    "SENSITIVE_TEMPLATE_VARIABLES",
    "TEMPLATES",
    "TRANSACTIONAL_TEMPLATE_CODES",
    "TransactionalEmailTemplate",
    "allowed_variables",
    "get_transactional_template",
    "render_email_template",
    "render_template_parts",
    "render_transactional_template",
    "resolve_template",
    "sample_variables",
    "template_identifiers",
    "validate_template_identifiers",
]
