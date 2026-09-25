"""WebSocket auth, disconnect/replay and job lifecycle without external models."""
import asyncio
from contextlib import asynccontextmanager
import threading
import time
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from src.assistant.models import AssistantError
from src.assistant.runtime import RuntimeResult
from src.assistant.service import AssistantService
from tests.helpers.assistant_memory import MemoryAssistantStore
from src.routes.assistant import origin_allowed, router


async def root_auth(token):
    if token not in {"root-a", "root-b"}:
        raise AssistantError("unauthorized", "A current root session is required")
    return SimpleNamespace(user_id=token, user_type="root")


@pytest.fixture
def environment(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://dashboard.test")
    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
            await app.state.assistant_service.close()

    app = FastAPI(lifespan=lifespan)
    app.include_router(router)
    store = MemoryAssistantStore()
    service = AssistantService(app, store, authenticator=root_auth)
    app.state.assistant_service = service
    return app, store, service


def rpc(ws, method, params=None):
    ws.send_json({"id": "call", "method": method, "params": params or {}})
    while True:
        response = ws.receive_json()
        if response.get("id") == "call":
            assert "error" not in response, response
            return response["result"]


def headers(token="root-a"):
    return {"origin": "http://dashboard.test", "cookie": f"session_token={token}"}


def test_websocket_denies_nonroot_and_cross_origin(environment):
    app, _, service = environment
    with TestClient(app) as client:
        for request_headers in ({"origin": "https://attacker.test", "cookie": "session_token=root-a"}, headers("admin"), headers("consumer"), {"cookie": "session_token=root-a"}):
            with pytest.raises(WebSocketDisconnect):
                with client.websocket_connect("/admin/assistant/ws", headers=request_headers) as ws:
                    ws.receive_json()
        with client.websocket_connect("/admin/assistant/ws", headers=headers()) as ws:
            data = rpc(ws, "bootstrap")
            assert not data["settings"]["mutations_enabled"]
            assert data["profiles"][0]["provider"] == "ollama"
            assert "api_key" not in data["profiles"][0]
            assert service.monitor_task is not None and not service.monitor_task.done()


def test_disconnect_does_not_cancel_and_snapshot_replays(environment):
    app, store, service = environment
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    async def runner(context, emit):
        await emit("message.delta", {"content": "First "})
        started.set()
        await asyncio.to_thread(release.wait, 5)
        await emit("message.delta", {"content": "second"})
        finished.set()
        return RuntimeResult(status="completed", content="First second", usage={"input_tokens": 3, "output_tokens": 2, "total_tokens": 5})
    service.runner = runner
    with TestClient(app) as client:
        with client.websocket_connect("/admin/assistant/ws", headers=headers()) as ws:
            rpc(ws, "bootstrap")
            rpc(ws, "settings.update", {"enabled": True})
            session = rpc(ws, "sessions.create")
            run = rpc(ws, "runs.start", {"session_id": session["id"], "message": "Hello", "request_id": "once"})
            assert started.wait(3)
        # The browser has closed; the backend task is still awaiting work.
        assert not finished.is_set()
        assert store.run("root-a", run["id"])["status"] == "running"
        with client.websocket_connect("/admin/assistant/ws", headers=headers()) as ws:
            snapshot = rpc(ws, "sessions.get", {"session_id": session["id"]})
            assert snapshot["partial_content"] == "First "
            rpc(ws, "sessions.subscribe", {"session_id": session["id"], "after_seq": snapshot["last_seq"]})
            release.set()
            seen = []
            while True:
                event = ws.receive_json()
                seen.append(event)
                if event["kind"] == "run.status" and event["data"]["status"] == "completed":
                    break
            assert [e["data"]["content"] for e in seen if e["kind"] == "message.delta"] == ["second"]
            assert len([e for e in seen if e["kind"] == "message.completed"]) == 1
            snapshot = rpc(ws, "sessions.get", {"session_id": session["id"]})
            assert snapshot["messages"][-1]["content"] == "First second"
            again = rpc(ws, "runs.start", {"session_id": session["id"], "message": "Hello", "request_id": "once"})
            assert again["id"] == run["id"]
            assert len(store.messages("root-a", session["id"])) == 2
        with client.websocket_connect("/admin/assistant/ws", headers=headers("root-b")) as ws:
            ws.send_json({"id": "cross", "method": "sessions.get", "params": {"session_id": session["id"]}})
            assert ws.receive_json()["error"]["code"] == "not_found"


@pytest.mark.asyncio
async def test_event_writes_wake_only_their_session_watchers(environment):
    _, _, service = environment
    await service.authorize("root-a")
    await service.dispatch("root-a", "bootstrap", {})
    first = await service.dispatch("root-a", "sessions.create", {})
    second = await service.dispatch("root-a", "sessions.create", {})
    with service.watch(first["id"]) as first_wake, service.watch(second["id"]) as second_wake:
        await service.event(first["id"], "test.event", {"value": 1})
        assert first_wake.is_set()
        assert not second_wake.is_set()
    # Closed subscriptions must not leave waiters behind for later writes.
    assert service.event_waiters == {}


def test_idle_subscription_backs_off_and_wakes_on_local_events(environment, monkeypatch):
    app, store, _ = environment
    # An idle ceiling far beyond the assertion window means the event can only
    # arrive in time through the in-process wake-up, not the fallback poll.
    monkeypatch.setattr("src.routes.assistant.STREAM_POLL_SECONDS", 0.01)
    monkeypatch.setattr("src.routes.assistant.STREAM_IDLE_POLL_SECONDS", 30)
    reads = []
    original_events = store.events

    def counted_events(*args, **kwargs):
        reads.append(time.monotonic())
        return original_events(*args, **kwargs)

    monkeypatch.setattr(store, "events", counted_events)
    with TestClient(app) as client:
        with client.websocket_connect("/admin/assistant/ws", headers=headers()) as ws:
            rpc(ws, "bootstrap")
            session = rpc(ws, "sessions.create")
            snapshot = rpc(ws, "sessions.get", {"session_id": session["id"]})
            rpc(ws, "sessions.subscribe", {"session_id": session["id"], "after_seq": snapshot["last_seq"]})
            deadline = time.monotonic() + 5
            while len(reads) < 7 and time.monotonic() < deadline:
                time.sleep(0.01)
            assert len(reads) >= 7
            # A fixed 10 ms interval would need about 60 ms for seven reads;
            # doubling waits need at least 1.26 s and are now waiting 1.28 s.
            assert reads[6] - reads[0] > 0.5
            sent = time.monotonic()
            ws.send_json({"id": "wake", "method": "settings.update", "params": {"enabled": True}})
            while True:
                message = ws.receive_json()
                if message.get("kind") == "settings.updated":
                    break
            assert time.monotonic() - sent < 0.6


@pytest.mark.asyncio
async def test_disable_cancels_run_and_history_uses_completed_only(environment):
    _, store, service = environment
    started = asyncio.Event()
    async def runner(context, emit):
        started.set()
        await asyncio.Event().wait()
    service.runner = runner
    await service.authorize("root-a")
    await service.dispatch("root-a", "bootstrap", {})
    await service.dispatch("root-a", "settings.update", {"enabled": True})
    session = await service.dispatch("root-a", "sessions.create", {})
    run = await service.dispatch("root-a", "runs.start", {"session_id": session["id"], "message": "Never replay this", "request_id": "1"})
    await asyncio.wait_for(started.wait(), 3)
    await service.dispatch("root-a", "settings.update", {"enabled": False})
    await asyncio.gather(*list(service.tasks.values()))
    assert store.run("root-a", run["id"])["status"] == "cancelled"
    assert store.history("root-a", session["id"]) == []
    await service.close()


@pytest.mark.asyncio
async def test_usage_cumulative_callback_is_not_double_counted(environment):
    _, store, service = environment
    async def runner(context, emit):
        await emit("usage", {"input_tokens": 2, "output_tokens": 1, "total_tokens": 3})
        await emit("usage", {"input_tokens": 5, "output_tokens": 3, "total_tokens": 8})
        return RuntimeResult(status="completed", content="Done", usage={"input_tokens": 5, "output_tokens": 3, "total_tokens": 8})
    service.runner = runner
    await service.authorize("root-a")
    await service.dispatch("root-a", "bootstrap", {})
    await service.dispatch("root-a", "settings.update", {"enabled": True})
    session = await service.dispatch("root-a", "sessions.create", {})
    await service.dispatch("root-a", "runs.start", {"session_id": session["id"], "message": "Hello", "request_id": "usage"})
    await asyncio.gather(*list(service.tasks.values()))
    assert store.usage("root-a")["total_tokens"] == 8
    await service.close()


def test_exact_origin_matching(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://dashboard.example")
    assert origin_allowed("https://dashboard.example", None)
    assert not origin_allowed("https://dashboard.example.attacker.test", None)
    assert not origin_allowed("null", "Bearer root")
    assert not origin_allowed(None, None)
    assert origin_allowed(None, "Bearer root")


@pytest.mark.asyncio
async def test_old_tab_cannot_replace_newer_valid_credential(environment):
    import base64
    import json
    _, _, service = environment
    async def authenticate(_):
        return SimpleNamespace(user_id="root-a", user_type="root")
    service.authenticator = authenticate
    def token(expiry):
        payload = base64.urlsafe_b64encode(json.dumps({"exp": expiry}).encode()).decode().rstrip("=")
        return "header." + payload + ".signature"
    await service.authorize(token(200))
    await service.authorize(token(100))
    assert service.tokens["root-a"] == token(200)


@pytest.mark.asyncio
async def test_cancellation_after_claim_is_immediately_terminal(environment):
    _, store, service = environment
    await service.authorize("root-a")
    await service.dispatch("root-a", "bootstrap", {})
    await service.dispatch("root-a", "settings.update", {"enabled": True})
    session = await service.dispatch("root-a", "sessions.create", {})
    claimed = asyncio.Event()
    original_db = service.db
    async def delayed_db(method, *args, **kwargs):
        result = await original_db(method, *args, **kwargs)
        if method == "claim":
            claimed.set()
            await asyncio.Event().wait()
        return result
    service.db = delayed_db
    run = await service.dispatch("root-a", "runs.start", {"session_id": session["id"], "message": "Cancel during claim", "request_id": "claim"})
    await asyncio.wait_for(claimed.wait(), 3)
    await service.dispatch("root-a", "runs.cancel", {"session_id": session["id"], "run_id": run["id"]})
    await asyncio.gather(*list(service.tasks.values()))
    assert store.run("root-a", run["id"])["status"] == "cancelled"


@pytest.mark.asyncio
async def test_stale_worker_loses_tool_capabilities_and_cannot_finish(environment):
    _, store, service = environment
    async def runner(context, emit):
        store.update_run("root-a", context.run_id, "interrupted")
        policy = await context.executor.policy_loader()
        assert not policy["enabled"]
        assert not policy["mutations_enabled"]
        return RuntimeResult(status="completed", content="Must not overwrite interrupted run")
    service.runner = runner
    await service.authorize("root-a")
    await service.dispatch("root-a", "bootstrap", {})
    await service.dispatch("root-a", "settings.update", {"enabled": True})
    session = await service.dispatch("root-a", "sessions.create", {})
    run = await service.dispatch("root-a", "runs.start", {"session_id": session["id"], "message": "Fencing", "request_id": "fence"})
    await asyncio.gather(*list(service.tasks.values()))
    assert store.run("root-a", run["id"])["status"] == "interrupted"
    assert all(m["role"] != "assistant" for m in store.messages("root-a", session["id"]))


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["cancel", "provider_error"])
@pytest.mark.parametrize("status,reassigned", [("interrupted", False), ("running", True), ("queued", True)])
async def test_old_worker_failure_cannot_overwrite_recovered_or_reassigned_run(environment, failure, status, reassigned):
    _, store, service = environment

    async def runner(context, emit):
        store.update_run("root-a", context.run_id, status)
        if reassigned:
            store.reassign_worker(context.run_id, "replacement-worker")
        if failure == "cancel":
            raise asyncio.CancelledError()
        raise RuntimeError("A provider request failed after ownership was lost")

    service.runner = runner
    await service.authorize("root-a")
    await service.dispatch("root-a", "bootstrap", {})
    await service.dispatch("root-a", "settings.update", {"enabled": True})
    session = await service.dispatch("root-a", "sessions.create", {})
    run = await service.dispatch("root-a", "runs.start", {"session_id": session["id"], "message": "Fenced failure", "request_id": "failure-fence"})
    await asyncio.gather(*list(service.tasks.values()))
    saved = store.run("root-a", run["id"])
    assert saved["status"] == status
    assert saved["worker"] == ("replacement-worker" if reassigned else service.worker_id)
    assert not any(event["kind"] == "run.status" and event["data"]["status"] in {"failed", "cancelled"}
                   for event in store.events("root-a", session["id"]))


@pytest.mark.asyncio
@pytest.mark.parametrize("failure,terminal_status", [("cancel", "cancelled"), ("provider_error", "failed")])
async def test_failure_handler_survives_atomic_ownership_loss_between_read_and_update(environment, failure, terminal_status):
    _, store, service = environment
    attempted = []
    original_db = service.db

    async def fenced_db(method, *args, **kwargs):
        if method == "update_run" and args[2] == terminal_status:
            attempted.append(kwargs)
            # Model the native store's row-lock check rejecting a race after the
            # service read, before its conditional update can acquire the lock.
            store.update_run(args[0], args[1], "interrupted")
            raise AssistantError("ownership_lost", "A different worker recovered this run")
        return await original_db(method, *args, **kwargs)

    async def runner(context, emit):
        if failure == "cancel":
            raise asyncio.CancelledError()
        raise RuntimeError("provider failure")

    service.db = fenced_db
    service.runner = runner
    await service.authorize("root-a")
    await service.dispatch("root-a", "bootstrap", {})
    await service.dispatch("root-a", "settings.update", {"enabled": True})
    session = await service.dispatch("root-a", "sessions.create", {})
    run = await service.dispatch("root-a", "runs.start", {"session_id": session["id"], "message": "Atomic fencing", "request_id": "atomic-fence"})
    await asyncio.gather(*list(service.tasks.values()))
    assert attempted and attempted[0]["expected_worker"] == service.worker_id
    assert store.run("root-a", run["id"])["status"] == "interrupted"
    assert not any(event["kind"] == "run.status" and event["data"]["status"] == terminal_status
                   for event in store.events("root-a", session["id"]))


@pytest.mark.asyncio
async def test_failed_conditional_heartbeat_cancels_its_own_generation(environment, monkeypatch):
    _, store, service = environment
    started, cancelled = asyncio.Event(), asyncio.Event()
    original_sleep = asyncio.sleep
    original_db = service.db

    async def fast_heartbeat_sleep(delay, *args, **kwargs):
        return await original_sleep(0 if delay == 3 else delay, *args, **kwargs)

    monkeypatch.setattr("src.assistant.service.asyncio.sleep", fast_heartbeat_sleep)

    async def lose_heartbeat(method, *args, **kwargs):
        if method == "heartbeat":
            await started.wait()
            assert kwargs["worker"] == service.worker_id
            store.reassign_worker(args[0], "replacement-worker")
            return False
        return await original_db(method, *args, **kwargs)

    async def runner(context, emit):
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    service.db = lose_heartbeat
    service.runner = runner
    await service.authorize("root-a")
    await service.dispatch("root-a", "bootstrap", {})
    await service.dispatch("root-a", "settings.update", {"enabled": True})
    session = await service.dispatch("root-a", "sessions.create", {})
    run = await service.dispatch("root-a", "runs.start", {"session_id": session["id"], "message": "Heartbeat race", "request_id": "heartbeat-fence"})
    await asyncio.wait_for(asyncio.gather(*list(service.tasks.values())), 3)
    assert cancelled.is_set()
    saved = store.run("root-a", run["id"])
    assert saved["status"] == "running" and saved["worker"] == "replacement-worker"


def test_service_factory_uses_project_mysql_and_propagates_connection_failure(monkeypatch):
    from unittest.mock import Mock
    from src.assistant import mysql_store
    from src.assistant.service import create_service

    mysql_connection = Mock(side_effect=RuntimeError("Project MySQL is unavailable"))
    monkeypatch.setattr(mysql_store, "_default_connection", mysql_connection)
    service = create_service(FastAPI())
    assert isinstance(service.store, mysql_store.AssistantStore)
    mysql_connection.assert_not_called()
    with pytest.raises(RuntimeError, match="MySQL is unavailable"):
        service.store.get_settings("root-a", {})
    mysql_connection.assert_called_once()
