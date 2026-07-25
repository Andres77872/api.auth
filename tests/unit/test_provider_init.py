"""Focused unit coverage for server-side provider-init redemption."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from src.Util.google_oauth_config import load_google_oauth_config
from src.Util.provider_init import (
    MAX_PROVIDER_INIT_TTL_SECONDS,
    ProviderInitRedeemError,
    fingerprint_provider_init_token,
    redeem_provider_init_token,
    redeem_provider_init_token_sync,
    validate_provider_init_binding,
)


RETURN_ORIGIN = "https://app.example.test"
ALTERNATE_RETURN_ORIGIN = "https://alternate.example.test"
REDEEM_URL = "https://companion.example.test/internal/provider-init/redeem"
REDEEM_BEARER = "test-companion-bearer-secret-never-log"
OPAQUE_TOKEN = "opaque-provider-init-secret-never-log"
PROJECT_HASH = "project-hash-secret-never-log"
USER_GROUP_HASH = "user-group-hash-secret-never-log"


class StubResponse:
    def __init__(self, *, status_code: int = 200, payload=None, json_error: Exception | None = None) -> None:
        self.status_code = status_code
        self._payload = payload
        self._json_error = json_error

    def json(self):
        if self._json_error is not None:
            raise self._json_error
        return self._payload


def _config():
    return load_google_oauth_config(
        env={
            "APP_ENV": "test",
            "GOOGLE_OAUTH_SCOPES": "openid email",
            "GOOGLE_OAUTH_RETURN_ORIGINS": f"{RETURN_ORIGIN},{ALTERNATE_RETURN_ORIGIN}",
            "PROVIDER_INIT_REDEEM_URL": REDEEM_URL,
            "PROVIDER_INIT_REDEEM_TOKEN": REDEEM_BEARER,
            "PROVIDER_INIT_RETURN_ORIGINS": f"{RETURN_ORIGIN},{ALTERNATE_RETURN_ORIGIN}",
        }
    )


def _payload(**overrides):
    payload = {
        "active": True,
        "signature_valid": True,
        "provider": "google",
        "audience": "api.auth",
        "purpose": "login",
        "return_origin": RETURN_ORIGIN,
        "project_hash": PROJECT_HASH,
        "user_group_hash": USER_GROUP_HASH,
        "expires_in": 300,
        "issuer": "companion.example.test",
        "scope_fingerprint": "scope-fingerprint-test-only",
    }
    payload.update(overrides)
    return payload


def test_redeem_posts_exactly_once_and_binds_provider_audience_purpose_and_origin():
    post = MagicMock(return_value=StubResponse(payload=_payload()))

    binding = redeem_provider_init_token_sync(
        OPAQUE_TOKEN,
        config=_config(),
        expected_purpose="login",
        return_origin=RETURN_ORIGIN,
        http_post=post,
        timeout_seconds=2.5,
    )

    post.assert_called_once()
    args, kwargs = post.call_args
    assert args == (REDEEM_URL,)
    assert kwargs == {
        "headers": {
            "Authorization": f"Bearer {REDEEM_BEARER}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        "json": {
            "provider_init_token": OPAQUE_TOKEN,
            "provider": "google",
            "audience": "api.auth",
        },
        "timeout": 2.5,
    }
    assert binding.provider == "google"
    assert binding.audience == "api.auth"
    assert binding.purpose == "login"
    assert binding.return_origin == RETURN_ORIGIN
    assert binding.project_hash == PROJECT_HASH
    assert binding.user_group_hash == USER_GROUP_HASH
    assert binding.provider_init_fingerprint == fingerprint_provider_init_token(OPAQUE_TOKEN)
    assert binding.as_state_binding(redirect_uri="https://auth.example.test/callback") == {
        "provider": "google",
        "purpose": "login",
        "project_hash": PROJECT_HASH,
        "user_group_hash": USER_GROUP_HASH,
        "return_origin": RETURN_ORIGIN,
        "provider_init_fingerprint": fingerprint_provider_init_token(OPAQUE_TOKEN),
        "scope_fingerprint": "scope-fingerprint-test-only",
        "redirect_uri": "https://auth.example.test/callback",
    }


@pytest.mark.asyncio
async def test_async_redeem_wrapper_still_performs_one_http_redemption():
    post = MagicMock(return_value=StubResponse(payload=_payload()))

    binding = await redeem_provider_init_token(
        OPAQUE_TOKEN,
        config=_config(),
        expected_purpose="login",
        return_origin=RETURN_ORIGIN,
        http_post=post,
    )

    assert binding.project_hash == PROJECT_HASH
    post.assert_called_once()


@pytest.mark.parametrize(
    ("payload_overrides", "call_overrides", "reason"),
    [
        ({"provider": "github"}, {}, "provider_init_provider_mismatch"),
        ({"audience": "another.service"}, {}, "provider_init_audience_mismatch"),
        ({"purpose": "unsupported"}, {}, "provider_init_purpose_invalid"),
        ({"purpose": "link"}, {"expected_purpose": "login"}, "provider_init_purpose_mismatch"),
        ({"return_origin": "https://evil.example.test"}, {}, "provider_init_return_origin_denied"),
        (
            {"return_origin": RETURN_ORIGIN},
            {"requested_return_origin": ALTERNATE_RETURN_ORIGIN},
            "provider_init_return_origin_mismatch",
        ),
    ],
)
def test_binding_rejects_provider_audience_purpose_and_origin_mismatches(
    payload_overrides,
    call_overrides,
    reason,
):
    with pytest.raises(ProviderInitRedeemError) as exc:
        validate_provider_init_binding(
            _payload(**payload_overrides),
            config=_config(),
            token_fingerprint="safe-token-fingerprint",
            **call_overrides,
        )

    assert exc.value.reason == reason
    assert exc.value.token_fingerprint == "safe-token-fingerprint"


def test_redeem_maps_timeout_or_transport_failure_without_leaking_secrets():
    post = MagicMock(side_effect=TimeoutError(f"timeout while sending {REDEEM_BEARER}"))

    with pytest.raises(ProviderInitRedeemError) as exc:
        redeem_provider_init_token_sync(
            OPAQUE_TOKEN,
            config=_config(),
            http_post=post,
        )

    post.assert_called_once()
    assert exc.value.reason == "provider_init_timeout_or_unavailable"
    assert exc.value.token_fingerprint == fingerprint_provider_init_token(OPAQUE_TOKEN)
    rendered = f"{exc.value!r} {exc.value}"
    assert OPAQUE_TOKEN not in rendered
    assert REDEEM_BEARER not in rendered


@pytest.mark.parametrize("status_code", [400, 401, 429, 500])
def test_redeem_rejects_every_non_2xx_response(status_code):
    post = MagicMock(return_value=StubResponse(status_code=status_code, payload=_payload()))

    with pytest.raises(ProviderInitRedeemError) as exc:
        redeem_provider_init_token_sync(OPAQUE_TOKEN, config=_config(), http_post=post)

    post.assert_called_once()
    assert exc.value.reason == "provider_init_http_rejected"


@pytest.mark.parametrize(
    "response",
    [
        StubResponse(json_error=ValueError("not json")),
        StubResponse(payload=["not", "an", "object"]),
        StubResponse(payload="not an object"),
    ],
)
def test_redeem_rejects_bad_json_or_non_object_payload(response):
    post = MagicMock(return_value=response)

    with pytest.raises(ProviderInitRedeemError) as exc:
        redeem_provider_init_token_sync(OPAQUE_TOKEN, config=_config(), http_post=post)

    post.assert_called_once()
    assert exc.value.reason == "provider_init_malformed_response"


@pytest.mark.parametrize("expires_in", ["not-an-integer", 0, -1, True, 1.5])
def test_binding_rejects_malformed_non_integral_or_non_positive_ttl(expires_in):
    with pytest.raises(ProviderInitRedeemError) as exc:
        validate_provider_init_binding(
            _payload(expires_in=expires_in),
            config=_config(),
            token_fingerprint="safe-token-fingerprint",
        )

    assert exc.value.reason == "provider_init_expired_or_ttl_invalid"


@pytest.mark.parametrize(
    "ttl_fields",
    [
        {},
        {"expires_at": "not-a-timestamp"},
        {"expires_at": ""},
        {"expires_at": datetime.now(timezone.utc) + timedelta(hours=1)},
    ],
)
def test_binding_rejects_missing_malformed_or_overlong_absolute_ttl(ttl_fields):
    payload = _payload()
    payload.pop("expires_in")
    payload.update(ttl_fields)

    with pytest.raises(ProviderInitRedeemError) as exc:
        validate_provider_init_binding(
            payload,
            config=_config(),
            token_fingerprint="safe-token-fingerprint",
        )

    assert exc.value.reason == "provider_init_expired_or_ttl_invalid"


def test_binding_enforces_max_ttl_and_expired_absolute_timestamp():
    accepted = validate_provider_init_binding(
        _payload(expires_in=MAX_PROVIDER_INIT_TTL_SECONDS),
        config=_config(),
    )
    assert accepted.expires_in == MAX_PROVIDER_INIT_TTL_SECONDS

    with pytest.raises(ProviderInitRedeemError, match="provider_init_expired_or_ttl_invalid"):
        validate_provider_init_binding(
            _payload(expires_in=MAX_PROVIDER_INIT_TTL_SECONDS + 1),
            config=_config(),
        )

    with pytest.raises(ProviderInitRedeemError, match="provider_init_expired_or_ttl_invalid"):
        validate_provider_init_binding(
            _payload(
                expires_in=30,
                expires_at=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
            ),
            config=_config(),
        )

    accepted_absolute = validate_provider_init_binding(
        _payload(
            expires_in=None,
            expires_at=(datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat(),
        ),
        config=_config(),
    )
    assert accepted_absolute.expires_at is not None


def test_binding_and_errors_redact_tokens_and_strict_hashes_from_repr():
    payload = _payload(companion_secret="payload-secret-never-log")
    binding = validate_provider_init_binding(
        payload,
        config=_config(),
        token_fingerprint=fingerprint_provider_init_token(OPAQUE_TOKEN),
    )

    binding_repr = repr(binding)
    for secret in (
        OPAQUE_TOKEN,
        REDEEM_BEARER,
        PROJECT_HASH,
        USER_GROUP_HASH,
        "payload-secret-never-log",
    ):
        assert secret not in binding_repr

    with pytest.raises(ProviderInitRedeemError) as exc:
        validate_provider_init_binding(
            _payload(provider="github", companion_secret="payload-secret-never-log"),
            config=_config(),
            token_fingerprint=fingerprint_provider_init_token(OPAQUE_TOKEN),
        )
    error_repr = f"{exc.value!r} {exc.value}"
    for secret in (OPAQUE_TOKEN, PROJECT_HASH, USER_GROUP_HASH, "payload-secret-never-log"):
        assert secret not in error_repr
