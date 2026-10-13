"""Public routes cannot vary request fields to buy fresh password work."""

import asyncio
import importlib
import threading
from unittest.mock import patch

import httpx
import pytest
from fastapi import FastAPI

from src.Util.email.route_support import EmailIdempotencyPlan
from src.Util.password_work import PasswordWorkPool
from src.middleware.error_handler import register_exception_handlers
from src.routes import auth


@pytest.mark.asyncio
async def test_unique_identifiers_and_spoofed_ips_hit_one_shared_ip_limit(client, integration_env):
    with patch("src.routes.auth.get_user_by_credentials", return_value=None) as verify:
        for index in range(20):
            response = await client.post(
                "/auth/login", data={"username": f"unknown-{index}", "password": "candidate"},
                headers={"X-Forwarded-For": f"203.0.113.{index + 1}", "X-Real-IP": f"192.0.2.{index + 1}"},
            )
            assert response.status_code == 401
        response = await client.post("/auth/platform/login", data={"username": "another", "password": "candidate"})
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "INT_7005"
    assert 1 <= int(response.headers["Retry-After"]) <= 60
    assert verify.call_count == 20


@pytest.mark.asyncio
async def test_all_four_routes_share_attempt_budget(client, integration_env, monkeypatch):
    monkeypatch.setenv("AUTH_PASSWORD_WORK_IP_LIMIT", "3")
    with patch("src.routes.auth.get_user_by_credentials", return_value=None), \
         patch("src.routes.auth.db_email.validate_password_reset_token", return_value={"token_valid": False}), \
         patch("src.routes.auth.enhanced_register") as register, \
         patch("src.routes.auth.hash_password") as hash_password:
        responses = [
            await client.post("/auth/login", data={"username": "one", "password": "candidate"}),
            await client.post("/auth/platform/login", data={"username": "two", "password": "candidate"}),
            await client.post("/auth/password/reset", json={"token": "unknown.secret", "new_password": "Violet!Lake7392"}),
            await client.post("/auth/register", data={"username": "three", "password": "Violet!Lake7392", "user_group_hash": "group"}),
        ]
    assert [response.status_code for response in responses] == [401, 401, 202, 429]
    register.assert_not_called()
    hash_password.assert_not_called()


@pytest.mark.asyncio
async def test_two_apps_share_global_budget_with_distinct_client_ips(integration_env, monkeypatch):
    monkeypatch.setenv("AUTH_PASSWORD_WORK_GLOBAL_LIMIT", "3")
    apps = [FastAPI(), FastAPI()]
    for app in apps:
        register_exception_handlers(app)
        app.include_router(auth.router)
        app.state.password_work_pool = PasswordWorkPool()
    try:
        with patch("src.routes.auth.get_user_by_credentials", return_value=None) as verify:
            for index in range(5):
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=apps[index % 2], client=(f"192.0.2.{index + 1}", 1234)),
                    base_url="http://test",
                ) as client:
                    response = await client.post("/auth/login", data={"username": f"unknown-{index}", "password": "candidate"})
                assert response.status_code == (401 if index < 3 else 429)
        assert verify.call_count == 3
    finally:
        for app in apps:
            await app.state.password_work_pool.aclose()


@pytest.mark.asyncio
async def test_redis_outage_prevents_database_and_password_work(client, integration_env):
    with patch.object(integration_env["redis"], "eval", side_effect=ConnectionError("offline")), \
         patch("src.routes.auth.get_user_by_credentials") as verify, \
         patch("src.routes.auth.check_username_email_available") as available, \
         patch("src.routes.auth.db_email.validate_password_reset_token") as proof, \
         patch("src.routes.auth.hash_password") as hash_password:
        for path, body in (
            ("/auth/login", {"username": "one", "password": "candidate"}),
            ("/auth/platform/login", {"username": "two", "password": "candidate"}),
            ("/auth/register", {"username": "three", "password": "Violet!Lake7392", "user_group_hash": "group"}),
        ):
            response = await client.post(path, data=body)
            assert response.status_code == 429
            assert response.headers["Retry-After"] == "1"
        response = await client.post("/auth/password/reset", json={"token": "lookup.secret", "new_password": "Violet!Lake7392"})
        assert response.status_code == 429
    for operation in (verify, available, proof, hash_password):
        operation.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("proof", [None, {"token_valid": False}, {"token_valid": True, "purpose": "email_activation"}])
async def test_invalid_proof_never_hashes_or_consumes(client, integration_env, proof):
    with patch("src.routes.auth.db_email.validate_password_reset_token", return_value=proof), \
         patch("src.routes.auth.hash_password") as hash_password, \
         patch("src.routes.auth.db_email.consume_password_reset_token") as consume:
        response = await client.post("/auth/password/reset", json={"token": "lookup.secret", "new_password": "Violet!Lake7392"})
    assert response.status_code == 202
    hash_password.assert_not_called()
    consume.assert_not_called()


@pytest.mark.asyncio
async def test_proof_database_failure_never_hashes(client, integration_env):
    with patch("src.routes.auth.db_email.validate_password_reset_token", side_effect=RuntimeError("offline")), \
         patch("src.routes.auth.hash_password") as hash_password:
        response = await client.post("/auth/password/reset", json={"token": "lookup.secret", "new_password": "Violet!Lake7392"})
    assert response.status_code == 202
    hash_password.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("purpose", ["password_reset", "admin_password_reset"])
async def test_valid_proof_hashes_then_atomically_consumes_in_worker(client, integration_env, purpose):
    events = []
    request_thread = threading.get_ident()

    def record(event, result):
        def operation(*args, **kwargs):
            assert threading.get_ident() != request_thread
            events.append(event)
            return result
        return operation

    with patch("src.routes.auth.db_email.validate_password_reset_token", side_effect=record("proof", {"token_valid": True, "purpose": purpose})), \
         patch("src.routes.auth.hash_password", side_effect=record("hash", "hashed-password")), \
         patch("src.routes.auth.db_email.consume_password_reset_token", side_effect=record("consume", {"password_changed": True, "user_id": "user"})) as consume, \
         patch("src.routes.auth.revoke_user_auth_state") as revoke:
        response = await client.post("/auth/password/reset", json={"token": "lookup.secret", "new_password": "Violet!Lake7392"})
    assert response.status_code == 202
    assert events == ["proof", "hash", "consume"]
    assert consume.call_args.kwargs["new_password_hash"] == "hashed-password"
    revoke.assert_called_once_with("user", reason="password_reset")


@pytest.mark.asyncio
async def test_idempotency_replay_skips_proof_and_hashing(client, integration_env):
    with patch("src.routes.auth._safe_prepare_email_idempotency", return_value=EmailIdempotencyPlan(
        raw_key="replay", scope="auth.password.reset", replay_response=auth.generic_accepted_response(),
    )), patch("src.routes.auth.db_email.validate_password_reset_token") as proof, patch("src.routes.auth.hash_password") as hashing:
        response = await client.post("/auth/password/reset", json={"token": "lookup.secret", "new_password": "Violet!Lake7392"})
    assert response.status_code == 202
    proof.assert_not_called()
    hashing.assert_not_called()


@pytest.mark.asyncio
async def test_worker_saturation_does_not_block_ping_or_queue_registration(client, integration_env):
    entered, release = threading.Event(), threading.Event()

    def credentials(*args):
        entered.set()
        assert release.wait(timeout=5)
        return None

    with patch("src.routes.auth.get_user_by_credentials", side_effect=credentials), \
         patch("src.routes.auth.enhanced_register") as register:
        running = asyncio.create_task(client.post("/auth/login", data={"username": "one", "password": "candidate"}))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            ping = await asyncio.wait_for(client.get("/system/ping"), timeout=1)
            assert ping.status_code == 200
            response = await client.post("/auth/register", data={"username": "two", "password": "Violet!Lake7392", "user_group_hash": "group"})
            assert response.status_code == 429
            assert response.headers["Retry-After"] == "1"
            register.assert_not_called()
        finally:
            release.set()
            await running


@pytest.mark.asyncio
async def test_stalled_redis_does_not_block_the_event_loop(client, integration_env):
    entered, release = threading.Event(), threading.Event()

    def redis_failure(*args):
        entered.set()
        assert release.wait(timeout=5)
        raise ConnectionError("offline")

    with patch.object(integration_env["redis"], "eval", side_effect=redis_failure), \
         patch("src.routes.auth.get_user_by_credentials") as credentials:
        running = asyncio.create_task(client.post("/auth/login", data={"username": "one", "password": "candidate"}))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            assert (await asyncio.wait_for(client.get("/system/ping"), timeout=1)).status_code == 200
        finally:
            release.set()
            response = await running
    assert response.status_code == 429
    credentials.assert_not_called()


@pytest.mark.asyncio
async def test_browser_can_read_retry_after_and_all_routes_document_429(client, integration_env, app):
    from src.main import ALLOWED_ORIGINS

    with patch("src.routes.auth.get_user_by_credentials", return_value=None), \
         patch("src.routes.auth.PasswordWorkLimiter.check_allowed", side_effect=auth.RateLimitExceeded(bucket="global", retry_after=7, limit=60)):
        response = await client.post("/auth/login", data={"username": "one", "password": "candidate"}, headers={"Origin": ALLOWED_ORIGINS[0]})
    assert response.status_code == 429
    assert "retry-after" in response.headers["Access-Control-Expose-Headers"].lower()
    assert response.headers["Retry-After"] == "7"
    schema = app.openapi()
    for path in ("/auth/login", "/auth/platform/login", "/auth/register", "/auth/password/reset"):
        assert "429" in schema["paths"][path]["post"]["responses"]
        assert "Retry-After" in schema["paths"][path]["post"]["responses"]["429"]["headers"]


@pytest.mark.asyncio
async def test_application_lifespan_owns_and_closes_password_pool(app, monkeypatch):
    main = importlib.import_module("src.main")
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "")
    monkeypatch.setenv("AUTH_PASSWORD_WORK_CONCURRENCY", "2")

    async def sweeper():
        await asyncio.Event().wait()

    monkeypatch.setattr(main, "run_api_key_expiry_sweeper", sweeper)
    async with main.lifespan(app):
        pool = app.state.password_work_pool
        assert pool.concurrency == 2
        assert await pool.run(lambda: 42) == 42
    with pytest.raises(auth.RateLimitExceeded):
        await pool.run(lambda: pytest.fail("closed pool admitted work"))


@pytest.mark.asyncio
@pytest.mark.parametrize(("name", "value"), [("FORWARDED_ALLOW_IPS", "*"), ("AUTH_PASSWORD_WORK_CONCURRENCY", "0")])
async def test_invalid_configuration_prevents_startup(app, monkeypatch, name, value):
    main = importlib.import_module("src.main")
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError):
        async with main.lifespan(app):
            pytest.fail("unsafe configuration started the API")
