"""Security and compatibility contracts for credential-bearing email URLs."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException, Request
from starlette.datastructures import Headers

from src.Util.email.route_support import (
    PUBLIC_BASE_URL_HEADER,
    _normalize_origin,
    allowed_link_origins,
    link_url,
    make_link_token_and_payload,
    public_base_url,
)
from src.Util.error_handler import ErrorCode, ValidationError


class _Req:
    def __init__(self, base_url: str, headers: dict | None = None) -> None:
        self.base_url = base_url
        self.headers = Headers(headers or {})


@pytest.fixture(autouse=True)
def origin_env(monkeypatch):
    for name in ("AUTH_EMAIL_PUBLIC_BASE_URL", "PUBLIC_AUTH_BASE_URL", "BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv(
        "ALLOWED_ORIGINS",
        "http://localhost:5000,http://localhost:5173,http://192.168.1.13:5173,"
        "https://app-one.example,https://app-two.example",
    )


@pytest.mark.parametrize("origin", ["https://app-one.example", "https://app-two.example", "http://192.168.1.13:5173"])
def test_approved_frontend_overrides_untrusted_authority(origin):
    req = _Req("http://evil.example/", {PUBLIC_BASE_URL_HEADER: origin})
    assert link_url(req, "/auth/password/reset", "lookup.secret") == f"{origin}/auth/password/reset?token=lookup.secret"


def test_request_authority_requires_exact_allowlisting():
    assert public_base_url(_Req("http://localhost:5000/")) == "http://localhost:5000"
    for base in ("http://evil.example/", "http://0.0.0.0:5000/", "http://localhost:5001/", "https://app-one.example.evil.test/"):
        with pytest.raises(ValidationError) as error:
            public_base_url(_Req(base))
        assert error.value.error_code == ErrorCode.INVALID_INPUT


def test_real_request_host_header_cannot_poison_a_link():
    req = Request({
        "type": "http", "scheme": "https", "path": "/auth/password/forgot",
        "root_path": "", "query_string": b"", "server": ("app-one.example", 443),
        "headers": [(b"host", b"attacker.example")],
    })
    with pytest.raises(ValidationError):
        link_url(req, "/auth/password/reset", "lookup.secret")


BAD_ORIGINS = [
    "not a url", "javascript:alert(1)", "ftp://app-one.example", "//app-one.example",
    "http://0.0.0.0:5000", "http://[::]/", "http://[0:0:0:0:0:0:0:0]/",
    "https://user@app-one.example", "https://user:pass@app-one.example",
    "https://app-one.example@evil.example", "https://app-one.example:bad",
    "https://app-one.example:65536", "https://app-one.example:0", "https://app-one.example:",
    "https://app-one.example/path", "https://app-one.example?token=secret",
    "https://app-one.example?", "https://app-one.example#", "https://app-one.example/#fragment",
    "https://app-one.example\r\n.evil.example", "https://app-one.example\t",
    "https://app-one.example\x7f", "https://app-one.example\\evil.example",
    "https://*.example", "https://app-one.example,evil.example", "https://%61pp-one.example",
    "https://[::1]evil.example", "https://[::1%25eth0]", "https://.example", "https://-example", "",
]


@pytest.mark.parametrize("bad", BAD_ORIGINS)
def test_malformed_or_untrusted_header_cannot_authorize_an_untrusted_host(bad):
    with pytest.raises(ValidationError):
        public_base_url(_Req("http://evil.example/", {PUBLIC_BASE_URL_HEADER: bad}))


@pytest.mark.parametrize("bad", [value for value in BAD_ORIGINS if "," not in value])
def test_malformed_allowlist_entries_cannot_establish_trust(monkeypatch, bad):
    monkeypatch.setenv("ALLOWED_ORIGINS", bad)
    with pytest.raises(HTTPException) as error:
        public_base_url(_Req("https://app-one.example/"))
    assert error.value.status_code == 503


@pytest.mark.parametrize("bad", [value for value in BAD_ORIGINS if value and value != "https://app-one.example/path"])
def test_invalid_pin_cannot_fall_back_to_request_input(monkeypatch, bad):
    monkeypatch.setenv("AUTH_EMAIL_PUBLIC_BASE_URL", bad)
    with pytest.raises(HTTPException) as error:
        public_base_url(_Req("https://app-one.example/"))
    assert error.value.status_code == 503


def test_rejected_header_can_only_fall_back_to_a_trusted_request_origin():
    req = _Req("http://localhost:5000/", {PUBLIC_BASE_URL_HEADER: "https://evil.example"})
    assert public_base_url(req) == "http://localhost:5000"


@pytest.mark.parametrize("configured", ["*", "", "ftp://app-one.example", "https://user@app-one.example"])
def test_configuration_without_trusted_origins_is_unavailable(monkeypatch, configured):
    monkeypatch.setenv("ALLOWED_ORIGINS", configured)
    with pytest.raises(HTTPException) as error:
        public_base_url(_Req("https://evil.example/", {PUBLIC_BASE_URL_HEADER: "https://evil.example"}))
    assert error.value.status_code == 503


def test_wildcard_does_not_expand_an_explicit_allowlist(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", "*,https://app-one.example")
    assert allowed_link_origins() == {"https://app-one.example"}
    assert public_base_url(_Req("https://app-one.example/")) == "https://app-one.example"
    with pytest.raises(ValidationError):
        public_base_url(_Req("https://evil.example/", {PUBLIC_BASE_URL_HEADER: "https://evil.example"}))


@pytest.mark.parametrize("environment", ["prod", "production", "stage", "staging", "unknown", ""])
def test_https_required_outside_explicit_development_and_test(monkeypatch, environment):
    monkeypatch.setenv("APP_ENV", environment)
    req = _Req("http://localhost:5000/", {PUBLIC_BASE_URL_HEADER: "http://localhost:5173"})
    with pytest.raises(ValidationError):
        public_base_url(req)
    req.headers = Headers({PUBLIC_BASE_URL_HEADER: "https://app-two.example"})
    assert public_base_url(req) == "https://app-two.example"
    monkeypatch.setenv("AUTH_EMAIL_PUBLIC_BASE_URL", "http://localhost:5173")
    with pytest.raises(HTTPException) as error:
        public_base_url(req)
    assert error.value.status_code == 503


@pytest.mark.parametrize("environment", ["dev", "development", "local", "test", "testing", "pytest"])
def test_explicit_development_and_test_allow_trusted_http(monkeypatch, environment):
    monkeypatch.setenv("APP_ENV", environment)
    assert public_base_url(_Req("http://localhost:5000/")) == "http://localhost:5000"


def test_production_never_uses_the_builtin_development_allowlist(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("ALLOWED_ORIGINS")
    with pytest.raises(HTTPException) as error:
        public_base_url(_Req("https://auth-ui.arz.ai/"))
    assert error.value.status_code == 503


def test_no_implicit_localhost_for_missing_request():
    with pytest.raises(ValidationError):
        public_base_url(None)


@pytest.mark.parametrize("name", ["AUTH_EMAIL_PUBLIC_BASE_URL", "PUBLIC_AUTH_BASE_URL", "BASE_URL"])
def test_pin_aliases_and_path_prefix_override_all_request_input(monkeypatch, name):
    monkeypatch.setenv(name, "https://pinned.example/auth-ui/")
    monkeypatch.setenv("ALLOWED_ORIGINS", "*")
    req = _Req("http://evil.example/", {PUBLIC_BASE_URL_HEADER: "https://evil.example"})
    assert link_url(req, "auth/email/verify", "lookup.secret") == "https://pinned.example/auth-ui/auth/email/verify?token=lookup.secret"
    assert public_base_url(None) == "https://pinned.example/auth-ui"


def test_preferred_pin_is_not_bypassed_by_a_valid_alias(monkeypatch):
    monkeypatch.setenv("AUTH_EMAIL_PUBLIC_BASE_URL", "https://user@evil.example")
    monkeypatch.setenv("PUBLIC_AUTH_BASE_URL", "https://trusted.example")
    with pytest.raises(HTTPException) as error:
        public_base_url(None)
    assert error.value.status_code == 503


def test_pin_precedence(monkeypatch):
    monkeypatch.setenv("AUTH_EMAIL_PUBLIC_BASE_URL", "https://first.example")
    monkeypatch.setenv("PUBLIC_AUTH_BASE_URL", "https://second.example")
    monkeypatch.setenv("BASE_URL", "https://third.example")
    assert public_base_url(None) == "https://first.example"
    monkeypatch.delenv("AUTH_EMAIL_PUBLIC_BASE_URL")
    assert public_base_url(None) == "https://second.example"


@pytest.mark.parametrize("url,expected", [
    ("HTTPS://APP-ONE.EXAMPLE:443/", "https://app-one.example"),
    ("http://localhost:80/", "http://localhost"),
    ("https://[2001:db8::1]:8443/", "https://[2001:db8::1]:8443"),
    ("https://app-one.example:8443", "https://app-one.example:8443"),
    (None, None),
])
def test_origin_normalization(url, expected):
    assert _normalize_origin(url) == expected


def test_untrusted_origin_rejected_before_token_generation(caplog):
    with patch("src.Util.email.route_support.generate_link_token") as generate:
        with pytest.raises(ValidationError):
            make_link_token_and_payload(
                purpose="password_reset", config=SimpleNamespace(),
                request=_Req("https://evil.example/?token=do-not-log"),
            )
    generate.assert_not_called()
    assert "evil.example" not in caplog.text
    assert "do-not-log" not in caplog.text
