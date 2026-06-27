"""ROOT-only admin API for DB-managed transactional email templates.

Endpoints (prefix ``/admin/email-templates``):
- ``GET    ""``                      list every transactional code + active source/version
- ``GET    /{code}``                 active subject/html/text + allowlist + version history
- ``PUT    /{code}``                 validate + sanitize-check, save a new active version
- ``POST   /{code}/preview``         render a draft (or the active version) with sample data
- ``POST   /{code}/send-test``       send a rendered test to the ROOT user's OWN verified email
- ``POST   /{code}/rollback``        re-activate a prior version

Security posture:
- ROOT only (``is_root_user``); editing security-email content is high impact.
- Drafts pass :func:`validate_template_draft` (placeholder allowlist, required-var
  presence, HTML safety, render smoke test) before they can be saved/previewed/sent.
- Rendering always funnels through ``render_template_parts`` so preview/send-test
  match the worker's real output exactly; variables are fixed server-side
  ``sample_variables`` (admins never inject variable values).
- ``send-test`` cannot target an arbitrary recipient: it is locked to the ROOT
  user's own verified address, rate-limited, and fails closed if the provider is
  not ready. Audit entries redact the recipient.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

from src.Util.Seccurity import HTTPBearerOrCookie
from src.Util.activity_logger import ActivityLogger, ActivityType
from src.Util.db import is_root_user
from src.Util.db import db_email_templates
from src.Util.db.db_email import list_user_emails
from src.Util.decorators import log_and_handle_errors
from src.Util.email.config import load_email_config, validate_email_readiness
from src.Util.email.fake_provider import FakeEmailProvider
from src.Util.email.mailpit import MailpitProvider
from src.Util.email.provider import EmailProvider, EmailProviderError, EmailSendRequest
from src.Util.email.rate_limit import EmailRateLimiter, RateLimitExceeded
from src.Util.email.resend_provider import ResendProvider
from src.Util.email.route_support import client_ip, hash_route_value, user_agent
from src.Util.email.security import sanitize_email_log_value
from src.Util.email.templates import (
    DYNAMIC_TEMPLATE_PURPOSES,
    EmailTemplateDisabled,
    EmailTemplateError,
    EmailTemplateLookupError,
    TEMPLATES,
    TRANSACTIONAL_TEMPLATE_CODES,
    TransactionalEmailTemplate,
    allowed_variables,
    render_template_parts,
    resolve_template,
    sample_variables,
)
from src.Util.email.template_validation import TemplateValidationError, validate_template_draft
from src.Util.error_handler import AuthorizationError, ErrorCode, NotFoundError, ValidationError
from src.Util.log_context_models import LogContext

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/email-templates", tags=["Admin - Email Templates"])
security = HTTPBearerOrCookie()

# Cap on test sends per ROOT user (reuses the shared email rate-limiter buckets).
_SEND_TEST_PURPOSE = "email_template_test"
_TEMPLATE_CODE_RE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
_VARIABLE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------
class TemplateDraft(BaseModel):
    subject_template: str
    html_template: str
    text_template: str


class TemplateCreateRequest(TemplateDraft):
    template_code: str = Field(min_length=1, max_length=100)
    purpose: str = Field(min_length=1, max_length=64)
    allowed_variables: list[str] = Field(default_factory=list)
    required_variables: list[str] = Field(default_factory=list)


class TemplatePreviewRequest(BaseModel):
    subject_template: Optional[str] = None
    html_template: Optional[str] = None
    text_template: Optional[str] = None


class TemplateRollbackRequest(BaseModel):
    version: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _require_root(log_context: LogContext) -> None:
    if not is_root_user(log_context.user_id):
        raise AuthorizationError(
            message="ROOT access required to manage email templates",
            error_code=ErrorCode.ACCESS_DENIED,
        )


def _require_known_code(template_code: str) -> str:
    code = str(template_code or "").strip().lower()
    if not code:
        raise NotFoundError(
            message=f"Unknown email template: {sanitize_email_log_value(template_code)}",
            error_code=ErrorCode.RESOURCE_NOT_FOUND,
        )
    return code


def _load_template(code: str, *, allow_disabled: bool = True) -> TransactionalEmailTemplate:
    try:
        return resolve_template(
            code,
            fail_closed_on_db_error=True,
            allow_disabled=allow_disabled,
        )
    except EmailTemplateDisabled as exc:
        raise ValidationError(
            message="Email template is disabled",
            error_code=ErrorCode.INVALID_INPUT,
        ) from exc
    except EmailTemplateLookupError as exc:
        raise ValidationError(
            message="Email template state is unavailable",
            error_code=ErrorCode.INVALID_INPUT,
        ) from exc
    except Exception as exc:
        raise NotFoundError(
            message=f"Unknown email template: {sanitize_email_log_value(code)}",
            error_code=ErrorCode.RESOURCE_NOT_FOUND,
        ) from exc


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat().replace("+00:00", "Z")
    return str(value)


def _audit(log_context: LogContext, action: str, details: Dict[str, Any]) -> None:
    try:
        ActivityLogger.log_activity(
            user_id=log_context.user_id,
            activity_type=ActivityType.ADMIN_ACTION.value,
            details={"action": action, **details},
            ip_address=getattr(log_context, "ip_address", None),
            user_agent=getattr(log_context, "user_agent", None),
        )
    except Exception:  # pragma: no cover - audit must never break the request
        logger.debug("email template audit log failed", exc_info=True)


def _provider_from_config(config) -> EmailProvider:
    if config.provider == "resend":
        return ResendProvider.from_config(config)
    if config.provider == "mailpit":
        return MailpitProvider.from_config(config)
    return FakeEmailProvider()


def _summary(code: str) -> Dict[str, Any]:
    template = _load_template(code, allow_disabled=True)
    return {
        "template_code": code,
        "purpose": template.purpose,
        "subject_template": template.subject_template,
        "source": template.source,  # "db" (customized) or "code" (default)
        "version": template.version,
        "is_customized": template.source == "db",
        "is_enabled": template.is_enabled,
        "is_dynamic": template.is_dynamic,
        "revision": template.revision,
        "disabled_at": template.disabled_at,
        "disabled_by": template.disabled_by,
        "required_variables": list(template.required_variables),
        "allowed_variables": sorted(allowed_variables(code, template.allowed_variables)),
    }


def _resolve_draft(code: str, body: Optional[TemplatePreviewRequest]) -> TransactionalEmailTemplate:
    """Return either the validated draft template or the active resolved one."""

    active = _load_template(code, allow_disabled=True)
    if body is not None and (body.subject_template or body.html_template or body.text_template):
        validate_template_draft(
            template_code=code,
            subject_template=body.subject_template or "",
            html_template=body.html_template or "",
            text_template=body.text_template or "",
            purpose=active.purpose,
            allowed_variable_names=active.allowed_variables,
            required_variable_names=active.required_variables,
        )
        return TransactionalEmailTemplate(
            code=code,
            purpose=active.purpose,
            subject_template=body.subject_template or "",
            html_template=body.html_template or "",
            text_template=body.text_template or "",
            required_variables=active.required_variables,
            allowed_variables=active.allowed_variables,
            is_dynamic=active.is_dynamic,
            is_enabled=active.is_enabled,
            revision=active.revision,
        )
    return active


def _normalize_template_code(value: str) -> str:
    code = str(value or "").strip().lower()
    if not _TEMPLATE_CODE_RE.match(code):
        raise ValidationError(
            message="template_code must be lowercase snake_case",
            error_code=ErrorCode.INVALID_INPUT,
        )
    if code in TEMPLATES or code in TRANSACTIONAL_TEMPLATE_CODES:
        raise ValidationError(
            message="template_code collides with a built-in template",
            error_code=ErrorCode.INVALID_INPUT,
        )
    return code


def _normalize_variable_names(
    values: list[str],
    *,
    field_name: str,
    allow_empty: bool = True,
) -> tuple[str, ...]:
    normalized: list[str] = []
    for value in values or []:
        name = str(value or "").strip()
        if not _VARIABLE_NAME_RE.match(name):
            raise ValidationError(
                message=f"{field_name} contains an invalid template variable name",
                error_code=ErrorCode.INVALID_INPUT,
            )
        if name not in normalized:
            normalized.append(name)
    if not normalized and not allow_empty:
        raise ValidationError(
            message=f"{field_name} must include at least one variable",
            error_code=ErrorCode.INVALID_INPUT,
        )
    return tuple(normalized)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.get("")
@log_and_handle_errors(
    operation_name="list_email_templates",
    activity_type=ActivityType.ADMIN_ACTION,
    log_success=False,
)
async def list_email_templates(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    log_context: LogContext = None,
) -> Dict[str, Any]:
    """List every transactional template with its active source/version."""

    _require_root(log_context)
    rows = db_email_templates.list_active_templates() or []
    codes = set(TEMPLATES)
    codes.update(str(row.get("template_code") or "").strip().lower() for row in rows)
    templates = [_summary(code) for code in sorted(code for code in codes if code)]
    return {"templates": templates, "generated_at": _now_iso()}


@router.post("")
@log_and_handle_errors(
    operation_name="create_email_template",
    activity_type=ActivityType.ADMIN_ACTION,
    log_success=True,
)
async def create_email_template(
    body: TemplateCreateRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    log_context: LogContext = None,
) -> Dict[str, Any]:
    """Create a dynamic internal template code and activate version 1."""

    _require_root(log_context)
    code = _normalize_template_code(body.template_code)
    purpose = str(body.purpose or "").strip().lower()
    if purpose not in DYNAMIC_TEMPLATE_PURPOSES:
        raise ValidationError(
            message="Dynamic templates are limited to internal delivery purposes",
            error_code=ErrorCode.INVALID_INPUT,
        )
    allowed = _normalize_variable_names(body.allowed_variables, field_name="allowed_variables")
    required = _normalize_variable_names(body.required_variables, field_name="required_variables")
    if set(required) - set(allowed):
        raise ValidationError(
            message="required_variables must be a subset of allowed_variables",
            error_code=ErrorCode.INVALID_INPUT,
        )

    try:
        summary = validate_template_draft(
            template_code=code,
            purpose=purpose,
            allowed_variable_names=allowed,
            required_variable_names=required,
            subject_template=body.subject_template,
            html_template=body.html_template,
            text_template=body.text_template,
        )
    except TemplateValidationError as exc:
        raise ValidationError(message=str(exc), error_code=ErrorCode.INVALID_INPUT) from exc

    result = db_email_templates.create_dynamic_template(
        template_id=f"emt-{uuid.uuid4()}",
        template_code=code,
        purpose=purpose,
        allowed_variables=allowed,
        required_variables=required,
        subject_template=body.subject_template,
        html_template=body.html_template,
        text_template=body.text_template,
    )
    _audit(
        log_context,
        "email_template_created",
        {"template_code": code, "purpose": purpose, "version": 1},
    )
    return {
        "success": True,
        "template_code": code,
        "purpose": purpose,
        "version": (result or {}).get("version") or 1,
        "revision": (result or {}).get("revision") or 1,
        "is_dynamic": True,
        "is_enabled": True,
        "used_variables": summary.get("used_variables"),
        "created_at": _now_iso(),
    }


@router.get("/{template_code}")
@log_and_handle_errors(
    operation_name="get_email_template",
    activity_type=ActivityType.ADMIN_ACTION,
    log_success=False,
)
async def get_email_template(
    template_code: str,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    log_context: LogContext = None,
) -> Dict[str, Any]:
    """Return the active body for a code plus its allowlist and version history."""

    _require_root(log_context)
    code = _require_known_code(template_code)
    template = _load_template(code, allow_disabled=True)
    versions = db_email_templates.list_template_versions(code) or []
    payload = {
        "template_code": code,
        "purpose": template.purpose,
        "source": template.source,
        "version": template.version,
        "is_customized": template.source == "db",
        "is_enabled": template.is_enabled,
        "is_dynamic": template.is_dynamic,
        "revision": template.revision,
        "disabled_at": template.disabled_at,
        "disabled_by": template.disabled_by,
        "subject_template": template.subject_template,
        "html_template": template.html_template,
        "text_template": template.text_template,
        "required_variables": list(template.required_variables),
        "allowed_variables": sorted(allowed_variables(code, template.allowed_variables)),
        "default": None if template.is_dynamic else {
            "subject_template": TEMPLATES[code].subject_template,
            "html_template": TEMPLATES[code].html_template,
            "text_template": TEMPLATES[code].text_template,
        },
        "versions": [
            {
                "version": row.get("version"),
                "subject_template": row.get("subject_template"),
                "is_active": bool(row.get("is_active")),
                "created_at": _iso(row.get("created_at")),
            }
            for row in versions
        ],
        "generated_at": _now_iso(),
    }
    return payload


@router.put("/{template_code}")
@log_and_handle_errors(
    operation_name="update_email_template",
    activity_type=ActivityType.ADMIN_ACTION,
    log_success=True,
)
async def update_email_template(
    template_code: str,
    body: TemplateDraft,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    log_context: LogContext = None,
) -> Dict[str, Any]:
    """Validate, sanitize-check and save a new active version of a template."""

    _require_root(log_context)
    code = _require_known_code(template_code)
    previous = _load_template(code, allow_disabled=True)

    try:
        summary = validate_template_draft(
            template_code=code,
            subject_template=body.subject_template,
            html_template=body.html_template,
            text_template=body.text_template,
            purpose=previous.purpose,
            allowed_variable_names=previous.allowed_variables,
            required_variable_names=previous.required_variables,
        )
    except TemplateValidationError as exc:
        raise ValidationError(message=str(exc), error_code=ErrorCode.INVALID_INPUT) from exc

    result = db_email_templates.save_and_activate_template(
        template_id=f"emt-{uuid.uuid4()}",
        template_code=code,
        subject_template=body.subject_template,
        html_template=body.html_template,
        text_template=body.text_template,
    )
    new_version = (result or {}).get("version")

    _audit(
        log_context,
        "email_template_updated",
        {
            "template_code": code,
            "new_version": new_version,
            "previous_version": previous.version,
            "previous_source": previous.source,
        },
    )

    return {
        "success": True,
        "template_code": code,
        "version": new_version,
        "revision": (result or {}).get("revision"),
        "is_enabled": True,
        "used_variables": summary.get("used_variables"),
        "updated_at": _now_iso(),
    }


@router.post("/{template_code}/preview")
@log_and_handle_errors(
    operation_name="preview_email_template",
    activity_type=ActivityType.ADMIN_ACTION,
    log_success=False,
)
async def preview_email_template(
    template_code: str,
    body: TemplatePreviewRequest | None = None,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    log_context: LogContext = None,
) -> Dict[str, Any]:
    """Render a draft (or the active version) with sample data for preview.

    The returned HTML is what the worker would actually send; the dashboard
    renders it inside a script-less sandboxed iframe.
    """

    _require_root(log_context)
    code = _require_known_code(template_code)
    try:
        template = _resolve_draft(code, body)
        rendered = render_template_parts(template, sample_variables(code, template.allowed_variables))
    except (EmailTemplateError, TemplateValidationError) as exc:
        raise ValidationError(message=str(exc), error_code=ErrorCode.INVALID_INPUT) from exc

    return {
        "template_code": code,
        "subject": rendered.subject,
        "html": rendered.html,
        "text": rendered.text,
        "sample_variables": sample_variables(code, template.allowed_variables),
        "generated_at": _now_iso(),
    }


@router.delete("/{template_code}")
@log_and_handle_errors(
    operation_name="disable_email_template",
    activity_type=ActivityType.ADMIN_ACTION,
    log_success=True,
)
async def disable_email_template(
    template_code: str,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    log_context: LogContext = None,
) -> Dict[str, Any]:
    """Disable a template code while preserving catalog/version history."""

    _require_root(log_context)
    code = _require_known_code(template_code)
    previous = _load_template(code, allow_disabled=True)
    result = db_email_templates.disable_template(
        template_code=code,
        disabled_by=getattr(log_context, "user_id", None),
    )
    _audit(
        log_context,
        "email_template_disabled",
        {
            "template_code": code,
            "previous_version": previous.version,
            "previous_revision": previous.revision,
        },
    )
    return {
        "success": True,
        "template_code": code,
        "is_enabled": False,
        "revision": (result or {}).get("revision"),
        "disabled_at": _now_iso(),
    }


@router.post("/{template_code}/send-test")
@log_and_handle_errors(
    operation_name="send_test_email_template",
    activity_type=ActivityType.ADMIN_ACTION,
    log_success=True,
)
async def send_test_email_template(
    template_code: str,
    body: TemplatePreviewRequest | None = None,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    log_context: LogContext = None,
) -> Dict[str, Any]:
    """Send a rendered test email to the ROOT user's OWN verified address."""

    _require_root(log_context)
    code = _require_known_code(template_code)
    active_for_send = _load_template(code, allow_disabled=False)

    # Recipient is locked to the caller's own verified email — never arbitrary.
    emails = list_user_emails(log_context.user_id) or []
    activated = [e for e in emails if str(e.get("status") or "").lower() == "activated"]
    if not activated:
        raise ValidationError(
            message="You have no verified email address on file to receive a test email",
            error_code=ErrorCode.INVALID_INPUT,
        )
    recipient = activated[0]
    recipient_email = str(recipient.get("email_normalized") or "").strip()
    recipient_masked = str(recipient.get("email_masked") or "your address")
    if not recipient_email:
        raise ValidationError(
            message="Your verified email address is unavailable",
            error_code=ErrorCode.INVALID_INPUT,
        )

    config = load_email_config(validate_real_send_guard=True)
    readiness = validate_email_readiness(config)
    if not readiness.ready:
        raise ValidationError(
            message=f"Email delivery is not ready (status: {readiness.status}); cannot send a test",
            error_code=ErrorCode.INVALID_INPUT,
        )

    # Rate-limit test sends per ROOT user (non-PII keys).
    recipient_hash = hash_route_value(recipient_email, config)
    try:
        EmailRateLimiter().check_send_request(
            purpose=_SEND_TEST_PURPOSE,
            recipient_hash=recipient_hash.hex() if recipient_hash else log_context.user_id,
            user_id=log_context.user_id,
            ip_address=getattr(log_context, "ip_address", None) or "unknown",
        )
    except RateLimitExceeded as exc:
        raise ValidationError(
            message="Too many test emails; please wait before sending another",
            error_code=ErrorCode.RATE_LIMIT_EXCEEDED,
        ) from exc

    try:
        template = _resolve_draft(code, body)
        if not template.is_enabled:
            raise ValidationError(message="Email template is disabled", error_code=ErrorCode.INVALID_INPUT)
        message_id = f"emt-test-{uuid.uuid4()}"
        rendered = render_template_parts(
            template,
            sample_variables(code, active_for_send.allowed_variables),
            message_id=message_id,
        )
    except (EmailTemplateError, TemplateValidationError) as exc:
        raise ValidationError(message=str(exc), error_code=ErrorCode.INVALID_INPUT) from exc

    provider = _provider_from_config(config)
    send_request = EmailSendRequest(
        message_id=message_id,
        from_address=config.from_address or "no-reply@example.invalid",
        to=[recipient_email],
        subject=f"[TEST] {rendered.subject}",
        html=rendered.html,
        text=rendered.text,
        headers={**rendered.headers, "X-Email-Template-Test": "true"},
        tags={**rendered.tags, "test": "true"},
        idempotency_key=message_id,
    )
    try:
        provider.send(send_request)
    except EmailProviderError as exc:
        logger.warning("email template test send failed", exc_info=True)
        raise ValidationError(
            message="Test email could not be sent by the provider",
            error_code=ErrorCode.INVALID_INPUT,
        ) from exc

    _audit(
        log_context,
        "email_template_test_sent",
        {"template_code": code, "provider": config.provider, "recipient": "[REDACTED]"},
    )

    return {
        "success": True,
        "template_code": code,
        "recipient_masked": recipient_masked,
        "provider": config.provider,
        "sent_at": _now_iso(),
    }


@router.post("/{template_code}/rollback")
@log_and_handle_errors(
    operation_name="rollback_email_template",
    activity_type=ActivityType.ADMIN_ACTION,
    log_success=True,
)
async def rollback_email_template(
    template_code: str,
    body: TemplateRollbackRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    log_context: LogContext = None,
) -> Dict[str, Any]:
    """Re-activate a prior version of a template."""

    _require_root(log_context)
    code = _require_known_code(template_code)
    state = _load_template(code, allow_disabled=True)

    target = db_email_templates.get_template_version(code, body.version)
    if not target:
        raise NotFoundError(
            message=f"Version {body.version} not found for {code}",
            error_code=ErrorCode.RESOURCE_NOT_FOUND,
        )

    try:
        validate_template_draft(
            template_code=code,
            subject_template=str(target.get("subject_template") or ""),
            html_template=str(target.get("html_template") or ""),
            text_template=str(target.get("text_template") or ""),
            purpose=state.purpose,
            allowed_variable_names=state.allowed_variables,
            required_variable_names=state.required_variables,
        )
    except TemplateValidationError as exc:
        raise ValidationError(message=str(exc), error_code=ErrorCode.INVALID_INPUT) from exc

    previous = state
    result = db_email_templates.rollback_template(template_code=code, version=body.version)

    _audit(
        log_context,
        "email_template_rolled_back",
        {
            "template_code": code,
            "activated_version": body.version,
            "previous_version": previous.version,
        },
    )

    return {
        "success": True,
        "template_code": code,
        "version": body.version,
        "revision": (result or {}).get("revision"),
        "is_enabled": True,
        "rolled_back_at": _now_iso(),
    }
