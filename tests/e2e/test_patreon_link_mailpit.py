"""Optional local E2E RED proof for Patreon link email-loop delivery.

Trace: `.dev/sdd/changes/patreon-account-link/tasks.md` task `1.13`.

This test is intentionally skipped unless `RUN_PATREON_LOCAL_E2E=1` is set.
When opted in, it exercises a fake Patreon API plus local Mailpit-compatible
SMTP/HTTP capture and fails until the future Patreon link routes exist.
"""

from __future__ import annotations

import json
import os
import re
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import import_module
from pathlib import Path
from typing import Any
from urllib.request import urlopen

import pytest


ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "patreon"

LOCAL_E2E_FLAG = "RUN_PATREON_LOCAL_E2E"
LINK_REQUEST_PATH = "/auth/patreon/link/request"
LINK_CONFIRM_PATH = "/auth/patreon/link/confirm"
LINK_STATUS_PATH = "/auth/patreon/link/status"

TOKEN_RE = re.compile(r"(?P<token>[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{24,})")
FORBIDDEN_RESPONSE_FIELDS = {
    "access_token",
    "refresh_token",
    "session_token",
    "api_key",
    "patreon_user_id",
    "patreon_member_id",
    "patreon_campaign_id",
    "patreon_tier_id",
    "raw_patreon_email",
    "provider_sub_hash",
    "provider_sub_fingerprint",
}


def _require_local_e2e_enabled() -> None:
    if os.environ.get(LOCAL_E2E_FLAG, "").strip().lower() not in {"1", "true", "yes", "on"}:
        pytest.skip(f"optional Patreon local E2E disabled; set {LOCAL_E2E_FLAG}=1 to run")


def _member_payload() -> dict[str, Any]:
    return json.loads((FIXTURE_ROOT / "members" / "mismatched_email_member.json").read_text(encoding="utf-8"))


def _mailpit_server():
    # Once the operator explicitly opts in, harness defects are test failures.
    # Only the disabled flag above is allowed to turn this test into a skip.
    module = import_module("tests.e2e.test_email_activation_mailpit")
    return module.mailpit_server()


class _FakePatreonAPIHandler(BaseHTTPRequestHandler):
    def _json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path.startswith("/api/oauth2/v2/campaigns/") and parsed.path.endswith("/members"):
            self.server.calls.append({"method": "GET", "path": parsed.path, "query": parsed.query})
            self._json(200, self.server.member_payload)
            return
        self._json(404, {"errors": [{"code": "not_found"}]})

    def log_message(self, *_args) -> None:
        return


class _FakePatreonAPIServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, member_payload: dict[str, Any]) -> None:
        super().__init__(("127.0.0.1", 0), _FakePatreonAPIHandler)
        self.member_payload = member_payload
        self.calls: list[dict[str, str]] = []
        self._thread: threading.Thread | None = None

    def start(self) -> "_FakePatreonAPIServer":
        self._thread = threading.Thread(target=self.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self.shutdown()
        self.server_close()
        if self._thread is not None:
            self._thread.join(timeout=1)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"


def _assert_future_route_exists(response, path: str) -> None:
    if response.status_code == 404 and "not found" in response.text.lower():
        pytest.fail(f"missing future Patreon route {path}; link/proof implementation must satisfy task 5.x", pytrace=False)


def _assert_no_session_or_raw_provider_leak(response, *, context: str) -> None:
    try:
        payload: Any = response.json()
    except Exception:
        payload = response.text
    serialized = json.dumps(payload, sort_keys=True).lower() if not isinstance(payload, str) else payload.lower()
    for field in FORBIDDEN_RESPONSE_FIELDS:
        assert field not in serialized, f"{context}: forbidden `{field}` leaked"
    assert "session_token" not in response.cookies
    assert "refresh_token" not in response.cookies


def _mailpit_messages(api_base_url: str) -> list[dict[str, Any]]:
    with urlopen(f"{api_base_url}/api/v1/messages", timeout=2) as response:  # noqa: S310 - local test server only
        payload = json.loads(response.read().decode("utf-8"))
    return list(payload.get("messages") or [])


def _mailpit_message(api_base_url: str, message_id: str) -> dict[str, Any]:
    with urlopen(f"{api_base_url}/api/v1/message/{urllib.parse.quote(message_id)}", timeout=2) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def _wait_for_proof_email(api_base_url: str, *, recipient: str) -> dict[str, Any]:
    for _ in range(30):
        for summary in _mailpit_messages(api_base_url):
            recipients = " ".join(summary.get("To") or [])
            if recipient in recipients:
                return _mailpit_message(api_base_url, summary["ID"])
        import time

        time.sleep(0.2)
    pytest.fail(f"Patreon proof email was not delivered to local Mailpit recipient {recipient}", pytrace=False)


def _extract_proof_token(message: dict[str, Any]) -> str:
    body = "\n".join(str(message.get(key) or "") for key in ("Text", "HTML", "Body"))
    match = TOKEN_RE.search(body)
    if not match:
        pytest.fail("Patreon proof email must contain a split proof token", pytrace=False)
    return match.group("token")


@pytest.mark.asyncio
async def test_fake_patreon_api_mailpit_proof_loop_never_issues_local_session(client, e2e_env, monkeypatch, request):
    _require_local_e2e_enabled()

    fake_patreon = _FakePatreonAPIServer(_member_payload()).start()
    local_mailpit = _mailpit_server().start()
    request.addfinalizer(fake_patreon.stop)
    request.addfinalizer(local_mailpit.stop)

    monkeypatch.setenv("PATREON_LINKING_ENABLED", "true")
    monkeypatch.setenv("PATREON_API_BASE_URL", fake_patreon.base_url)
    monkeypatch.setenv("PATREON_CREATOR_ACCESS_TOKEN", "fake-local-patreon-creator-token-not-real")
    monkeypatch.setenv("PATREON_CAMPAIGN_IDS", "campaign-mw-alpha")
    monkeypatch.setenv("EMAIL_DELIVERY_ENABLED", "true")
    monkeypatch.setenv("EMAIL_PROVIDER", "mailpit")
    monkeypatch.setenv("MAILPIT_SMTP_HOST", local_mailpit.smtp_host)
    monkeypatch.setenv("MAILPIT_SMTP_PORT", str(local_mailpit.smtp_port))
    monkeypatch.setenv("MAILPIT_API_BASE_URL", local_mailpit.api_base_url)

    auth_headers = {
        "Authorization": "Bearer fake-local-session-token-for-patreon-link",
        "User-Agent": "patreon-local-mailpit-e2e-red-test",
    }
    link_request = await client.post(
        LINK_REQUEST_PATH,
        json={"patreon_email_hint": "local-owner@example.test"},
        headers=auth_headers,
    )
    _assert_future_route_exists(link_request, LINK_REQUEST_PATH)
    assert link_request.status_code == 202
    _assert_no_session_or_raw_provider_leak(link_request, context="link request")

    proof_message = _wait_for_proof_email(local_mailpit.api_base_url, recipient="patron-different@example.test")
    proof_token = _extract_proof_token(proof_message)

    confirm = await client.post(LINK_CONFIRM_PATH, json={"token": proof_token}, headers=auth_headers)
    _assert_future_route_exists(confirm, LINK_CONFIRM_PATH)
    assert confirm.status_code in {200, 202}
    _assert_no_session_or_raw_provider_leak(confirm, context="proof confirm")

    status = await client.get(LINK_STATUS_PATH, headers=auth_headers)
    _assert_future_route_exists(status, LINK_STATUS_PATH)
    assert status.status_code == 200
    _assert_no_session_or_raw_provider_leak(status, context="link status")
    assert fake_patreon.calls, "link request must discover Patreon membership through the fake creator-owned API"
