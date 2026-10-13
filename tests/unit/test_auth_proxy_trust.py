"""The ASGI server alone owns forwarded client identity and HTTPS scheme."""

import pytest
from starlette.requests import Request
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from src.Util.email.route_support import client_ip
from src.Util.proxy_config import validate_forwarded_allow_ips


@pytest.mark.parametrize("value", ["*", "0.0.0.0/0", "::/0", "invalid", "192.0.2.1,"])
def test_unsafe_proxy_configuration_is_rejected(value):
    with pytest.raises(ValueError):
        validate_forwarded_allow_ips(value)


def test_proxy_default_is_empty_and_explicit_networks_are_normalized():
    assert validate_forwarded_allow_ips("") == ""
    assert validate_forwarded_allow_ips(" 192.0.2.1,10.2.3.4/24 ") == "192.0.2.1,10.2.3.0/24"


@pytest.mark.asyncio
@pytest.mark.parametrize(("peer", "trust", "forwarded", "expected_ip", "expected_scheme"), [
    ("198.51.100.1", "", "203.0.113.99", "198.51.100.1", "http"),
    ("198.51.100.1", "192.0.2.10", "203.0.113.99", "198.51.100.1", "http"),
    ("192.0.2.10", "192.0.2.10", "198.51.100.1", "198.51.100.1", "https"),
    ("192.0.2.10", "192.0.2.0/24", "203.0.113.99,198.51.100.1,192.0.2.11", "198.51.100.1", "https"),
])
async def test_forwarded_identity_cannot_override_the_server_boundary(peer, trust, forwarded, expected_ip, expected_scheme):
    scope = {
        "type": "http", "method": "POST", "path": "/auth/login", "scheme": "http",
        "client": (peer, 1234), "server": ("auth.test", 80), "query_string": b"",
        "headers": [(b"x-forwarded-for", forwarded.encode()), (b"x-real-ip", b"203.0.113.88"), (b"x-forwarded-proto", b"https")],
    }

    async def app(scope, receive, send):
        request = Request(scope)
        assert client_ip(request) == expected_ip
        assert request.url.scheme == expected_scheme

    await ProxyHeadersMiddleware(app, trusted_hosts=validate_forwarded_allow_ips(trust))(scope, None, None)
