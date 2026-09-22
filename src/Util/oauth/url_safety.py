"""URL validation for allow-lists and SSRF guarding for outbound provider fetches.

Two distinct jobs:

* ``validate_redirect_uri`` / ``validate_origin`` -- shape checks applied when an
  administrator adds an allow-list row. Matching at request time is always exact
  string equality; there is no prefix, wildcard or pattern matching anywhere.
* ``assert_safe_outbound_url`` -- applied before ``api.auth`` fetches a URL that
  came from configuration (discovery, JWKS, token, userinfo, legacy redeem).
  Rejects non-HTTPS and hosts that resolve to private, loopback, link-local or
  metadata ranges, so a tenant-supplied URL cannot be pointed at internal
  services.
"""

from __future__ import annotations

import ipaddress
import socket
from typing import Callable, Iterable
from urllib.parse import urlsplit


_LOCAL_DEV_HOSTS = {"localhost", "127.0.0.1", "::1"}


class UnsafeURLError(ValueError):
    """Raised when a URL fails shape validation or the SSRF guard."""


def _split(url: str):
    try:
        parts = urlsplit(str(url or "").strip())
    except ValueError as exc:
        raise UnsafeURLError("URL is malformed") from exc
    if not parts.scheme or not parts.hostname:
        raise UnsafeURLError("URL must be absolute")
    return parts


def _require_scheme(parts, *, allow_http_localhost: bool) -> None:
    scheme = parts.scheme.lower()
    if scheme == "https":
        return
    if scheme == "http" and allow_http_localhost and (parts.hostname or "").lower() in _LOCAL_DEV_HOSTS:
        return
    raise UnsafeURLError("URL must use https")


def validate_redirect_uri(url: str, *, allow_http_localhost: bool = False) -> str:
    """Validate an allow-listed redirect URI and return it unchanged."""

    text = str(url or "").strip()
    parts = _split(text)
    _require_scheme(parts, allow_http_localhost=allow_http_localhost)
    if "*" in text:
        raise UnsafeURLError("Redirect URI must not contain wildcards")
    if parts.fragment or text.endswith("#"):
        raise UnsafeURLError("Redirect URI must not contain a fragment")
    if parts.username or parts.password:
        raise UnsafeURLError("Redirect URI must not contain credentials")
    return text


def validate_origin(origin: str, *, allow_http_localhost: bool = False) -> str:
    """Validate an allow-listed origin: scheme + host + optional port, nothing else."""

    text = str(origin or "").strip()
    parts = _split(text)
    _require_scheme(parts, allow_http_localhost=allow_http_localhost)
    if "*" in text:
        raise UnsafeURLError("Origin must not contain wildcards")
    if parts.path not in ("", ) or parts.query or parts.fragment or parts.username or parts.password:
        raise UnsafeURLError("Origin must be scheme://host[:port] only")
    if text.endswith("/"):
        raise UnsafeURLError("Origin must not end with a slash")
    return text


def _is_forbidden_address(address: ipaddress._BaseAddress) -> bool:
    return bool(
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
        or getattr(address, "is_site_local", False)
    )


def _default_resolver(host: str) -> Iterable[str]:
    infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    return [info[4][0] for info in infos]


def assert_safe_outbound_url(
    url: str,
    *,
    allow_private_hosts: bool = False,
    resolver: Callable[[str], Iterable[str]] | None = None,
) -> str:
    """Fail closed unless ``url`` is HTTPS and resolves only to public addresses.

    ``allow_private_hosts`` is a development-only relaxation
    (``OAUTH_ALLOW_PRIVATE_IDP_HOSTS``) for local IdPs and test doubles.
    """

    text = str(url or "").strip()
    parts = _split(text)
    if parts.username or parts.password:
        raise UnsafeURLError("Outbound URL must not contain credentials")
    if allow_private_hosts:
        if parts.scheme.lower() not in {"https", "http"}:
            raise UnsafeURLError("Outbound URL must use http or https")
        return text
    if parts.scheme.lower() != "https":
        raise UnsafeURLError("Outbound URL must use https")

    host = parts.hostname or ""
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if _is_forbidden_address(literal):
            raise UnsafeURLError("Outbound URL resolves to a non-public address")
        return text

    try:
        addresses = list((resolver or _default_resolver)(host))
    except Exception as exc:
        raise UnsafeURLError("Outbound URL host could not be resolved") from exc
    if not addresses:
        raise UnsafeURLError("Outbound URL host could not be resolved")
    for raw in addresses:
        try:
            address = ipaddress.ip_address(str(raw).split("%", 1)[0])
        except ValueError as exc:
            raise UnsafeURLError("Outbound URL host resolved to an invalid address") from exc
        if _is_forbidden_address(address):
            raise UnsafeURLError("Outbound URL resolves to a non-public address")
    return text


__all__ = [
    "UnsafeURLError",
    "assert_safe_outbound_url",
    "validate_origin",
    "validate_redirect_uri",
]
