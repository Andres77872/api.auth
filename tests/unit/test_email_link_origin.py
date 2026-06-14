"""Unit tests for agnostic email-link origin resolution.

`public_base_url()` must build activation/reset links from the end-user's real
browser origin (relayed by the BFF via `X-Public-Base-Url`), never from this
service's own bind address (e.g. `0.0.0.0:5000`). The forwarded origin is honored
only when it is well-formed and present in `ALLOWED_ORIGINS`, so an attacker can't
inject an arbitrary host into emailed links.
"""

from __future__ import annotations

import pytest
from starlette.datastructures import Headers

from src.Util.email.route_support import (
    PUBLIC_BASE_URL_HEADER,
    _normalize_origin,
    link_url,
    public_base_url,
)


class _Req:
    """Minimal stand-in for a Starlette Request (case-insensitive headers)."""

    def __init__(self, base_url: str, headers: dict | None = None) -> None:
        self.base_url = base_url
        self.headers = Headers(headers or {})


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    for var in ("AUTH_EMAIL_PUBLIC_BASE_URL", "PUBLIC_AUTH_BASE_URL", "BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv(
        "ALLOWED_ORIGINS", "http://localhost:5173,http://192.168.1.13:5173"
    )
    yield


def test_forwarded_origin_is_used_over_bind_address():
    # The exact bug: base_url is the unreachable bind address, but the BFF relays
    # the real browser origin — the link must use the latter.
    req = _Req(
        "http://0.0.0.0:5000/",
        {PUBLIC_BASE_URL_HEADER: "http://192.168.1.13:5173"},
    )
    assert public_base_url(req) == "http://192.168.1.13:5173"


def test_link_url_never_emits_bind_address():
    req = _Req(
        "http://0.0.0.0:5000/",
        {PUBLIC_BASE_URL_HEADER: "http://192.168.1.13:5173"},
    )
    url = link_url(req, "/auth/email/verify", "lid.secret")
    assert url == "http://192.168.1.13:5173/auth/email/verify?token=lid.secret"
    assert "0.0.0.0" not in url


def test_unlisted_forwarded_origin_is_ignored():
    req = _Req(
        "http://localhost:5000/",
        {PUBLIC_BASE_URL_HEADER: "http://evil.example:9999"},
    )
    # Not in the allowlist → ignored → falls back to the sanitized request host.
    assert public_base_url(req) == "http://localhost:5000"


@pytest.mark.parametrize(
    "bad",
    ["not a url", "javascript:alert(1)", "http://0.0.0.0:5000", "ftp://x.example", ""],
)
def test_malformed_forwarded_origin_is_ignored(bad):
    req = _Req("http://localhost:5000/", {PUBLIC_BASE_URL_HEADER: bad})
    assert public_base_url(req) == "http://localhost:5000"


def test_bind_address_base_without_header_falls_to_default():
    # No usable signal at all → safe default, never an unreachable 0.0.0.0 link.
    assert public_base_url(_Req("http://0.0.0.0:5000/")) == "http://localhost"


def test_valid_base_without_header_is_used():
    assert public_base_url(_Req("http://localhost:5000/")) == "http://localhost:5000"


def test_env_pin_overrides_everything(monkeypatch):
    monkeypatch.setenv("AUTH_EMAIL_PUBLIC_BASE_URL", "https://pinned.example.com/")
    req = _Req(
        "http://0.0.0.0:5000/",
        {PUBLIC_BASE_URL_HEADER: "http://192.168.1.13:5173"},
    )
    assert public_base_url(req) == "https://pinned.example.com"


def test_wildcard_allowlist_accepts_any_forwarded_origin(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", "*")
    req = _Req(
        "http://0.0.0.0:5000/",
        {PUBLIC_BASE_URL_HEADER: "https://anything.example:1234"},
    )
    assert public_base_url(req) == "https://anything.example:1234"


def test_none_request_returns_default():
    assert public_base_url(None) == "http://localhost"


@pytest.mark.parametrize(
    "url,expected",
    [
        ("http://0.0.0.0:5000/", None),
        ("http://[::]/", None),
        ("http://localhost:5000/", "http://localhost:5000"),
        ("https://app.example.com", "https://app.example.com"),
        ("http://192.168.1.13:5173", "http://192.168.1.13:5173"),
        ("ftp://x.example", None),
        ("garbage", None),
        ("", None),
        (None, None),
    ],
)
def test_normalize_origin(url, expected):
    assert _normalize_origin(url) == expected
