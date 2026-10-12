"""Real session lifecycle and OAuth routes, with only provider/DB boundaries mocked."""

from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

import fakeredis
import httpx
import pytest
from redis import Redis
from fastapi import FastAPI

from src.Util import auth_flow, auth_lifecycle, oauth_state
from src.Util.oauth.pipeline import OAuthPipeline, PipelineDeps
from src.Util.oauth_rate_limit import OAuthRateLimiter
from src.Util.oauth_state import OAuthStateInvalidError, OAuthStateStore
from src.routes import auth_oauth
from tests.integration.test_oauth_generic_multitenant import FakeIdPAdapter, FakeSource, PROJECT_A


@pytest.fixture
def flow(monkeypatch):
    monkeypatch.setenv("OAUTH_ENABLED", "true")
    monkeypatch.setenv("OAUTH_RECENT_REAUTH_SECONDS", "300")
    monkeypatch.setenv("OAUTH_MAX_STATE_TTL_SECONDS", "600")
    test_url = os.environ.get("OAUTH_AUTHORIZATION_TEST_REDIS_URL")
    redis = Redis.from_url(test_url) if test_url else fakeredis.FakeStrictRedis()
    original_keys = set(redis.scan_iter()) if test_url else set()
    monkeypatch.setattr(auth_lifecycle, "redis_client", redis)
    monkeypatch.setattr(oauth_state, "redis_client", redis)
    monkeypatch.setattr("src.Util.cache_manager.cache_manager.redis", redis)
    monkeypatch.setattr("src.Util.session_plan.resolve_session_plan", lambda *args, **kwargs: None)
    user = SimpleNamespace(id="usr-victim", user_hash="uh-victim", username="victim", user_type="consumer", is_active=True, email=None)
    project = SimpleNamespace(id="prj-a", project_hash=PROJECT_A, project_name="A", project_description=None, is_active=True, archived=False)
    group = SimpleNamespace(id="grp-a", group_name="Consumers")
    db = SimpleNamespace(
        get_user_by_hash=Mock(return_value=user), get_project_by_hash=Mock(return_value=project),
        get_user_groups_in_project_by_hash=Mock(return_value=[group]), get_user_permissions=Mock(return_value=[]),
        get_user_accessible_projects=Mock(return_value=[project]), get_user_groups_for_user=Mock(return_value=[group]),
        get_user_by_external_account=Mock(return_value=None), link_external_account=Mock(return_value={"status": "linked"}),
        touch_external_account_last_seen=Mock(), handle_db_operation=lambda fn, **kwargs: fn(),
    )
    hooks = {name + "_fn": getattr(db, name) for name in (
        "get_user_by_hash", "get_project_by_hash", "get_user_groups_in_project_by_hash", "get_user_permissions", "get_user_accessible_projects"
    )}
    monkeypatch.setattr(auth_oauth, "validate_access_session", lambda token: auth_lifecycle.validate_access_session(token, **hooks))

    class Adapter(FakeIdPAdapter):
        exchange_hook = None

        async def exchange_code(self, *args):
            if self.exchange_hook is not None:
                await self.exchange_hook()
            return await super().exchange_code(*args)

    adapter = Adapter()
    source = FakeSource(adapter)
    store = OAuthStateStore(redis_client=redis)
    events = []

    async def activity(*args, **kwargs):
        events.append(kwargs.get("details", {}))

    pipeline = OAuthPipeline(PipelineDeps(db=db, state_store=lambda: store, rate_limiter=lambda: OAuthRateLimiter(redis_client=redis),
                                         connection_source=lambda: source, record_activity=activity))
    monkeypatch.setattr(auth_oauth, "get_connection_source", lambda: source)
    monkeypatch.setattr(auth_oauth, "build_pipeline", lambda: pipeline)
    app = FastAPI()
    app.include_router(auth_oauth.router)

    def issue(auth_age=0):
        with patch.object(auth_lifecycle, "_utc_now", return_value=datetime.now(timezone.utc) - timedelta(seconds=auth_age)):
            return auth_lifecycle.issue_project_token_pair(user=vars(user), project=vars(project), groups=[group.group_name], group_ids=[group.id])

    pair = issue()
    yield SimpleNamespace(redis=redis, store=store, db=db, user=user, project=project, adapter=adapter, source=source,
                          app=app, pair=pair, issue=issue, hooks=hooks, events=events)
    if test_url:
        created_keys = set(redis.scan_iter()) - original_keys
        if created_keys:
            redis.delete(*created_keys)
        redis.close()


def client(flow):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=flow.app), base_url="https://test")


async def start(ac, flow, purpose="link", pair=None):
    pair = pair or flow.pair
    response = await ac.post(f"/auth/oauth/fakeidp/{purpose}/start", headers={"Authorization": "Bearer " + pair.access_token},
                             json={"return_origin": "https://a.example"}, follow_redirects=False)
    assert response.status_code == 303, response.text
    return parse_qs(urlparse(response.headers["location"]).query)["state"][0]


async def callback(ac, state, method="GET"):
    # BFF relays deliberately carry neither a local token nor a binding cookie.
    ac.cookies.clear()
    data = {"state": state, "code": "attacker-subject"}
    return await ac.get("/auth/oauth/callback", params=data) if method == "GET" else await ac.post("/auth/oauth/callback", data=data)


def assert_rejected(response, flow, code=None):
    assert response.status_code in {401, 403}, response.text
    if code is not None:
        assert response.json()["error"]["code"] == code
    flow.db.link_external_account.assert_not_called()


@pytest.mark.parametrize("purpose", ["link", "reauth"])
@pytest.mark.parametrize("revocation", ["access", "logout", "all", "password_reset"])
async def test_revocation_invalidates_pending_callbacks(flow, purpose, revocation):
    flow.db.get_user_by_external_account.return_value = flow.user if purpose == "reauth" else None
    async with client(flow) as ac:
        state = await start(ac, flow, purpose)
        if revocation == "access":
            auth_lifecycle.revoke_access_session(flow.pair.access_claims["jti"])
        elif revocation == "logout":
            auth_lifecycle.revoke_refresh_family(flow.pair.access_claims["family_id"], reason="logout")
        else:
            auth_lifecycle.revoke_user_auth_state(flow.user.id, reason=revocation)
        result = await callback(ac, state)
    assert_rejected(result, flow, "EXT_8024" if purpose == "link" else "EXT_8028")
    assert not flow.adapter.exchanged, "preflight should reject before contacting the provider"
    assert not flow.store.has_recent_reauth(user_id=flow.user.id, session_id=flow.pair.access_claims["session_id"])


@pytest.mark.parametrize("purpose", ["link", "reauth"])
@pytest.mark.parametrize("method", ["GET", "POST"])
async def test_valid_callbacks_and_refresh_keep_original_session(flow, purpose, method):
    flow.db.get_user_by_external_account.return_value = flow.user if purpose == "reauth" else None
    async with client(flow) as ac:
        state = await start(ac, flow, purpose)
        rotated = auth_lifecycle.rotate_refresh_family(flow.pair.refresh_token, **flow.hooks)
        assert rotated.token_pair.access_claims["session_id"] == flow.pair.access_claims["session_id"]
        assert not flow.redis.exists("session:" + flow.pair.access_claims["jti"])
        result = await callback(ac, state, method)
        assert result.status_code == 200, result.text
        replay = await callback(ac, state, method)
    assert replay.status_code == 401 and replay.json()["error"]["code"] == "EXT_8016"
    marker = flow.store.has_recent_reauth(user_id=flow.user.id, session_id=flow.pair.access_claims["session_id"])
    assert marker == (purpose == "reauth")
    assert flow.db.link_external_account.call_count == (1 if purpose == "link" else 0)
    assert not list(flow.redis.scan_iter(match="oauth_completion:*"))


@pytest.mark.parametrize("action", ["revocation", "refresh", "grant_expiry"])
@pytest.mark.parametrize("purpose", ["link", "reauth"])
async def test_authorization_is_rechecked_after_provider_exchange(flow, action, purpose):
    flow.db.get_user_by_external_account.return_value = flow.user if purpose == "reauth" else None
    entered, released = asyncio.Event(), asyncio.Event()

    async def wait_at_provider():
        entered.set()
        await released.wait()

    flow.adapter.exchange_hook = wait_at_provider
    async with client(flow) as ac:
        state = await start(ac, flow, purpose)
        task = asyncio.create_task(callback(ac, state))
        await asyncio.wait_for(entered.wait(), 3)
        try:
            if action == "revocation":
                auth_lifecycle.revoke_refresh_family(flow.pair.access_claims["family_id"], reason="logout")
            elif action == "refresh":
                auth_lifecycle.rotate_refresh_family(flow.pair.refresh_token, **flow.hooks)
            else:
                flow.redis.pexpire(next(flow.redis.scan_iter(match="oauth_completion:*")), 0)
        finally:
            released.set()
        response = await asyncio.wait_for(task, 3)
    if action == "refresh":
        assert response.status_code == 200, response.text
    else:
        assert_rejected(response, flow)
        assert not flow.store.has_recent_reauth(user_id=flow.user.id, session_id=flow.pair.access_claims["session_id"])


@pytest.mark.parametrize("action", ["revocation", "refresh", "grant_expiry", "marker_replaced"])
@pytest.mark.parametrize("purpose", ["link", "reauth"])
async def test_final_transaction_observes_concurrent_mutation(flow, monkeypatch, action, purpose):
    flow.db.get_user_by_external_account.return_value = flow.user if purpose == "reauth" else None
    if action == "marker_replaced":
        flow.pair = flow.issue(auth_age=301)
        flow.store.mark_recent_reauth(user_id=flow.user.id, session_id=flow.pair.access_claims["session_id"])
    original_pipeline = flow.redis.pipeline
    mutated = False

    def pipeline(*args, **kwargs):
        nonlocal mutated
        pipe = original_pipeline(*args, **kwargs)
        original_execute = pipe.execute

        def execute(*args, **kwargs):
            nonlocal mutated
            finalizing = any(command[0] == "DEL" and str(command[1]).startswith("oauth_completion:") for command, _ in pipe.command_stack)
            if finalizing and not mutated:
                mutated = True
                if action == "revocation":
                    auth_lifecycle.revoke_refresh_family(flow.pair.access_claims["family_id"], reason="logout")
                elif action == "refresh":
                    auth_lifecycle.rotate_refresh_family(flow.pair.refresh_token, **flow.hooks)
                elif action == "grant_expiry":
                    flow.redis.pexpire(next(flow.redis.scan_iter(match="oauth_completion:*")), 0)
                else:
                    flow.store.mark_recent_reauth(user_id=flow.user.id, session_id=flow.pair.access_claims["session_id"])
            return original_execute(*args, **kwargs)

        pipe.execute = execute
        return pipe

    monkeypatch.setattr(flow.redis, "pipeline", pipeline)
    async with client(flow) as ac:
        state = await start(ac, flow, purpose)
        response = await callback(ac, state)
    assert mutated
    if action == "refresh" or (action == "marker_replaced" and purpose == "reauth"):
        assert response.status_code == 200, response.text
    else:
        assert_rejected(response, flow)


@pytest.mark.parametrize("during_exchange", [False, True])
async def test_original_proof_expiry_cannot_be_renewed(flow, monkeypatch, during_exchange):
    async with client(flow) as ac:
        state = await start(ac, flow)
        future = datetime.now(timezone.utc) + timedelta(seconds=301)

        async def expire_proof():
            monkeypatch.setattr(oauth_state, "time", SimpleNamespace(time=lambda: future.timestamp()))
            monkeypatch.setattr(auth_lifecycle, "_utc_now", lambda: future)
            # A new proof for the same session cannot extend this transaction.
            flow.store.mark_recent_reauth(user_id=flow.user.id, session_id=flow.pair.access_claims["session_id"])

        if during_exchange:
            flow.adapter.exchange_hook = expire_proof
        else:
            await expire_proof()
        result = await callback(ac, state)
    assert_rejected(result, flow, "EXT_8014")
    assert bool(flow.adapter.exchanged) == during_exchange


@pytest.mark.parametrize("change", ["deleted", "replaced"])
async def test_link_requires_the_original_reauth_marker(flow, change):
    flow.pair = flow.issue(auth_age=301)
    key = flow.store.mark_recent_reauth(user_id=flow.user.id, session_id=flow.pair.access_claims["session_id"])
    async with client(flow) as ac:
        state = await start(ac, flow)
        if change == "deleted":
            flow.redis.delete(key)
        else:
            flow.store.mark_recent_reauth(user_id=flow.user.id, session_id=flow.pair.access_claims["session_id"])
        result = await callback(ac, state)
    assert_rejected(result, flow, "EXT_8024")


@pytest.mark.parametrize("change", [
    "user", "session", "family", "scope", "project", "missing_session", "expired_session", "expired_family",
    "inactive_user", "inactive_project", "project_access",
])
async def test_live_context_cannot_be_substituted(flow, change):
    async with client(flow) as ac:
        state = await start(ac, flow)
        key = "session:" + flow.pair.access_claims["jti"]
        payload = json.loads(flow.redis.get(key))
        fields = {"user": "user_id", "session": "session_id", "family": "family_id", "scope": "scope", "project": "project_hash"}
        if change in fields:
            payload[fields[change]] = "another-context"
            flow.redis.set(key, json.dumps(payload), ex=600)
        elif change == "missing_session":
            flow.redis.delete(key)
            assert flow.redis.exists("refresh_anchor:" + flow.pair.access_claims["family_id"])
        elif change in {"expired_session", "expired_family"}:
            if change == "expired_family":
                key = "refresh_family:" + flow.pair.access_claims["family_id"]
                payload = json.loads(flow.redis.get(key))
            payload["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
            flow.redis.set(key, json.dumps(payload), ex=600)
        elif change == "inactive_user":
            flow.user.is_active = False
        elif change == "inactive_project":
            flow.project.is_active = False
        else:
            flow.db.get_user_groups_in_project_by_hash.return_value = []
        result = await callback(ac, state)
    assert_rejected(result, flow, "EXT_8025" if change in {"project_access", "inactive_project"} else "EXT_8024")


async def test_revoking_other_sessions_preserves_pending_authorization(flow):
    other = flow.issue()
    async with client(flow) as ac:
        state = await start(ac, flow)
        auth_lifecycle.revoke_user_auth_state_except_current(flow.user.id, current_access_jti=flow.pair.access_claims["jti"],
                                                          current_family_id=flow.pair.access_claims["family_id"], reason="password_change")
        assert not flow.redis.exists("session:" + other.access_claims["jti"])
        result = await callback(ac, state)
    assert result.status_code == 200, result.text


@pytest.mark.parametrize("purpose", ["login", "link", "reauth"])
def test_legacy_state_is_accepted_only_for_login(flow, purpose):
    created = flow.store.create_state(oauth_binding={"purpose": "login"})
    key = next(flow.redis.scan_iter(match="oauth_state:*"))
    payload = json.loads(flow.redis.get(key))
    payload.update(version=2, purpose=purpose)
    flow.redis.set(key, json.dumps(payload), ex=600)
    if purpose == "login":
        assert flow.store.consume_state(created.state).version == 2
    else:
        with pytest.raises(OAuthStateInvalidError):
            flow.store.consume_state(created.state)


async def test_snapshot_has_no_tokens_and_uses_shorter_original_proof_deadline(flow):
    flow.pair = flow.issue(auth_age=290)
    async with client(flow) as ac:
        state = await start(ac, flow)
    state_key = next(flow.redis.scan_iter(match="oauth_state:*"))
    grant_key = next(flow.redis.scan_iter(match="oauth_completion:*"))
    assert 0 < flow.redis.pttl(grant_key) <= 10000
    assert abs(flow.redis.pttl(state_key) - flow.redis.pttl(grant_key)) < 100
    serialized = b" ".join(flow.redis.get(key) for key in (state_key, grant_key)).decode()
    assert flow.pair.access_token not in serialized and flow.pair.refresh_token not in serialized
    assert state not in grant_key.decode() and state not in state_key.decode()
    record = flow.store.consume_state(state)
    assert record.authorization.family_id == flow.pair.access_claims["family_id"]


async def test_completed_link_does_not_replace_existing_marker(flow):
    flow.pair = flow.issue(auth_age=301)
    key = flow.store.mark_recent_reauth(user_id=flow.user.id, session_id=flow.pair.access_claims["session_id"])
    original = flow.redis.get(key)
    async with client(flow) as ac:
        response = await callback(ac, await start(ac, flow))
    assert response.status_code == 200, response.text
    assert flow.redis.get(key) == original


async def test_redis_failure_during_completion_fails_closed(flow, monkeypatch):
    async def fail_store():
        monkeypatch.setattr(flow.redis, "pipeline", Mock(side_effect=RuntimeError("unavailable")))

    flow.adapter.exchange_hook = fail_store
    async with client(flow) as ac:
        result = await callback(ac, await start(ac, flow))
    assert_rejected(result, flow, "EXT_8014")


async def test_project_switch_invalidates_the_original_context(flow):
    other_project = SimpleNamespace(id="prj-b", project_hash="project-b", project_name="B", is_active=True, archived=False)
    async with client(flow) as ac:
        state = await start(ac, flow)
        flow.db.get_project_by_hash.return_value = other_project
        auth_lifecycle.rotate_refresh_family(flow.pair.refresh_token, target_project=other_project, **flow.hooks)
        result = await callback(ac, state)
    assert_rejected(result, flow, "EXT_8024")


@pytest.mark.parametrize("change", ["missing_snapshot", "invalid_proof", "binding_mismatch", "unsupported_version", "changed_grant"])
async def test_malformed_state_or_completion_authorization_is_rejected(flow, change):
    async with client(flow) as ac:
        state = await start(ac, flow)
        key = next(flow.redis.scan_iter(match="oauth_state:*"))
        payload = json.loads(flow.redis.get(key))
        if change == "missing_snapshot":
            payload.pop("authorization")
        elif change == "invalid_proof":
            payload["authorization"]["proof"]["expires_at_ms"] = "invalid"
        elif change == "binding_mismatch":
            payload["user_id"] = "another-user"
        elif change == "unsupported_version":
            payload["version"] = 999
        else:
            grant = next(flow.redis.scan_iter(match="oauth_completion:*"))
            flow.redis.set(grant, "{}", ex=600)
        flow.redis.set(key, json.dumps(payload), ex=600)
        result = await callback(ac, state)
    assert_rejected(result, flow, "EXT_8014")
    assert not flow.adapter.exchanged


async def test_start_refuses_stale_proof_but_chooses_fresh_marker(flow):
    flow.pair = flow.issue(auth_age=301)
    async with client(flow) as ac:
        stale = await ac.post("/auth/oauth/fakeidp/link/start", headers={"Authorization": "Bearer " + flow.pair.access_token},
                              json={"return_origin": "https://a.example"})
        assert stale.status_code == 401 and stale.json()["error"]["code"] == "EXT_8024"
        assert not list(flow.redis.scan_iter(match="oauth_state:*"))
        flow.store.mark_recent_reauth(user_id=flow.user.id, session_id=flow.pair.access_claims["session_id"])
        record = flow.store.consume_state(await start(ac, flow))
    assert record.authorization.proof.source == "marker"


async def test_freshest_proof_is_used_without_renewing_it(flow):
    flow.pair = flow.issue(auth_age=290)
    marker_key = flow.store.mark_recent_reauth(user_id=flow.user.id, session_id=flow.pair.access_claims["session_id"])
    raw = flow.redis.get(marker_key)
    proof = auth_flow.resolve_recent_authentication_proof(user_id=flow.user.id, access_token=flow.pair.access_token,
                                                         session_id=flow.pair.access_claims["session_id"], reauth_store=flow.store)
    assert proof.source == "marker"
    assert flow.redis.get(marker_key) == raw
    async with client(flow) as ac:
        state = await start(ac, flow)
    record = flow.store.consume_state(state)
    assert record.authorization.proof.source == "marker"
    assert record.authorization.proof.expires_at_ms <= proof.expires_at_ms + 100


async def test_newer_sign_in_proof_is_preferred_over_older_marker(flow):
    key = flow.store.mark_recent_reauth(user_id=flow.user.id, session_id=flow.pair.access_claims["session_id"])
    payload = json.loads(flow.redis.get(key))
    payload["created_at"] = (datetime.now(timezone.utc) - timedelta(seconds=290)).isoformat()
    flow.redis.set(key, json.dumps(payload), ex=10)
    async with client(flow) as ac:
        state = await start(ac, flow)
    assert flow.store.consume_state(state).authorization.proof.source == "token"


async def test_repeated_final_conflicts_stop_after_three_attempts(flow, monkeypatch):
    original_pipeline = flow.redis.pipeline
    conflicts = 0

    def pipeline(*args, **kwargs):
        pipe = original_pipeline(*args, **kwargs)
        original_execute = pipe.execute

        def execute(*args, **kwargs):
            nonlocal conflicts
            if any(command[0] == "DEL" and str(command[1]).startswith("oauth_completion:") for command, _ in pipe.command_stack):
                conflicts += 1
                key = "session:" + flow.pair.access_claims["jti"]
                payload = json.loads(flow.redis.get(key))
                payload["concurrent_update"] = conflicts
                flow.redis.set(key, json.dumps(payload), ex=600)
            return original_execute(*args, **kwargs)

        pipe.execute = execute
        return pipe

    monkeypatch.setattr(flow.redis, "pipeline", pipeline)
    async with client(flow) as ac:
        result = await callback(ac, await start(ac, flow))
    assert_rejected(result, flow, "EXT_8024")
    assert conflicts == 3
    assert flow.events[-1]["sub_reason"] == "session_changed_during_authorization"


@pytest.mark.skipif(not os.environ.get("OAUTH_AUTHORIZATION_TEST_REDIS_URL"), reason="requires isolated real Redis")
async def test_natural_expiry_of_watched_grant_prevents_completion(flow, monkeypatch):
    original_pipeline = flow.redis.pipeline
    delayed = False

    def pipeline(*args, **kwargs):
        pipe = original_pipeline(*args, **kwargs)
        original_execute = pipe.execute

        def execute(*args, **kwargs):
            nonlocal delayed
            if not delayed and any(command[0] == "DEL" and str(command[1]).startswith("oauth_completion:") for command, _ in pipe.command_stack):
                delayed = True
                # Arrange a natural expiry before this final transaction watches
                # the record, then let Redis expire it while EXEC is held back.
                time.sleep(0.3)
            return original_execute(*args, **kwargs)

        pipe.execute = execute
        return pipe

    async with client(flow) as ac:
        state = await start(ac, flow)
        key = next(flow.redis.scan_iter(match="oauth_completion:*"))
        flow.redis.pexpire(key, 250)
        monkeypatch.setattr(flow.redis, "pipeline", pipeline)
        result = await callback(ac, state)
    assert delayed
    assert_rejected(result, flow, "EXT_8014")


async def test_revocation_after_final_authorization_does_not_undo_the_link(flow):
    def authorized_sql_write(**kwargs):
        assert not list(flow.redis.scan_iter(match="oauth_completion:*"))
        auth_lifecycle.revoke_refresh_family(flow.pair.access_claims["family_id"], reason="logout")
        return {"status": "linked"}

    flow.db.link_external_account.side_effect = authorized_sql_write
    async with client(flow) as ac:
        result = await callback(ac, await start(ac, flow))
    assert result.status_code == 200, result.text
    assert flow.db.link_external_account.call_count == 1
    assert auth_lifecycle.is_refresh_family_revoked(flow.pair.access_claims["family_id"])


@pytest.mark.parametrize("version", [2, 3])
async def test_login_callback_remains_compatible_and_issues_session(flow, version):
    flow.db.get_user_by_external_account.return_value = flow.user
    resolved = flow.source.bindings[PROJECT_A]
    created = flow.store.create_state(oauth_binding={
        "purpose": "login", "provider": "fakeidp", "connection_id": resolved.config.connection_id,
        "binding_id": resolved.binding.binding_id, "project_hash": PROJECT_A,
        "redirect_uri": resolved.binding.redirect_uris[0], "return_origin": "https://a.example",
    })
    key = next(flow.redis.scan_iter(match="oauth_state:*"))
    payload = json.loads(flow.redis.get(key))
    payload["version"] = version
    flow.redis.set(key, json.dumps(payload), ex=600)
    async with client(flow) as ac:
        response = await callback(ac, created.state)
    assert response.status_code == 200, response.text
    assert response.json()["user"]["user_hash"] == flow.user.user_hash
    assert response.json()["access_token"] != flow.pair.access_token
    assert "access_token" in response.cookies
    assert not list(flow.redis.scan_iter(match="oauth_completion:*"))
    flow.db.link_external_account.assert_not_called()


async def test_reauth_requires_live_session_but_not_prior_recent_proof(flow):
    flow.pair = flow.issue(auth_age=301)
    flow.db.get_user_by_external_account.return_value = flow.user
    assert not auth_flow.access_token_has_recent_auth(flow.pair.access_token)
    assert not flow.store.has_recent_reauth(user_id=flow.user.id, session_id=flow.pair.access_claims["session_id"])
    async with client(flow) as ac:
        result = await callback(ac, await start(ac, flow, "reauth"))
    assert result.status_code == 200 and result.json()["reauthenticated"] is True
    assert auth_flow.require_recent_reauthentication(user_id=flow.user.id, access_token=flow.pair.access_token,
                                                     session_id=flow.pair.access_claims["session_id"], reauth_store=flow.store)
