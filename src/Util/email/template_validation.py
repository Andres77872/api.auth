"""Save-time validation for admin-editable transactional email templates.

Threat model and posture
-------------------------
Only ROOT may edit templates, the dashboard preview renders inside a script-less
sandboxed iframe, and mail clients strip executable content — so this module is
defense-in-depth, not the sole control. It is deliberately a *reject-on-violation*
validator (precise errors, the authored document preserved byte-for-byte) rather
than a silently-stripping sanitizer, which would mangle the full HTML document
(DOCTYPE/`<html>`/`<head>`/`<style>`) and could drop ``$placeholders``.

It enforces, in order:
1. Placeholder allowlist — every ``$name`` in subject/html/text must be in the
   per-code allowlist (no attribute/expression syntax; that is structurally
   impossible with ``string.Template``, but unknown names are rejected here).
2. Required variables — the workflow's required variable(s) must actually be
   referenced (e.g. an activation email must keep ``$activation_link``).
3. HTML safety — no ``<script>``/``<iframe>``/etc., no ``on*`` event handlers,
   no ``javascript:``/``vbscript:``/``data:`` URLs, no ``<meta http-equiv=refresh>``,
   no CSS ``expression()``/``@import``/``javascript:`` in style.
4. Render smoke test — the draft renders cleanly through the real funnel with
   sample data (so a broken template can never be saved/sent).
"""

from __future__ import annotations

from html.parser import HTMLParser

from src.Util.email.templates import (
    EmailTemplateError,
    TEMPLATES,
    TRANSACTIONAL_TEMPLATE_CODES,
    TransactionalEmailTemplate,
    allowed_variables,
    render_template_parts,
    sample_variables,
    validate_template_identifiers,
)

MAX_SUBJECT_LENGTH = 255
MAX_HTML_LENGTH = 100_000  # keep well under Gmail's ~102KB clipping threshold
MAX_TEXT_LENGTH = 40_000

# Structural/formatting tags an email body may use. Anything else is rejected.
ALLOWED_HTML_TAGS = frozenset(
    {
        "html", "head", "body", "title", "meta", "style",
        "table", "thead", "tbody", "tfoot", "tr", "td", "th",
        "div", "span", "p", "br", "hr", "a", "img",
        "h1", "h2", "h3", "h4", "h5", "h6",
        "strong", "b", "em", "i", "u", "small", "blockquote",
        "ul", "ol", "li", "center", "font",
    }
)

# Tags that must never appear in a transactional email body.
FORBIDDEN_HTML_TAGS = frozenset(
    {
        "script", "iframe", "object", "embed", "applet", "base", "form",
        "input", "button", "textarea", "select", "option", "link", "noscript",
        "template", "svg", "math", "frame", "frameset", "audio", "video",
        "source", "track", "canvas", "map", "area", "portal",
    }
)

# Attributes carrying a URL whose scheme must be validated.
_URL_ATTRIBUTES = frozenset({"href", "src", "background", "action", "xlink:href", "formaction"})
_ALLOWED_URL_SCHEMES = frozenset({"http", "https", "mailto"})


class TemplateValidationError(EmailTemplateError):
    """Raised when an admin-supplied template fails validation."""


def _violation(message: str) -> TemplateValidationError:
    return TemplateValidationError(message)


def _check_url_value(tag: str, attr: str, value: str) -> None:
    raw = (value or "").strip()
    if not raw:
        return
    # Allow template placeholders as whole or partial values (e.g. href="$activation_link").
    if raw.startswith("$"):
        return
    lowered = raw.lower()
    # A scheme is present only when a ':' precedes any '/', '?', '#'.
    scheme = ""
    for index, char in enumerate(lowered):
        if char == ":":
            scheme = lowered[:index]
            break
        if char in "/?#":
            break
    if scheme and scheme not in _ALLOWED_URL_SCHEMES:
        raise _violation(
            f"disallowed URL scheme '{scheme}:' in <{tag} {attr}>; "
            "only http, https and mailto are permitted"
        )


def _check_style_value(value: str) -> None:
    lowered = (value or "").lower()
    for needle in ("expression(", "javascript:", "vbscript:", "@import", "behavior:", "-moz-binding"):
        if needle in lowered:
            raise _violation(f"disallowed CSS construct '{needle}' in a style value")


class _HtmlGuard(HTMLParser):
    """Walk the document and raise on the first unsafe construct."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)

    def _check(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        name = tag.lower()
        if name in FORBIDDEN_HTML_TAGS:
            raise _violation(f"disallowed HTML tag <{name}>")
        if name not in ALLOWED_HTML_TAGS:
            raise _violation(f"unrecognized HTML tag <{name}> is not permitted in email templates")
        for attr_name, attr_value in attrs:
            attr = (attr_name or "").lower()
            value = attr_value or ""
            if attr.startswith("on"):
                raise _violation(f"event-handler attribute '{attr}' is not allowed")
            if attr == "style":
                _check_style_value(value)
            if attr in _URL_ATTRIBUTES:
                _check_url_value(name, attr, value)
            if name == "meta" and attr == "http-equiv" and value.strip().lower() == "refresh":
                raise _violation("<meta http-equiv=\"refresh\"> is not allowed")
            if attr == "srcdoc":
                raise _violation("the 'srcdoc' attribute is not allowed")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._check(tag, attrs)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._check(tag, attrs)


def validate_html_body(html_template: str) -> None:
    """Reject an HTML body containing unsafe tags/attributes/URLs."""

    guard = _HtmlGuard()
    guard.feed(html_template or "")
    guard.close()


def validate_template_draft(
    *,
    template_code: str,
    subject_template: str,
    html_template: str,
    text_template: str,
) -> dict[str, object]:
    """Validate an admin-submitted draft; raise on any problem.

    Returns a small summary (used variables) on success.
    """

    code = str(template_code or "").strip().lower()
    if code not in TRANSACTIONAL_TEMPLATE_CODES or code not in TEMPLATES:
        raise _violation("unknown or non-transactional template code")

    subject = str(subject_template or "")
    html = str(html_template or "")
    text = str(text_template or "")

    if not subject.strip():
        raise _violation("subject is required")
    if not html.strip():
        raise _violation("HTML body is required")
    if not text.strip():
        raise _violation("plain-text body is required")
    if len(subject) > MAX_SUBJECT_LENGTH:
        raise _violation(f"subject exceeds {MAX_SUBJECT_LENGTH} characters")
    if "\n" in subject or "\r" in subject:
        raise _violation("subject must be a single line")
    if len(html) > MAX_HTML_LENGTH:
        raise _violation(f"HTML body exceeds {MAX_HTML_LENGTH} characters")
    if len(text) > MAX_TEXT_LENGTH:
        raise _violation(f"plain-text body exceeds {MAX_TEXT_LENGTH} characters")

    required = TEMPLATES[code].required_variables
    try:
        # 1. Placeholder allowlist (subject + html + text).
        used = validate_template_identifiers(
            template_code=code,
            subject_template=subject,
            html_template=html,
            text_template=text,
        )

        # 2. Required workflow variables must actually be referenced.
        missing_required = [name for name in required if name not in used]
        if missing_required:
            raise _violation(
                "template must reference the required variable(s): "
                + ", ".join("$" + name for name in missing_required)
            )

        # 3. HTML safety.
        validate_html_body(html)

        # 4. Render smoke test through the real funnel with sample data.
        draft = TransactionalEmailTemplate(
            code=code,
            purpose=TEMPLATES[code].purpose,
            subject_template=subject,
            html_template=html,
            text_template=text,
            required_variables=required,
        )
        render_template_parts(draft, sample_variables(code))
    except TemplateValidationError:
        raise
    except EmailTemplateError as exc:
        # Normalise the lower-level render/identifier errors to one public type.
        raise TemplateValidationError(str(exc)) from exc

    return {
        "used_variables": sorted(used),
        "allowed_variables": sorted(allowed_variables(code)),
        "required_variables": list(required),
    }


__all__ = [
    "ALLOWED_HTML_TAGS",
    "FORBIDDEN_HTML_TAGS",
    "TemplateValidationError",
    "validate_html_body",
    "validate_template_draft",
]
