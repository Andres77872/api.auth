"""Root-only WebSocket API; disconnecting never owns/cancels execution."""
from __future__ import annotations

import asyncio
import json
import os
from contextlib import suppress

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from src.assistant.models import AssistantError, Command, Subscribe
from src.assistant.service import create_service
from src.Util.auth_constants import ACCESS_COOKIE_NAME, DEFAULT_ALLOWED_ORIGINS

router = APIRouter(prefix="/admin/assistant", tags=["Admin - Assistant"])
MAX_FRAME_BYTES = 131072
# Subscriptions read at most every STREAM_POLL_SECONDS so bursts of deltas share
# one query. Idle conversations back off to STREAM_IDLE_POLL_SECONDS; events
# written by this process wake them early, so the idle ceiling only delays
# events written by another process.
STREAM_POLL_SECONDS = 0.25
STREAM_IDLE_POLL_SECONDS = 2.0


def origin_allowed(origin: str | None, authorization: str | None) -> bool:
    allowed = {item.strip().rstrip("/") for item in os.getenv("ALLOWED_ORIGINS", DEFAULT_ALLOWED_ORIGINS).split(",") if item.strip()}
    # Browsers always send Origin. Non-browser callers must explicitly send a
    # bearer credential; cookies without Origin are rejected to prevent CSWSH.
    if origin is None:
        return bool(authorization and authorization.startswith("Bearer "))
    return origin.rstrip("/") in allowed and origin != "null"


@router.websocket("/ws")
async def assistant_socket(websocket: WebSocket):
    authorization = websocket.headers.get("authorization")
    if not origin_allowed(websocket.headers.get("origin"), authorization):
        await websocket.close(code=4403, reason="Origin is not allowed")
        return
    token = authorization[7:] if authorization and authorization.startswith("Bearer ") else websocket.cookies.get(ACCESS_COOKIE_NAME, "")
    # Service is lazily initialized so ordinary API startup does not create
    # assistant data files or load model dependencies until the feature is used.
    service = getattr(websocket.app.state, "assistant_service", None)
    if service is None:
        service = create_service(websocket.app)
        websocket.app.state.assistant_service = service
    await websocket.accept()
    try:
        owner = await service.authorize(token)
    except Exception:
        await websocket.close(code=4401, reason="A root session is required")
        return
    await service.start()
    send_lock = asyncio.Lock()
    subscriptions: dict[str, asyncio.Task] = {}

    async def send(payload):
        async with send_lock:
            await websocket.send_json(payload)

    async def stream(session_id: str, cursor: int):
        try:
            last_auth = 0.0
            poll_delay = STREAM_POLL_SECONDS
            with service.watch(session_id) as wake:
                while True:
                    now = asyncio.get_running_loop().time()
                    if now - last_auth >= 20:
                        await service.authorize(token)
                        last_auth = now
                    # Clear before reading so a write during the query is not lost.
                    wake.clear()
                    events = await service.db("events", owner, session_id, cursor)
                    for event in events:
                        await send(event)
                        cursor = event["seq"]
                    if len(events) < 200:
                        poll_delay = STREAM_POLL_SECONDS if events else min(poll_delay * 2, STREAM_IDLE_POLL_SECONDS)
                        await asyncio.sleep(STREAM_POLL_SECONDS)
                        if poll_delay > STREAM_POLL_SECONDS and not wake.is_set():
                            with suppress(TimeoutError):
                                await asyncio.wait_for(wake.wait(), poll_delay - STREAM_POLL_SECONDS)
        except AssistantError as exc:
            if exc.code == "unauthorized":
                await websocket.close(code=4401, reason="Session expired")
            else:
                await send({"type": "subscription.error", "session_id": session_id, "error": {"code": exc.code, "message": exc.message}})
        except (WebSocketDisconnect, RuntimeError):
            pass

    try:
        # Clients ping every 20 seconds. A dead connection can expire without
        # keeping subscriptions and socket tasks around indefinitely.
        while True:
            raw = await asyncio.wait_for(websocket.receive_text(), timeout=90)
            if len(raw.encode()) > MAX_FRAME_BYTES:
                await websocket.close(code=1009, reason="Command is too large")
                break
            request_id = None
            try:
                value = json.loads(raw)
                if isinstance(value, dict) and isinstance(value.get("id"), str):
                    request_id = value["id"][:100]
                command = Command.model_validate(value)
                # Every command rechecks the live session and exact root role.
                current_owner = await service.authorize(token)
                if current_owner != owner:
                    raise AssistantError("unauthorized", "Session identity changed")
                if command.method == "sessions.subscribe":
                    sub = Subscribe.model_validate(command.params)
                    await service.db("session", owner, sub.session_id)
                    if sub.session_id in subscriptions:
                        subscriptions[sub.session_id].cancel()
                        await asyncio.gather(subscriptions.pop(sub.session_id), return_exceptions=True)
                    elif len(subscriptions) >= 8:
                        raise AssistantError("limit_exceeded", "Subscribe to at most eight conversations at once")
                    await send({"id": command.id, "result": {"subscribed": True}})
                    subscriptions[sub.session_id] = asyncio.create_task(stream(sub.session_id, sub.after_seq))
                    continue
                if command.method == "sessions.unsubscribe":
                    sub = Subscribe.model_validate(command.params)
                    task = subscriptions.pop(sub.session_id, None)
                    if task:
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
                    result = {"subscribed": False}
                else:
                    result = await service.dispatch(owner, command.method, command.params)
                await send({"id": command.id, "result": result})
            except AssistantError as exc:
                await send({"id": request_id, "error": {"code": exc.code, "message": exc.message}})
                if exc.code == "unauthorized":
                    await websocket.close(code=4401, reason="Session expired")
                    break
            except (ValidationError, ValueError, TypeError):
                await send({"id": request_id, "error": {"code": "invalid_params", "message": "Invalid assistant command or parameters"}})
            except Exception:
                await send({"id": request_id, "error": {"code": "internal_error", "message": "The assistant command could not be completed"}})
    except (WebSocketDisconnect, asyncio.TimeoutError, RuntimeError):
        with suppress(RuntimeError):
            await websocket.close()
    finally:
        # Only subscriptions belong to this connection. Background runs continue.
        for task in subscriptions.values():
            task.cancel()
        await asyncio.gather(*subscriptions.values(), return_exceptions=True)


async def shutdown_assistant(app):
    service = getattr(app.state, "assistant_service", None)
    if service:
        await service.close()
