"""Transactional auth email package.

This package contains the Phase 4 foundation for email activation and
password-reset delivery.  It intentionally exposes only provider-neutral
helpers here; routes and workers consume these modules without importing a
concrete provider unless configuration selects one.
"""

from src.Util.email.config import (
    EmailConfig,
    EmailConfigError,
    EmailReadiness,
    is_explicit_test_runtime,
    load_email_config,
    validate_email_readiness,
)
from src.Util.email.provider import (
    EmailProvider,
    EmailProviderError,
    EmailSendRequest,
    EmailSendResult,
    WebhookVerificationError,
)
from src.Util.email.idempotency import (
    EmailIdempotencyManager,
    IdempotencyKeyError,
    IdempotencyRecord,
    hash_idempotency_key,
    request_fingerprint,
    validate_idempotency_key,
)
from src.Util.email.rate_limit import (
    EmailRateLimiter,
    RateLimitDecision,
    RateLimitExceeded,
    RateLimitPolicy,
)
from src.Util.email.security import (
    GeneratedLinkToken,
    decrypt_render_payload,
    encrypt_render_payload,
    generate_link_token,
    hash_email,
    hash_link_token,
    mask_email,
    normalize_email,
    parse_link_token,
    purge_render_payload_if_due,
    sanitize_email_log_value,
    verify_link_token,
)
from src.Util.email.templates import (
    EmailTemplateDisabled,
    EmailTemplateError,
    EmailTemplateLookupError,
    RenderedEmailTemplate,
    TransactionalEmailTemplate,
    get_transactional_template,
    render_email_template,
    render_transactional_template,
)

__all__ = [
    "EmailConfig",
    "EmailConfigError",
    "EmailProvider",
    "EmailProviderError",
    "EmailRateLimiter",
    "EmailReadiness",
    "EmailSendRequest",
    "EmailSendResult",
    "EmailTemplateDisabled",
    "EmailTemplateError",
    "EmailTemplateLookupError",
    "GeneratedLinkToken",
    "IdempotencyKeyError",
    "IdempotencyRecord",
    "RateLimitDecision",
    "RateLimitExceeded",
    "RateLimitPolicy",
    "RenderedEmailTemplate",
    "TransactionalEmailTemplate",
    "WebhookVerificationError",
    "decrypt_render_payload",
    "encrypt_render_payload",
    "generate_link_token",
    "get_transactional_template",
    "hash_email",
    "hash_idempotency_key",
    "hash_link_token",
    "is_explicit_test_runtime",
    "load_email_config",
    "mask_email",
    "normalize_email",
    "parse_link_token",
    "purge_render_payload_if_due",
    "render_email_template",
    "render_transactional_template",
    "request_fingerprint",
    "sanitize_email_log_value",
    "validate_idempotency_key",
    "validate_email_readiness",
    "verify_link_token",
]
