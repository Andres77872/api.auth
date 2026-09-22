"""URL validation / SSRF guard and secrets-at-rest for provider-agnostic OAuth."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from src.Util.oauth.secrets import (
    KIND_CLIENT_SECRET,
    OAuthSecretError,
    OAuthSecretsNotReady,
    decrypt_secret,
    encrypt_secret,
    reencrypt_secret,
    secret_hmac,
)
from src.Util.oauth.settings import load_oauth_settings
from src.Util.oauth.url_safety import UnsafeURLError, assert_safe_outbound_url, validate_origin, validate_redirect_uri


pytestmark = pytest.mark.unit

PUBLIC = lambda host: ["93.184.216.34"]  # noqa: E731 - tiny resolver double


# ───────────────────────────────────────────────────────── allow-list validation

@pytest.mark.parametrize(
    "url",
    [
        "https://app.example/auth/callback",
        "https://app.example:8443/cb?x=1",
    ],
)
def test_redirect_uri_accepts_exact_https_urls(url):
    assert validate_redirect_uri(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "http://app.example/cb",          # plain http outside localhost
        "https://*.example/cb",           # wildcard
        "https://app.example/cb#frag",    # fragment
        "https://user:pw@app.example/cb",  # credentials
        "/relative/cb",
        "javascript:alert(1)",
        "",
    ],
)
def test_redirect_uri_rejects_unsafe_shapes(url):
    with pytest.raises(UnsafeURLError):
        validate_redirect_uri(url)


def test_http_is_accepted_only_for_localhost_and_only_when_allowed():
    assert validate_redirect_uri("http://localhost:8000/cb", allow_http_localhost=True)
    with pytest.raises(UnsafeURLError):
        validate_redirect_uri("http://localhost:8000/cb", allow_http_localhost=False)
    with pytest.raises(UnsafeURLError):
        validate_redirect_uri("http://evil.example/cb", allow_http_localhost=True)


@pytest.mark.parametrize("origin", ["https://app.example", "https://app.example:8443"])
def test_origin_is_scheme_host_port_only(origin):
    assert validate_origin(origin) == origin


@pytest.mark.parametrize(
    "origin",
    ["https://app.example/", "https://app.example/path", "https://app.example?x=1", "https://*.example", "app.example"],
)
def test_origin_rejects_paths_queries_and_wildcards(origin):
    with pytest.raises(UnsafeURLError):
        validate_origin(origin)


# ─────────────────────────────────────────────────────────────────── SSRF guard

@pytest.mark.parametrize(
    "address",
    ["10.0.0.5", "172.16.3.1", "192.168.1.90", "127.0.0.1", "169.254.169.254", "::1", "fd00::1", "0.0.0.0"],
)
def test_outbound_guard_rejects_hosts_resolving_to_non_public_addresses(address):
    with pytest.raises(UnsafeURLError):
        assert_safe_outbound_url("https://idp.tenant.example/.well-known/openid-configuration", resolver=lambda host: [address])


def test_outbound_guard_rejects_when_any_resolved_address_is_private():
    with pytest.raises(UnsafeURLError):
        assert_safe_outbound_url("https://idp.example/jwks", resolver=lambda host: ["93.184.216.34", "10.0.0.1"])


def test_outbound_guard_rejects_ip_literals_in_private_ranges_without_resolving():
    with pytest.raises(UnsafeURLError):
        assert_safe_outbound_url("https://169.254.169.254/latest/meta-data", resolver=PUBLIC)


def test_outbound_guard_requires_https_and_no_credentials():
    with pytest.raises(UnsafeURLError):
        assert_safe_outbound_url("http://idp.example/jwks", resolver=PUBLIC)
    with pytest.raises(UnsafeURLError):
        assert_safe_outbound_url("https://u:p@idp.example/jwks", resolver=PUBLIC)


def test_outbound_guard_fails_closed_when_resolution_fails():
    def broken(host):
        raise OSError("dns down")

    with pytest.raises(UnsafeURLError):
        assert_safe_outbound_url("https://idp.example/jwks", resolver=broken)


def test_outbound_guard_accepts_public_https_and_has_a_dev_only_relaxation():
    url = "https://idp.example/jwks"
    assert assert_safe_outbound_url(url, resolver=PUBLIC) == url
    assert assert_safe_outbound_url("http://localhost:9000/jwks", allow_private_hosts=True)


# ───────────────────────────────────────────────────────────── secrets at rest

def _settings(**extra):
    env = {
        "OAUTH_SECRET_ENCRYPTION_KEY": Fernet.generate_key().decode(),
        "OAUTH_SECRET_ENCRYPTION_KEY_ID": "oauth-key-1",
        "OAUTH_SECRET_HMAC_KEY": "unit-test-hmac-key-not-real-at-least-32-bytes",
        **extra,
    }
    return load_oauth_settings(env=env)


def test_encrypt_decrypt_round_trip_and_ciphertext_never_contains_plaintext():
    settings = _settings()
    encrypted = encrypt_secret(owner_id="oac-1", kind=KIND_CLIENT_SECRET, value="super-secret-SENTINEL", settings=settings)
    assert b"SENTINEL" not in encrypted.ciphertext
    assert "SENTINEL" not in repr(encrypted)
    assert len(encrypted.digest) == 32 and len(encrypted.fingerprint) == 12
    assert decrypt_secret(
        owner_id="oac-1", kind=KIND_CLIENT_SECRET, ciphertext=encrypted.ciphertext, key_id=encrypted.key_id,
        expected_digest=encrypted.digest, settings=settings,
    ) == "super-secret-SENTINEL"


def test_ciphertext_moved_to_another_row_is_rejected():
    settings = _settings()
    encrypted = encrypt_secret(owner_id="oac-1", kind=KIND_CLIENT_SECRET, value="secret-a", settings=settings)
    with pytest.raises(OAuthSecretError, match="does not belong"):
        decrypt_secret(
            owner_id="oac-2", kind=KIND_CLIENT_SECRET, ciphertext=encrypted.ciphertext, key_id=encrypted.key_id,
            expected_digest=encrypted.digest, settings=settings,
        )


def test_hmac_is_purpose_separated_per_owner_and_kind():
    settings = _settings()
    base = secret_hmac(owner_id="oac-1", kind="client_secret", value="v", settings=settings)
    assert base != secret_hmac(owner_id="oac-2", kind="client_secret", value="v", settings=settings)
    assert base != secret_hmac(owner_id="oac-1", kind="signing_key", value="v", settings=settings)


def test_unknown_key_id_and_missing_keys_fail_closed_without_echoing_material():
    settings = _settings()
    encrypted = encrypt_secret(owner_id="oac-1", kind=KIND_CLIENT_SECRET, value="secret-a", settings=settings)
    with pytest.raises(OAuthSecretsNotReady):
        decrypt_secret(owner_id="oac-1", kind=KIND_CLIENT_SECRET, ciphertext=encrypted.ciphertext, key_id="retired-key", settings=settings)
    with pytest.raises(OAuthSecretsNotReady):
        encrypt_secret(owner_id="oac-1", kind=KIND_CLIENT_SECRET, value="x", settings=load_oauth_settings(env={}))
    with pytest.raises(OAuthSecretError) as excinfo:
        decrypt_secret(owner_id="oac-1", kind=KIND_CLIENT_SECRET, ciphertext=b"not-a-token", key_id="oauth-key-1", settings=settings)
    assert "not-a-token" not in str(excinfo.value)


def test_encryption_key_rotation_keeps_the_row_binding_hmac_stable():
    import json

    old_key = Fernet.generate_key().decode()
    old_settings = _settings(OAUTH_SECRET_ENCRYPTION_KEY=old_key, OAUTH_SECRET_ENCRYPTION_KEY_ID="oauth-key-1")
    original = encrypt_secret(owner_id="oac-1", kind=KIND_CLIENT_SECRET, value="rotate-me", settings=old_settings)

    rotated_settings = _settings(
        OAUTH_SECRET_ENCRYPTION_KEY_ID="oauth-key-2",
        OAUTH_SECRET_DECRYPTION_KEYS_JSON=json.dumps({"oauth-key-1": old_key}),
    )
    rotated = reencrypt_secret(
        owner_id="oac-1", kind=KIND_CLIENT_SECRET, ciphertext=original.ciphertext, key_id=original.key_id,
        expected_digest=original.digest, settings=rotated_settings,
    )
    assert rotated.key_id == "oauth-key-2"
    assert rotated.digest == original.digest, "rotation re-encrypts but must not change the HMAC"
    assert rotated.ciphertext != original.ciphertext
    assert decrypt_secret(
        owner_id="oac-1", kind=KIND_CLIENT_SECRET, ciphertext=rotated.ciphertext, key_id=rotated.key_id,
        expected_digest=rotated.digest, settings=rotated_settings,
    ) == "rotate-me"
