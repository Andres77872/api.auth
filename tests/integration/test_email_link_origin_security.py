"""Verify trusted links and fail-closed behavior through the complete ASGI stack."""

import json
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlsplit

import pytest

from src.routes import auth, auth_patreon, users
from src.Util.email import route_support
from src.Util.email.config import load_email_config
from src.Util.email.security import decrypt_render_payload
from src.Util.patreon.config import load_patreon_config


USER_HASH = "usr-11111111-1111-4111-8111-111111111111"
ROUTES = [
    ("/auth/password/forgot", {"email_or_username": "victim@example.test"}, "enqueue_password_reset_link", "reset_link"),
    ("/users/me/emails", {"email": "victim@example.test"}, "add_user_email_and_enqueue", "activation_link"),
    ("/users/me/emails/email-fixture/resend", None, "resend_user_email_activation", "activation_link"),
    (f"/users/{USER_HASH}/emails/email-fixture/resend", None, "resend_user_email_activation", "activation_link"),
    (f"/users/{USER_HASH}/reset-password", None, "enqueue_admin_password_reset_link", "reset_link"),
    ("/auth/patreon/link/request", {"patreon_email_hint": "patron-linked@example.test", "explicit_user_intent": True}, "create_patreon_proof", "patreon_link_proof_url"),
]


@pytest.fixture
def link_seams(monkeypatch, integration_env):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://app-one.example,https://app-two.example")
    for name in ("AUTH_EMAIL_PUBLIC_BASE_URL", "PUBLIC_AUTH_BASE_URL", "BASE_URL"):
        monkeypatch.delenv(name, raising=False)

    fixture_root = Path(__file__).parents[1] / "fixtures" / "patreon"
    manifest = json.loads((fixture_root / "manifest.json").read_text())
    member_payload = json.loads((fixture_root / manifest["member_fixtures"]["active_mapped"]).read_text())
    member = member_payload["data"][0]
    campaign_id = member["relationships"]["campaign"]["data"]["id"]
    session = SimpleNamespace(user_id="1", user_hash=USER_HASH, user_type="consumer", session_id="test-session")
    user = SimpleNamespace(id="1", user_hash=USER_HASH, username="fixture", user_type="admin", is_active=True)
    scope = SimpleNamespace(is_admin=True)
    queues = {}
    config = load_patreon_config()
    with ExitStack() as stack:
        for obj, name, value in [
            (users, "get_user_by_hash", MagicMock(return_value=user)),
            (users, "_require_admin_or_root", MagicMock(return_value=scope)),
            (users, "resolve_admin_scope", MagicMock(return_value=scope)),
            (users, "require_user_in_scope", MagicMock()),
            (auth, "_check_email_send_rate_limit", MagicMock(return_value=None)),
            (users, "_check_email_send_rate_limit", MagicMock(return_value=None)),
            (users, "_check_resend_cooldown", MagicMock(return_value=None)),
            (auth_patreon, "_load_current_session", MagicMock(return_value=session)),
            (auth_patreon, "require_recent_reauthentication", MagicMock()),
            (auth_patreon, "_check_link_request_rate_limit", AsyncMock(return_value=None)),
            (auth_patreon, "_check_proof_request_rate_limit", AsyncMock(return_value=None)),
            (auth_patreon, "_load_config_or_none", MagicMock(return_value=config)),
            (auth_patreon, "_feature_ready_for_link_request", MagicMock(return_value=True)),
            (auth_patreon, "_patreon_client_from_config", MagicMock(return_value=(None, False))),
            (auth_patreon, "ensure_patreon_catalog_safely", MagicMock(return_value=True)),
            (auth_patreon, "record_patreon_link_activity", AsyncMock()),
        ]:
            stack.enter_context(patch.object(obj, name, value))
        provider = stack.enter_context(patch.object(
            auth_patreon, "_discover_member_for_link",
            AsyncMock(return_value=(member_payload, member, campaign_id)),
        ))
        for name in {route[2] for route in ROUTES}:
            db = auth_patreon.db_patreon if name == "create_patreon_proof" else auth.db_email
            queues[name] = stack.enter_context(patch.object(
                db, name, MagicMock(return_value={"user_id": "1", "email_message_id": "fixture-email"}),
            ))
        begin = stack.enter_context(patch.object(auth.db_email, "begin_email_idempotency", return_value=None))
        generate = stack.enter_context(patch.object(route_support, "generate_link_token", wraps=route_support.generate_link_token))
        proof_generate = stack.enter_context(patch.object(auth_patreon, "generate_patreon_proof_token", wraps=auth_patreon.generate_patreon_proof_token))
        yield SimpleNamespace(
            queues=queues, provider=provider, begin=begin, generate=generate,
            proof_generate=proof_generate, session=session,
        )


def request_headers(origin=None, **extra):
    headers = {"Authorization": "Bearer fixture-token", "Idempotency-Key": "email-origin-fixture"}
    if origin is not None:
        headers["X-Public-Base-Url"] = origin
    return {**headers, **extra}


def test_email_origin_header_and_failure_contracts_are_in_openapi(app):
    schema = app.openapi()
    for path, _, _, _ in ROUTES:
        documented_path = path.replace(USER_HASH, "{user_hash}").replace("email-fixture", "{email_id}")
        operation = schema["paths"][documented_path]["post"]
        assert {"400", "503"} <= operation["responses"].keys()
        assert any(
            parameter["name"] == "X-Public-Base-Url" and not parameter["required"]
            for parameter in operation["parameters"]
        )


@pytest.mark.parametrize("path,body,queue,link_key", ROUTES)
@pytest.mark.parametrize("case", ["host", "forwarded", "http", "missing", "wildcard", "bad_pin"])
async def test_rejected_origin_has_no_email_side_effects(
    client, link_seams, monkeypatch, debug_mode_off, path, body, queue, link_key, case,
):
    headers = request_headers(Host="attacker.example")
    expected_status = 400
    if case == "forwarded":
        headers["X-Public-Base-Url"] = "https://attacker.example"
    elif case == "http":
        headers["X-Public-Base-Url"] = "http://app-one.example"
    elif case == "missing":
        headers.pop("Host")
    elif case == "wildcard":
        monkeypatch.setenv("ALLOWED_ORIGINS", "*")
        headers["X-Public-Base-Url"] = "https://attacker.example"
        expected_status = 503
    elif case == "bad_pin":
        monkeypatch.setenv("AUTH_EMAIL_PUBLIC_BASE_URL", "https://user@attacker.example")
        headers["X-Public-Base-Url"] = "https://app-one.example"
        expected_status = 503

    response = await client.post(path, json=body, headers=headers)
    assert response.status_code == expected_status, response.text
    assert response.json()["error"]["code"] == ("VAL_3001" if expected_status == 400 else "INT_7003")
    link_seams.generate.assert_not_called()
    link_seams.proof_generate.assert_not_called()
    link_seams.begin.assert_not_called()
    link_seams.provider.assert_not_called()
    for enqueue in link_seams.queues.values():
        enqueue.assert_not_called()


@pytest.mark.parametrize("path,body,queue,link_key", ROUTES)
@pytest.mark.parametrize("origin", ["https://app-one.example", "https://app-two.example"])
async def test_each_app_receives_its_own_trusted_link(client, link_seams, path, body, queue, link_key, origin):
    response = await client.post(path, json=body, headers=request_headers(origin, Host="attacker.example"))
    assert response.status_code == (200 if queue == "enqueue_admin_password_reset_link" else 202), response.text
    enqueue = link_seams.queues[queue]
    enqueue.assert_called_once()
    payload = decrypt_render_payload(enqueue.call_args.kwargs["render_payload_ciphertext"], key=load_email_config().payload_key)
    parts = urlsplit(payload[link_key])
    assert f"{parts.scheme}://{parts.netloc}" == origin
    assert parts.path == {
        "reset_link": "/auth/password/reset", "activation_link": "/auth/email/verify",
        "patreon_link_proof_url": "/auth/patreon/link/confirm",
    }[link_key]
    assert parse_qs(parts.query)["token"][0].split(".")[0] == enqueue.call_args.kwargs["lookup_id"]
    assert "token" not in response.json()
    if queue == "create_patreon_proof":
        assert enqueue.call_args.kwargs["user_id"] == link_seams.session.user_id


async def test_approved_request_origin_still_works_without_header(client, link_seams):
    response = await client.post(
        "https://app-one.example/auth/password/forgot",
        json={"email_or_username": "victim@example.test"}, headers=request_headers(),
    )
    assert response.status_code == 202
    queued = link_seams.queues["enqueue_password_reset_link"].call_args.kwargs
    payload = decrypt_render_payload(queued["render_payload_ciphertext"], key=load_email_config().payload_key)
    assert payload["reset_link"].startswith("https://app-one.example/auth/password/reset?token=")


@pytest.mark.parametrize("path,body,queue,link_key", ROUTES)
async def test_fixed_pin_overrides_host_and_header(client, link_seams, monkeypatch, path, body, queue, link_key):
    monkeypatch.setenv("AUTH_EMAIL_PUBLIC_BASE_URL", "https://pinned.example/auth-ui/")
    monkeypatch.setenv("ALLOWED_ORIGINS", "*")
    response = await client.post(path, json=body, headers=request_headers("https://evil.example", Host="evil.example"))
    assert response.status_code in {200, 202}, response.text
    queued = link_seams.queues[queue].call_args.kwargs
    payload = decrypt_render_payload(queued["render_payload_ciphertext"], key=load_email_config().payload_key)
    assert payload[link_key].startswith("https://pinned.example/auth-ui/auth/")


@pytest.mark.parametrize("queue_result", [None, {"user_id": "1", "email_message_id": "fixture-email"}])
async def test_forgot_response_remains_generic_with_trusted_origin(client, link_seams, queue_result):
    link_seams.queues["enqueue_password_reset_link"].return_value = queue_result
    response = await client.post(
        "/auth/password/forgot", json={"email_or_username": "unknown-or-known@example.test"},
        headers=request_headers("https://app-one.example"),
    )
    assert response.status_code == 202
    assert response.json() == {"success": True, "message": "If the request can be processed, it has been accepted."}


async def test_new_reset_token_can_be_redeemed_without_origin_header(client, link_seams):
    response = await client.post(
        "/auth/password/forgot", json={"email_or_username": "victim@example.test"},
        headers=request_headers("https://app-one.example"),
    )
    assert response.status_code == 202
    queued = link_seams.queues["enqueue_password_reset_link"].call_args.kwargs
    payload = decrypt_render_payload(queued["render_payload_ciphertext"], key=load_email_config().payload_key)
    token = parse_qs(urlsplit(payload["reset_link"]).query)["token"][0]
    with (
        patch.object(auth.db_email, "validate_password_reset_token", return_value={"token_valid": True, "purpose": "password_reset"}),
        patch.object(auth.db_email, "consume_password_reset_token", return_value={"password_changed": True, "user_id": "1"}) as consume,
        patch.object(auth, "revoke_user_auth_state") as revoke,
    ):
        result = await client.post("/auth/password/reset", json={"token": token, "new_password": "Valid-reset-password-2026!"})
    assert result.status_code == 202, result.text
    assert consume.call_args.kwargs["lookup_id"] == queued["lookup_id"]
    assert consume.call_args.kwargs["token_hash"] == queued["token_hash"]
    revoke.assert_called_once_with("1", reason="password_reset")


async def test_patreon_confirmation_keeps_requester_binding(client, link_seams):
    response = await client.post(
        "/auth/patreon/link/request", json=ROUTES[-1][1],
        headers=request_headers("https://app-two.example"),
    )
    assert response.status_code == 202
    queued = link_seams.queues["create_patreon_proof"].call_args.kwargs
    payload = decrypt_render_payload(queued["render_payload_ciphertext"], key=load_email_config().payload_key)
    with (
        patch.object(auth_patreon, "_feature_ready_for_link_confirm", return_value=True),
        patch.object(auth_patreon, "_check_proof_consume_rate_limit", AsyncMock(return_value=None)),
        patch.object(auth_patreon.db_patreon, "consume_patreon_proof", return_value={"consume_status": "not_found"}) as consume,
    ):
        result = await client.post(
            "/auth/patreon/link/confirm", json={"token": payload["proof_token"]},
            headers={"Authorization": "Bearer fixture-token"},
        )
    assert result.status_code == 202, result.text
    consume.assert_called_once()
    assert consume.call_args.kwargs["user_id"] == queued["user_id"]
    assert consume.call_args.kwargs["lookup_id"] == queued["lookup_id"]
    assert consume.call_args.kwargs["token_hash"] == queued["token_hash"]
