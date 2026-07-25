"""Phase 3 RED high-fidelity lifecycle contracts for Google OAuth.

Trace: `.dev/sdd/changes/google-oauth-login/tasks.md` task 3.6. The tests
collect without a full local stack, but execution skips unless the local test
MySQL and Redis services are provisioned. No docker/build command is started
from this test module.
"""

from __future__ import annotations

import json
import os
from contextlib import ExitStack, contextmanager
from importlib import import_module
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

import pymysql
import pytest
import redis

from src.Util.JWT_Security import JWTTokenHandler
from src.Util.oauth_state import build_pkce_s256_challenge, fingerprint_oauth_value


START_PATH = "/auth/google/start"
CALLBACK_PATH = "/auth/google/callback"


def _mysql_available() -> bool:
    try:
        conn = pymysql.connect(
            host=os.environ.get("REAL_DB_HOST", "127.0.0.1"),
            port=int(os.environ.get("REAL_DB_PORT", "3307")),
            user=os.environ.get("REAL_DB_USER", "test_user"),
            password=os.environ.get("REAL_DB_PASSWORD", "test_mysql_password"),
            database=os.environ.get("REAL_DB_NAME", "magic_auth"),
            charset="utf8mb4",
            connect_timeout=5,
            read_timeout=10,
            write_timeout=10,
        )
        conn.close()
        return True
    except Exception:
        return False


def _redis_available() -> bool:
    try:
        client = redis.StrictRedis(
            host=os.environ.get("REAL_REDIS_HOST", "127.0.0.1"),
            port=int(os.environ.get("REAL_REDIS_PORT", "6380")),
            db=0,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
        )
        return bool(client.ping())
    except Exception:
        return False


@pytest.fixture
def google_oauth_full_stack_available():
    if not (_mysql_available() and _redis_available()):
        if os.environ.get("E2E_REQUIRE_REAL_INFRA", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }:
            pytest.fail(
                "Docker E2E requires MySQL and Redis for the Google OAuth lifecycle",
                pytrace=False,
            )
        pytest.skip(
            "full Google OAuth lifecycle stack not provisioned for Phase 3 RED "
            "(needs local test MySQL, Redis, ASGI app, and fake Google seams)"
        )


@pytest.fixture
def isolated_google_oauth_redis(google_oauth_full_stack_available, live_redis):
    """Give each synthetic OAuth lifecycle a clean live-Redis namespace."""
    return live_redis


def _is_unimplemented_route(response) -> bool:
    body = response.text.lower()
    return response.status_code == 404 and "not found" in body and "ext_8" not in body


def _assert_oauth_route_exists(response, path: str) -> None:
    if _is_unimplemented_route(response):
        pytest.fail(
            f"missing future OAuth route {path}; lifecycle RED test cannot pass "
            "until Phase 8 registers auth_google.router",
            pytrace=False,
        )


def _authorization_params_from_start(response) -> dict[str, str]:
    """Extract the one real state/nonce/PKCE tuple emitted by the start route."""
    assert response.status_code == 303
    location = response.headers.get("location")
    assert location, "OAuth start must redirect to the provider authorization URL"
    query = parse_qs(urlparse(location).query, keep_blank_values=True)
    values: dict[str, str] = {}
    for name in ("state", "nonce", "code_challenge", "code_challenge_method"):
        assert len(query.get(name, [])) == 1, f"OAuth start must emit exactly one {name}"
        values[name] = query[name][0]
    assert values["code_challenge_method"] == "S256"
    return values


@contextmanager
def _optional_patch_targets(targets: tuple[str, ...], value: Any):
    with ExitStack() as stack:
        for target in targets:
            module_name, _, _ = target.rpartition(".")
            try:
                import_module(module_name)
            except ImportError:
                continue
            stack.enter_context(patch(target, value, create=True))
        yield


@contextmanager
def _fake_google_e2e_seams(fake_google_token_response):
    fake_token_client = MagicMock()
    fake_token_client.authorize_access_token.return_value = fake_google_token_response
    fake_token_client.exchange_authorization_code.return_value = fake_google_token_response
    fake_id_token_verifier = MagicMock(
        side_effect=lambda _token, *, expected_nonce, **_kwargs: {
            "provider": "google",
            "sub": "google-sub-test-001",
            "email": "oauth-user@example.test",
            "email_verified": True,
            "iss": "https://accounts.google.com",
            "aud": os.environ.get(
                "GOOGLE_OAUTH_CLIENT_ID",
                "test-google-client-id.apps.googleusercontent.com",
            ),
            "nonce": expected_nonce,
        }
    )
    with _optional_patch_targets(
        (
            "src.routes.auth_google.google_oauth_client",
            "src.routes.auth_google.oauth_client",
            "src.Util.oauth_clients.google_oauth_client",
        ),
        fake_token_client,
    ), _optional_patch_targets(
        ("src.routes.auth_google.verify_google_id_token",),
        fake_id_token_verifier,
    ):
        yield SimpleNamespace(
            token_client=fake_token_client,
            id_token_verifier=fake_id_token_verifier,
        )


class _E2EProviderInitRedeemer:
    def __init__(self, *tokens: str):
        self.tokens = set(tokens)

    async def redeem_provider_init_token(self, provider_init_token: str, **kwargs):
        if provider_init_token not in self.tokens:
            raise RuntimeError("provider_init_not_found")
        return {
            "provider": "google",
            "purpose": "login",
            "project_hash": "project-hash-redacted-by-contract",
            "user_group_hash": "group-hash-redacted-by-contract",
            "return_origin": kwargs.get("return_origin") or "http://localhost:3000",
            "issuer": "magic-worlds-api",
            "audience": "api.auth",
            "expires_in": 600,
            "scope_fingerprint": "e2e-scope-fingerprint",
            "provider_init_fingerprint": "e2e-provider-init-fingerprint",
        }


@contextmanager
def _fake_provider_init_e2e_seams(*tokens: str):
    fake_provider_init_redeemer = _E2EProviderInitRedeemer(*tokens)
    redeem = fake_provider_init_redeemer.redeem_provider_init_token
    with _optional_patch_targets(
        (
            "src.routes.auth_google.redeem_provider_init_token",
            "src.routes.auth_google.redeem_provider_init",
            "src.Util.provider_init.redeem_provider_init_token",
        ),
        redeem,
    ):
        yield fake_provider_init_redeemer


@contextmanager
def _linked_google_identity_db_seams():
    """Resolve one fake linked identity consistently through callback and session use."""
    user = SimpleNamespace(
        id="1",
        user_hash="usr-oauth-linked-001",
        username="oauthuser",
        email="oauth-user@example.test",
        user_type="consumer",
        is_active=True,
        assigned_project_id=None,
    )
    project = SimpleNamespace(
        id="1",
        project_hash="project-hash-redacted-by-contract",
        project_name="OAuth Project",
        project_description="OAuth project",
        is_active=True,
        archived=False,
    )
    group = SimpleNamespace(
        id="1",
        group_hash="group-hash-redacted-by-contract",
        group_name="OAuth Consumers",
    )

    with ExitStack() as stack:
        for target, value in (
            ("src.Util.db.db_enhanced.get_user_by_hash", user),
            ("src.Util.db.db_enhanced.get_project_by_hash", project),
            ("src.Util.db.db_enhanced.get_user_groups_in_project_by_hash", [group]),
            ("src.Util.db.db_enhanced.get_user_accessible_projects", [project]),
            ("src.routes.auth.get_user_by_hash", user),
            ("src.routes.auth.get_project_by_hash", project),
            ("src.routes.auth._route_refresh_groups", [group]),
            ("src.routes.auth.get_user_accessible_projects", [project]),
            ("src.Util.db.db_global_roles.get_user_permissions", []),
            ("src.routes.auth_google.db.get_user_by_external_account", user),
            ("src.routes.auth_google.db.touch_external_account_last_seen", True),
            ("src.routes.auth_google.db.get_user_accessible_projects", [project]),
            ("src.routes.auth_google.db.get_project_by_hash", project),
            ("src.routes.auth_google.db.get_user_groups_for_user", [group]),
        ):
            stack.enter_context(patch(target, return_value=value))
        yield


@pytest.mark.asyncio
async def test_google_oauth_start_callback_validate_refresh_logout_lifecycle(
    client,
    isolated_google_oauth_redis,
    fake_google_token_response,
    monkeypatch,
):
    monkeypatch.setenv("GOOGLE_OAUTH_ENABLED", "true")

    with _fake_google_e2e_seams(fake_google_token_response) as google_seams, _fake_provider_init_e2e_seams("fake-provider-init-e2e-token-not-real"):
        start = await client.post(
            START_PATH,
            json={
                "provider_init_token": "fake-provider-init-e2e-token-not-real",
                "redirect_uri": "http://localhost:8000/auth/google/callback",
                "return_origin": "http://localhost:3000",
            },
            headers={"User-Agent": "phase3-google-oauth-e2e-test"},
            follow_redirects=False,
        )
        _assert_oauth_route_exists(start, START_PATH)
        authorization_params = _authorization_params_from_start(start)
        emitted_state = authorization_params["state"]
        assert start.cookies.get("oauth_state") == fingerprint_oauth_value(emitted_state)
        pending_state_keys = set(isolated_google_oauth_redis.scan_iter("google_oauth_state:*"))
        assert len(pending_state_keys) == 1

        with _linked_google_identity_db_seams():
            callback = await client.get(
                CALLBACK_PATH,
                params={"code": "fake-google-auth-code-not-real", "state": emitted_state},
                headers={"User-Agent": "phase3-google-oauth-e2e-test"},
                follow_redirects=False,
            )
            _assert_oauth_route_exists(callback, CALLBACK_PATH)
            assert callback.status_code == 200
            data = callback.json()
            assert not pending_state_keys.intersection(
                isolated_google_oauth_redis.scan_iter("google_oauth_state:*")
            )
            assert len(
                set(isolated_google_oauth_redis.scan_iter("google_oauth_state_consumed:*"))
            ) == 1
            google_seams.token_client.exchange_authorization_code.assert_called_once()
            exchange_kwargs = (
                google_seams.token_client.exchange_authorization_code.call_args.kwargs
            )
            assert (
                build_pkce_s256_challenge(exchange_kwargs["code_verifier"])
                == authorization_params["code_challenge"]
            )
            assert (
                exchange_kwargs["redirect_uri"]
                == "http://localhost:8000/auth/google/callback"
            )
            assert (
                google_seams.id_token_verifier.call_args.kwargs["expected_nonce"]
                == authorization_params["nonce"]
            )

            access_claims = JWTTokenHandler.decode_access_token(data["access_token"])
            family_id = str(access_claims["family_id"])
            family = json.loads(isolated_google_oauth_redis.get(f"refresh_family:{family_id}"))
            assert family["status"] == "active"
            assert isolated_google_oauth_redis.get(f"revoked_family:{family_id}") is None

            validate = await client.get(
                "/auth/validate",
                headers={"Authorization": f"Bearer {data['access_token']}", "User-Agent": "phase3-google-oauth-e2e-test"},
            )
            assert validate.status_code == 200

            refresh = await client.post(
                "/auth/refresh",
                data={"refresh_token": data["refresh_token"]},
                cookies={"refresh_token": data["refresh_token"]},
                headers={"User-Agent": "phase3-google-oauth-e2e-test"},
            )
            assert refresh.status_code == 200
            assert refresh.json()["access_token"] != data["access_token"]

            logout = await client.post(
                "/auth/logout",
                headers={"Authorization": f"Bearer {refresh.json()['access_token']}", "User-Agent": "phase3-google-oauth-e2e-test"},
            )
            assert logout.status_code in {200, 204}


@pytest.mark.asyncio
async def test_google_oauth_link_unlink_middleware_skiplist_and_existing_flows_remain_compatible(
    client,
    isolated_google_oauth_redis,
    fake_google_token_response,
    monkeypatch,
):
    monkeypatch.setenv("GOOGLE_OAUTH_ENABLED", "true")

    with _fake_google_e2e_seams(fake_google_token_response), _fake_provider_init_e2e_seams("fake-provider-init-link-token-not-real"):
        start = await client.post(
            START_PATH,
            json={"provider_init_token": "fake-provider-init-link-token-not-real"},
            headers={"User-Agent": "phase3-google-oauth-e2e-test"},
            follow_redirects=False,
        )
        _assert_oauth_route_exists(start, START_PATH)
        assert start.status_code != 401, "start must be on middleware auth skip-list while audit remains active"

        link_start = await client.post(
            "/auth/google/link/start",
            headers={"Authorization": "Bearer fake-local-session-token", "User-Agent": "phase3-google-oauth-e2e-test"},
            follow_redirects=False,
        )
        assert link_start.status_code in {200, 302, 303, 401, 403}

        unlink = await client.delete(
            "/auth/google/unlink",
            headers={"Authorization": "Bearer fake-local-session-token", "User-Agent": "phase3-google-oauth-e2e-test"},
        )
        assert unlink.status_code in {200, 401, 403, 409}

        local_password_flow = await client.post(
            "/auth/login",
            data={"username": "nonexistent", "password": "wrong", "project_hash": "project-hash-redacted-by-contract"},
            headers={"User-Agent": "phase3-google-oauth-e2e-test"},
        )
        assert local_password_flow.status_code in {401, 403, 404}

        api_key_flow = await client.get(
            "/auth/validate",
            headers={"Authorization": "Bearer fake-api-key-or-session", "User-Agent": "phase3-google-oauth-e2e-test"},
        )
        assert api_key_flow.status_code in {200, 401, 403}
