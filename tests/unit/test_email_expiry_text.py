"""Link emails state the configured link lifetime, not a fixed "24 hours" / "1 hour".

Regression: `make_link_token_and_payload` hard-coded the `expires_in` text, so a
changed `EMAIL_ACTIVATION_TOKEN_TTL_SECONDS` or `EMAIL_PASSWORD_RESET_TOKEN_TTL_SECONDS`
produced links whose real expiry disagreed with the email body.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from src.Util.email.route_support import expiry_text, make_link_token_and_payload
from src.Util.email.security import decrypt_render_payload


PAYLOAD_KEY = "MTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTE="


@pytest.mark.parametrize(
    "seconds, text",
    [
        (86_400, "24 hours"),
        (3_600, "1 hour"),
        (7_200, "2 hours"),
        (1_800, "30 minutes"),
        (60, "1 minute"),
        (5_400, "90 minutes"),
        (172_800, "2 days"),
        (259_200, "3 days"),
        (3_601, "60 minutes"),
        (45, "45 seconds"),
    ],
)
def test_expiry_text(seconds, text):
    assert expiry_text(seconds) == text


@pytest.mark.parametrize(
    "purpose, ttl_field, ttl, expected",
    [
        ("email_activation", "activation_token_ttl_seconds", 172_800, "2 days"),
        ("password_reset", "password_reset_token_ttl_seconds", 900, "15 minutes"),
    ],
)
def test_link_payload_uses_the_configured_ttl(purpose, ttl_field, ttl, expected):
    config = SimpleNamespace(
        activation_token_ttl_seconds=86_400,
        password_reset_token_ttl_seconds=3_600,
        token_pepper_bytes=b"unit-token-pepper-not-real-0123456789",
        payload_key=PAYLOAD_KEY,
    )
    setattr(config, ttl_field, ttl)

    generated, encrypted = make_link_token_and_payload(
        purpose=purpose, config=config, request=None, recipient_email="user@example.com"
    )

    assert decrypt_render_payload(encrypted, key=PAYLOAD_KEY)["expires_in"] == expected
    assert abs((generated.expires_at - datetime.now(timezone.utc)).total_seconds() - ttl) < 30
