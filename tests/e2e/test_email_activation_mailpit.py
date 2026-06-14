"""RED Mailpit proof for the full email activation chain.

Trace: `.dev/sdd/changes/email-activation/tasks.md` task 1.10.
"""

from __future__ import annotations

import hmac
import json
import socketserver
import threading
import uuid
import urllib.parse
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import patch

import pytest


def _e2e_object(**attrs):
    return SimpleNamespace(**attrs)


def _project():
    return _e2e_object(
        id="proj-mailpit-e2e-001",
        project_hash="prj-e2e-001",
        project_name="Mailpit E2E Project",
        project_description="Mailpit activation proof project",
        is_active=True,
        archived=False,
    )


def _user_group():
    return _e2e_object(
        id="ug-mailpit-e2e-001",
        group_hash="grp-e2e-001",
        group_name="Mailpit E2E Group",
        group_description="Mailpit activation proof group",
    )


def _register_result(*, username: str, user_id: str, user_hash: str, project):
    return _e2e_object(
        user_id=user_id,
        user_hash=user_hash,
        username=username,
        email=None,
        user_type="consumer",
        project_id=project.id,
        project_hash=project.project_hash,
        project_name=project.project_name,
        groups=["Mailpit E2E Group"],
        user_group_ids=["ug-mailpit-e2e-001"],
        permissions=[],
    )


def _session(*, token: str, username: str, user_id: str, user_hash: str, project):
    return _e2e_object(
        user_id=user_id,
        user_hash=user_hash,
        username=username,
        user_type="consumer",
        project_id=project.id,
        project_hash=project.project_hash,
        project_name=project.project_name,
        permissions=[],
        groups=["Mailpit E2E Group"],
        session_token=token,
        session_length=259200,
        scope="project",
    )


def _login_user(*, username: str, email: str, user_id: str, user_hash: str):
    return _e2e_object(
        id=user_id,
        user_hash=user_hash,
        username=username,
        email=email,
        user_type="consumer",
        is_active=True,
        assigned_project_id=None,
    )


class MailpitActivationHarness:
    """Deterministic in-memory DB seam for the Mailpit activation chain.

    The app routes still generate the token/outbox payloads and the real worker
    still renders/sends through Mailpit. This seam only replaces unavailable
    MySQL stored procedures so the E2E gate reaches the delivery path instead of
    failing on unrelated mocked availability/default-cursor behavior.
    """

    def __init__(self) -> None:
        self._messages: list[dict] = []
        self._tokens: dict[str, dict] = {}
        self.attempts: list[dict] = []
        self.completed_idempotency: list[dict] = []
        self.activated_email: str | None = None

    def begin_email_idempotency(self, **kwargs):
        return {
            "idempotency_status": "created",
            "idempotency_id": kwargs.get("idempotency_id"),
            "replay_status_code": 202,
            "replay_body": kwargs.get("replay_body"),
            "expires_at": kwargs.get("expires_at"),
        }

    def complete_email_idempotency(self, **kwargs):
        self.completed_idempotency.append(dict(kwargs))
        return {"idempotency_status": "complete", "email_message_id": kwargs.get("email_message_id")}

    def add_user_email_and_enqueue(self, **kwargs):
        token = {
            "lookup_id": kwargs["lookup_id"],
            "token_hash": kwargs["token_hash"],
            "user_id": kwargs["user_id"],
            "user_email_id": kwargs["user_email_id"],
            "email_normalized": kwargs["email_normalized"],
            "consumed": False,
        }
        self._tokens[token["lookup_id"]] = token
        self._messages.append(
            {
                "id": kwargs["email_message_id"],
                "email_message_id": kwargs["email_message_id"],
                "user_id": kwargs["user_id"],
                "user_email_id": kwargs["user_email_id"],
                "purpose": "email_activation",
                "template_code": "email_activation",
                "recipient_email": kwargs["email_normalized"],
                "recipient_hash": kwargs["email_hash"],
                "recipient_masked": kwargs["email_masked"],
                "provider": kwargs["provider"],
                "provider_idempotency_key": kwargs["provider_idempotency_key"],
                "status": "pending",
                "attempt_count": 0,
                "max_attempts": 8,
                "render_payload_ciphertext": kwargs["render_payload_ciphertext"],
            }
        )
        return {
            "email_message_id": kwargs["email_message_id"],
            "user_email_id": kwargs["user_email_id"],
            "lifecycle_status": "accepted",
        }

    def claim_email_messages(self, *, worker_id: str, limit: int, lease_seconds: int):
        claimed = []
        for message in self._messages:
            if message["status"] not in {"pending", "retry"}:
                continue
            message["status"] = "processing"
            message["claimed_by"] = worker_id
            message["lease_seconds"] = lease_seconds
            claimed.append(dict(message))
            if len(claimed) >= int(limit):
                break
        return claimed

    def is_recipient_suppressed(self, recipient_hash) -> bool:
        return False

    def record_email_delivery_attempt(self, **kwargs):
        self.attempts.append(dict(kwargs))
        return {"status": kwargs.get("status")}

    def finalize_email_message(self, **kwargs):
        message_id = kwargs.get("email_message_id")
        for message in self._messages:
            if message["email_message_id"] == message_id:
                message["status"] = kwargs.get("status")
                message["provider_message_id"] = kwargs.get("provider_message_id")
                break
        return {"email_message_id": message_id, "status": kwargs.get("status")}

    def consume_email_activation_token(self, *, lookup_id: str, token_hash: bytes, **_kwargs):
        token = self._tokens.get(lookup_id)
        if not token or token["consumed"] or not hmac.compare_digest(token_hash, token["token_hash"]):
            return {"identity_changed": False}
        token["consumed"] = True
        self.activated_email = token["email_normalized"]
        return {
            "identity_changed": True,
            "user_id": token["user_id"],
            "user_email_id": token["user_email_id"],
            "lifecycle_status": "activated",
        }


class _MailStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._messages: dict[str, dict] = {}

    def add_raw_message(self, raw_message: bytes) -> None:
        parsed = BytesParser(policy=policy.default).parsebytes(raw_message)
        message_id = str(uuid.uuid4())
        subject = str(parsed.get("Subject") or "")
        to_header = str(parsed.get("To") or "")
        text = ""
        html = ""
        if parsed.is_multipart():
            for part in parsed.walk():
                content_type = part.get_content_type()
                if content_type == "text/plain" and not text:
                    text = str(part.get_content() or "")
                elif content_type == "text/html" and not html:
                    html = str(part.get_content() or "")
        else:
            payload = str(parsed.get_content() or "")
            if parsed.get_content_type() == "text/html":
                html = payload
            else:
                text = payload
        body = raw_message.decode("utf-8", errors="replace")
        with self._lock:
            self._messages[message_id] = {
                "ID": message_id,
                "Subject": subject,
                "To": [to_header],
                "Text": text,
                "HTML": html,
                "Body": body,
            }

    def summaries(self) -> list[dict]:
        with self._lock:
            return [
                {"ID": message["ID"], "Subject": message["Subject"], "To": message["To"]}
                for message in self._messages.values()
            ]

    def get(self, message_id: str) -> dict | None:
        with self._lock:
            message = self._messages.get(message_id)
            return dict(message) if message else None


class _SMTPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, server_address, RequestHandlerClass, store: _MailStore):
        super().__init__(server_address, RequestHandlerClass)
        self.store = store


class _SMTPHandler(socketserver.StreamRequestHandler):
    def _send(self, line: bytes) -> None:
        self.wfile.write(line + b"\r\n")

    def handle(self) -> None:
        self._send(b"220 local-mailpit.test ESMTP")
        in_data = False
        data_lines: list[bytes] = []
        while True:
            line = self.rfile.readline(65536)
            if not line:
                return

            if in_data:
                if line in {b".\r\n", b".\n"}:
                    self.server.store.add_raw_message(b"".join(data_lines))
                    data_lines = []
                    in_data = False
                    self._send(b"250 2.0.0 queued")
                    continue
                data_lines.append(line[1:] if line.startswith(b"..") else line)
                continue

            command = line.decode("ascii", errors="ignore").strip().upper()
            if command.startswith("EHLO") or command.startswith("HELO"):
                self.wfile.write(b"250-local-mailpit.test\r\n250 SIZE 33554432\r\n")
            elif command.startswith("MAIL FROM") or command.startswith("RCPT TO"):
                self._send(b"250 2.1.0 OK")
            elif command == "DATA":
                in_data = True
                self._send(b"354 End data with <CR><LF>.<CR><LF>")
            elif command == "RSET" or command == "NOOP":
                self._send(b"250 OK")
            elif command == "QUIT":
                self._send(b"221 2.0.0 Bye")
                return
            else:
                self._send(b"250 OK")


class _MailpitHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, server_address, RequestHandlerClass, store: _MailStore):
        super().__init__(server_address, RequestHandlerClass)
        self.store = store


class _MailpitHTTPHandler(BaseHTTPRequestHandler):
    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API.
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/v1/messages":
            self._json(200, {"messages": self.server.store.summaries()})
            return
        if path.startswith("/api/v1/message/"):
            message_id = urllib.parse.unquote(path.rsplit("/", 1)[-1])
            message = self.server.store.get(message_id)
            self._json(200, message or {})
            return
        self._json(404, {"error": "not_found"})

    def log_message(self, *_args) -> None:
        return


class LocalMailpitServer:
    """Local Mailpit-compatible SMTP + HTTP capture server for hermetic E2E runs."""

    def __init__(self) -> None:
        self.store = _MailStore()
        self.smtp_server: _SMTPServer | None = None
        self.http_server: _MailpitHTTPServer | None = None
        self._threads: list[threading.Thread] = []

    def start(self) -> "LocalMailpitServer":
        self.smtp_server = _SMTPServer(("127.0.0.1", 0), _SMTPHandler, self.store)
        self.http_server = _MailpitHTTPServer(("127.0.0.1", 0), _MailpitHTTPHandler, self.store)
        for server in (self.smtp_server, self.http_server):
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self._threads.append(thread)
        return self

    def stop(self) -> None:
        for server in (self.smtp_server, self.http_server):
            if server is not None:
                server.shutdown()
                server.server_close()
        for thread in self._threads:
            thread.join(timeout=1)
        self.smtp_server = None
        self.http_server = None
        self._threads = []

    @property
    def smtp_host(self) -> str:
        return "127.0.0.1"

    @property
    def smtp_port(self) -> int:
        assert self.smtp_server is not None
        return int(self.smtp_server.server_address[1])

    @property
    def api_base_url(self) -> str:
        assert self.http_server is not None
        return f"http://127.0.0.1:{self.http_server.server_address[1]}"


@pytest.mark.asyncio
async def test_mailpit_activation_chain_register_add_deliver_verify_login(client, e2e_env, monkeypatch, request):
    """Proves route → outbox → worker → Mailpit → verify → activated-email login."""
    from src.Util.email.mailpit import MailpitClient
    from src.workers.email_worker import DrainResult, EmailWorker

    # tests/conftest.py intentionally loads `.env.test` with delivery disabled;
    # gate 8.9 is the explicit local-Mailpit opt-in.
    local_mailpit = LocalMailpitServer().start()
    request.addfinalizer(local_mailpit.stop)
    monkeypatch.setenv("EMAIL_DELIVERY_ENABLED", "true")
    monkeypatch.setenv("EMAIL_PROVIDER", "mailpit")
    monkeypatch.setenv("MAILPIT_SMTP_HOST", local_mailpit.smtp_host)
    monkeypatch.setenv("MAILPIT_SMTP_PORT", str(local_mailpit.smtp_port))
    monkeypatch.setenv("MAILPIT_API_BASE_URL", local_mailpit.api_base_url)

    harness = MailpitActivationHarness()
    suffix = uuid.uuid4().hex[:10]
    username = f"mailpit_user_{suffix}"
    email = f"mailpit-user-{suffix}@example.com"
    user_id = f"usr-mailpit-{suffix}"
    user_hash = f"usr-mailpit-hash-{suffix}"
    project = _project()
    register_result = _register_result(username=username, user_id=user_id, user_hash=user_hash, project=project)

    with patch("src.routes.auth.check_username_email_available", return_value=True), \
         patch("src.routes.auth.get_user_group_by_hash", return_value=_user_group()), \
         patch("src.routes.auth.enhanced_register", return_value=register_result):
        register_response = await client.post(
            "/auth/register",
            data={"username": username, "password": "SecureP@ss123", "user_group_hash": "grp-e2e-001"},
        )
    assert register_response.status_code == 200
    assert register_response.json()["user"]["email"] is None

    session = _session(
        token=register_response.json()["access_token"],
        username=username,
        user_id=user_id,
        user_hash=user_hash,
        project=project,
    )

    auth_session_patches = (
        patch("src.Util.db.db_enhanced.validate_session", return_value=session),
        patch("src.Util.decorators.validate_session", return_value=session),
    )

    for patcher in auth_session_patches:
        patcher.start()
    try:
        with patch("src.routes.users.db_email", harness), \
             patch("src.Util.email.route_support.db_email", harness), \
             patch("src.Util.email.route_support.redis_client", e2e_env["redis"]):
            add_response = await client.post(
                "/users/me/emails",
                data={"email": email},
                headers={
                    "Authorization": f"Bearer {register_response.json()['access_token']}",
                    "Idempotency-Key": f"mailpit-add-{suffix}",
                },
            )
        assert add_response.status_code == 202

        worker = EmailWorker(worker_id="mailpit-test-worker", db_module=harness)
        drain_result = DrainResult(
            worker_id=worker.worker_id,
            results=tuple(worker.drain_once(limit=10)),
        )
        assert drain_result.sent_count == 1

        mailpit = MailpitClient(base_url=local_mailpit.api_base_url)
        message = mailpit.wait_for_message(to=email, subject_contains="Activate", timeout_seconds=10)
        token = mailpit.extract_activation_token(message)
        assert token and "." in token

        with patch("src.routes.auth.db_email", harness), \
             patch("src.Util.email.route_support.db_email", harness), \
             patch("src.Util.email.route_support.redis_client", e2e_env["redis"]), \
             patch("src.routes.auth.revoke_user_auth_state") as revoke_auth_state:
            verify_response = await client.post("/auth/email/verify", json={"token": token})
        assert verify_response.status_code == 202
        assert "session_token" not in verify_response.cookies
        assert "refresh_token" not in verify_response.cookies
        assert harness.activated_email == email
        revoke_auth_state.assert_called_once_with(user_id, reason="email_activation")

        login_user = _login_user(username=username, email=email, user_id=user_id, user_hash=user_hash)
        with patch("src.routes.auth.get_user_by_credentials", return_value=login_user) as credentials_lookup, \
             patch("src.routes.auth.get_user_accessible_projects", return_value=[project]), \
             patch("src.routes.auth.get_project_by_hash", return_value=project), \
             patch("src.routes.auth.get_user_groups_for_user", return_value=[]):
            login_response = await client.post(
                "/auth/login",
                data={"username": email, "password": "SecureP@ss123", "project_hash": project.project_hash},
            )
    finally:
        for patcher in reversed(auth_session_patches):
            patcher.stop()
        local_mailpit.stop()

    assert login_response.status_code == 200
    credentials_lookup.assert_called_once_with(email, "SecureP@ss123")
