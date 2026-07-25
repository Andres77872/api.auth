"""RED unit contracts for the Patreon creator API client.

Trace: `.dev/sdd/changes/patreon-account-link/tasks.md` task 1.6 and
design requirements for `src/Util/patreon/client.py`: JSON:API URL/query
construction, encoded bracket query params, server-only bearer headers,
configured User-Agent, explicit timeouts, pagination, 401/429 posture,
`retry_after_seconds` backoff, and redacted errors.

These tests import the future implementation inside test bodies so collection
does not break before Phase 4.1 creates the client.
"""

from __future__ import annotations

import asyncio
import importlib
import json
from types import ModuleType
from typing import Any, Mapping
from urllib.parse import parse_qs, urlsplit

import pytest


MODULE_NAME = "src.Util.patreon.client"
CREATOR_TOKEN = "creator_token_fixture_do_not_log"
USER_AGENT = "api.auth-patreon-tests/1.0"


class FakeAiohttpResponse:
    def __init__(
        self,
        *,
        status: int = 200,
        payload: Mapping[str, Any] | None = None,
        text: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.status = status
        self._payload = dict(payload or {})
        self._text = text
        self.headers = dict(headers or {})

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def __await__(self):
        async def _coro():
            return self

        return _coro().__await__()

    async def json(self) -> dict[str, Any]:
        return dict(self._payload)

    async def text(self) -> str:
        if self._text is not None:
            return self._text
        return json.dumps(self._payload, sort_keys=True)


class FakeAiohttpSession:
    def __init__(self, responses: list[FakeAiohttpResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def get(self, url: str, **kwargs: Any) -> FakeAiohttpResponse:
        self.calls.append({"url": url, **kwargs})
        if not self.responses:
            raise AssertionError("unexpected extra Patreon HTTP GET call")
        return self.responses.pop(0)


def _future_client_module() -> ModuleType:
    try:
        return importlib.import_module(MODULE_NAME)
    except ModuleNotFoundError as exc:
        if exc.name and (MODULE_NAME.startswith(exc.name) or exc.name.startswith("src.Util.patreon")):
            pytest.fail(
                f"missing implementation module: {MODULE_NAME}; "
                "Phase 4.1 must provide the Patreon creator API client",
                pytrace=False,
            )
        pytest.fail(
            f"{MODULE_NAME} import failed due to missing dependency: {exc.name}",
            pytrace=False,
        )


def _client_class(module: ModuleType):
    candidate = getattr(module, "PatreonClient", None)
    assert isinstance(candidate, type), "expected PatreonClient class contract"
    return candidate


def _api_error_type(module: ModuleType) -> type[BaseException]:
    candidate = getattr(module, "PatreonAPIError", None)
    assert isinstance(candidate, type), "expected PatreonAPIError exception type"
    return candidate


def _new_client(module: ModuleType, session: FakeAiohttpSession):
    cls = _client_class(module)
    try:
        return cls(
            access_token=CREATOR_TOKEN,
            user_agent=USER_AGENT,
            base_url="https://www.patreon.com",
            timeout_seconds=7.5,
            session=session,
        )
    except TypeError as exc:
        pytest.fail(
            "PatreonClient must accept keyword contract "
            "(access_token, user_agent, base_url, timeout_seconds, session): "
            f"{exc}",
            pytrace=False,
        )


async def _fetch_campaign_members(client: Any, campaign_id: str) -> Any:
    for name in ("fetch_campaign_members", "list_campaign_members", "get_campaign_members"):
        method = getattr(client, name, None)
        if callable(method):
            return await method(campaign_id)
    pytest.fail("expected PatreonClient.fetch_campaign_members(campaign_id) async method", pytrace=False)


def _timeout_total(timeout: Any) -> float:
    if isinstance(timeout, (int, float)):
        return float(timeout)
    total = getattr(timeout, "total", None)
    if isinstance(total, (int, float)):
        return float(total)
    pytest.fail(f"could not inspect timeout total from {timeout!r}", pytrace=False)


def _members_from_result(result: Any) -> list[Any]:
    if isinstance(result, list):
        return result
    if isinstance(result, Mapping):
        data = result.get("data") or result.get("members")
        if isinstance(data, list):
            return data
    if hasattr(result, "data") and isinstance(result.data, list):
        return result.data
    pytest.fail("campaign member result must expose merged member data", pytrace=False)


def test_campaign_members_request_uses_expected_url_headers_query_and_timeout():
    module = _future_client_module()
    session = FakeAiohttpSession([FakeAiohttpResponse(payload={"data": [], "links": {}})])
    client = _new_client(module, session)

    asyncio.run(_fetch_campaign_members(client, "campaign-mw-alpha"))

    assert len(session.calls) == 1
    call = session.calls[0]
    parsed = urlsplit(call["url"])
    query = parse_qs(parsed.query)

    assert parsed.scheme == "https"
    assert parsed.netloc == "www.patreon.com"
    assert parsed.path == "/api/oauth2/v2/campaigns/campaign-mw-alpha/members"
    assert "fields%5Bmember%5D" in parsed.query
    assert "fields%5Btier%5D" in parsed.query
    assert "page%5Bcount%5D" in parsed.query
    assert query["include"] == ["currently_entitled_tiers,user"]
    assert "email" in query["fields[member]"][0]
    assert "patron_status" in query["fields[member]"][0]
    assert "last_charge_status" in query["fields[member]"][0]
    assert "title" in query["fields[tier]"][0]
    assert query["page[count]"][0].isdigit()

    headers = call.get("headers") or {}
    assert headers.get("Authorization") == f"Bearer {CREATOR_TOKEN}"
    assert headers.get("User-Agent") == USER_AGENT
    assert _timeout_total(call.get("timeout")) == 7.5


def test_campaign_members_paginates_until_no_next_link():
    module = _future_client_module()
    next_url = (
        "https://www.patreon.com/api/oauth2/v2/campaigns/campaign-mw-alpha/members"
        "?page%5Bcursor%5D=cursor-2"
    )
    session = FakeAiohttpSession(
        [
            FakeAiohttpResponse(
                payload={
                    "data": [{"id": "member-page-1", "type": "member"}],
                    "links": {"next": next_url},
                }
            ),
            FakeAiohttpResponse(
                payload={"data": [{"id": "member-page-2", "type": "member"}], "links": {}}
            ),
        ]
    )
    client = _new_client(module, session)

    result = asyncio.run(_fetch_campaign_members(client, "campaign-mw-alpha"))

    assert [member["id"] for member in _members_from_result(result)] == [
        "member-page-1",
        "member-page-2",
    ]
    assert len(session.calls) == 2
    assert "page%5Bcursor%5D=cursor-2" in session.calls[1]["url"]


def test_unauthorized_response_raises_redacted_patreon_api_error():
    module = _future_client_module()
    error_type = _api_error_type(module)
    session = FakeAiohttpSession(
        [
            FakeAiohttpResponse(
                status=401,
                payload={"errors": [{"detail": f"token {CREATOR_TOKEN} failed for patron@example.test"}]},
                text=f"Unauthorized creator token {CREATOR_TOKEN} patron@example.test",
            )
        ]
    )
    client = _new_client(module, session)

    with pytest.raises(error_type) as exc_info:
        asyncio.run(_fetch_campaign_members(client, "campaign-mw-alpha"))

    error = exc_info.value
    serialized = f"{error!s} {getattr(error, 'metadata', '')}"
    assert getattr(error, "status_code", getattr(error, "status", None)) == 401
    assert CREATOR_TOKEN not in serialized
    assert "patron@example.test" not in serialized


def test_rate_limit_response_exposes_retry_after_seconds_without_secret_leakage():
    module = _future_client_module()
    error_type = _api_error_type(module)
    session = FakeAiohttpSession(
        [
            FakeAiohttpResponse(
                status=429,
                payload={
                    "errors": [
                        {
                            "detail": f"rate limited token={CREATOR_TOKEN}",
                            "retry_after_seconds": 17,
                        }
                    ]
                },
            )
        ]
    )
    client = _new_client(module, session)

    with pytest.raises(error_type) as exc_info:
        asyncio.run(_fetch_campaign_members(client, "campaign-mw-alpha"))

    error = exc_info.value
    retry_after = getattr(error, "retry_after_seconds", getattr(error, "backoff_seconds", None))
    assert getattr(error, "status_code", getattr(error, "status", None)) == 429
    assert retry_after == 17
    assert CREATOR_TOKEN not in f"{error!s} {getattr(error, 'metadata', '')}"
