"""Real webhook handlers reject oversized input before provider/config/mutation work."""

from unittest.mock import patch

import pytest

from src.middleware.body_limit import MAX_REQUEST_BODY_BYTES, RequestBodyLimitMiddleware
from src.routes import email_webhooks, patreon_webhooks, stripe_webhooks


def test_production_body_guard_precedes_every_body_reader(app):
    assert app.user_middleware[0].cls is RequestBodyLimitMiddleware
    names = [middleware.cls.__name__ for middleware in app.user_middleware]
    assert names.index("APIAuditMiddleware") < names.index("RequestValidationMiddleware")


@pytest.mark.large_payload
@pytest.mark.parametrize("declared", [False, True])
@pytest.mark.parametrize("path,module,seam", [
    ("/webhooks/email/resend", email_webhooks, "verify_resend_webhook"),
    ("/webhooks/patreon", patreon_webhooks, "load_patreon_config"),
    ("/webhooks/stripe/unknown-group", stripe_webhooks, "load_stripe_config"),
])
async def test_oversized_real_webhook_stops_before_verification_or_disabled_gate(client, declared, path, module, seam):
    yielded = 0
    total = 9 * 1024 * 1024

    async def chunks():
        nonlocal yielded
        for _ in range(total // (64 * 1024)):
            yielded += 64 * 1024
            yield b"x" * (64 * 1024)

    headers = {"User-Agent": "bounded-webhook-test", "Content-Type": "application/json",
               "svix-id": "fake-id", "svix-timestamp": "0", "svix-signature": "fake-signature"}
    if declared:
        headers["Content-Length"] = str(total)
    with patch.object(module, seam) as business_work:
        response = await client.post(path, content=chunks(), headers=headers)
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "VAL_3010"
    business_work.assert_not_called()
    assert yielded == (0 if declared else MAX_REQUEST_BODY_BYTES + 64 * 1024)

