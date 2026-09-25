"""Backend-owned runs, authorization and WebSocket command handling."""
from __future__ import annotations

import asyncio
import base64
import json
import importlib.util
import logging
import os
import time
from contextlib import contextmanager
from functools import partial
from typing import Any, Iterator

from src.assistant.catalog import SKILLS, build_catalog, public_catalog
from src.assistant.models import (
    AssistantError, MessagesPage, ProfileInput, RunRef, RunResume, RunStart, SessionCreate,
    SessionRef, Settings,
)
from src.assistant.store import AssistantStore, uid

logger = logging.getLogger(__name__)
TERMINAL = {"completed", "failed", "cancelled", "interrupted"}


async def validate_root(token: str):
    def validate():
        from src.Util.db import is_root_user, validate_session
        user = validate_session(token)
        if not user or getattr(user, "user_type", None) != "root" or not is_root_user(user.user_id):
            raise AssistantError("unauthorized", "A current root session is required")
        return user
    return await asyncio.to_thread(validate)


class AssistantService:
    def __init__(self, app, store: AssistantStore, *, runner=None, authenticator=validate_root):
        self.app, self.store, self.runner, self.authenticator = app, store, runner, authenticator
        self.worker_id = uid("worker")
        self.tasks: dict[str, asyncio.Task] = {}
        self.tokens: dict[str, str] = {}
        self.token_expiry: dict[str, float] = {}
        self.task_owners: dict[str, str] = {}
        self.monitor_task: asyncio.Task | None = None
        self.event_waiters: dict[str, set[asyncio.Event]] = {}

    async def db(self, method: str, *args, **kwargs):
        return await asyncio.to_thread(partial(getattr(self.store, method), *args, **kwargs))

    async def event(self, session_id: str, kind: str, data: dict) -> dict:
        result = await self.db("event", session_id, kind, data)
        self.notify(session_id)
        return result

    def notify(self, session_id: str):
        """Wake this process's subscribers; other processes rely on polling."""
        for waiter in self.event_waiters.get(session_id, ()):
            waiter.set()

    @contextmanager
    def watch(self, session_id: str) -> Iterator[asyncio.Event]:
        waiter = asyncio.Event()
        self.event_waiters.setdefault(session_id, set()).add(waiter)
        try:
            yield waiter
        finally:
            waiters = self.event_waiters.get(session_id)
            if waiters is not None:
                waiters.discard(waiter)
                if not waiters:
                    del self.event_waiters[session_id]

    def defaults(self) -> dict:
        return Settings(enabled_skills=list(SKILLS), enabled_tools=[t.id for t in build_catalog(self.app).values() if not t.mutates]).model_dump()

    async def settings(self, owner: str) -> dict:
        return await self.db("get_settings", owner, self.defaults())

    async def authorize(self, token: str) -> str:
        user = await self.authenticator(token)
        owner = str(user.user_id)
        # The token was validated above. Expiry is used only to avoid an old
        # browser tab replacing a newer credential after coordinated refresh.
        expiry = 0.0
        try:
            payload = token.split(".")[1]
            expiry = float(json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))["exp"])
        except (IndexError, ValueError, KeyError, TypeError):
            pass
        if expiry >= self.token_expiry.get(owner, 0):
            self.tokens[owner] = token
            self.token_expiry[owner] = expiry
        return owner

    async def start(self):
        if self.monitor_task is None:
            self.monitor_task = asyncio.create_task(self._monitor(), name="assistant-monitor")

    async def close(self):
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        if self.monitor_task:
            self.monitor_task.cancel()
            tasks.append(self.monitor_task)
        await asyncio.gather(*tasks, return_exceptions=True)
        self.tokens.clear()

    async def _monitor(self):
        while True:
            for run_id, session_id in await self.db("recover_stale"):
                await self.event(session_id, "run.status", {"run_id": run_id, "status": "interrupted", "error": "The server stopped during execution. Inspect activity before starting a new conversation; changes are never automatically replayed."})
            await asyncio.sleep(20)

    async def dispatch(self, owner: str, method: str, params: dict) -> Any:
        if method == "bootstrap":
            await self.db("ensure_default_profile", owner)
            return {"settings": await self.settings(owner), "profiles": await self.db("profiles", owner), **public_catalog(self.app), "sessions": await self.db("sessions", owner), "usage": await self.db("usage", owner), "runtime_available": importlib.util.find_spec("deepagents") is not None}
        if method == "settings.get":
            return await self.settings(owner)
        if method == "settings.update":
            # Partial settings updates retain previous values and validate the
            # complete result; unknown capability identifiers fail closed.
            data = Settings.model_validate({**await self.settings(owner), **params}).model_dump()
            if set(data["enabled_skills"]) - set(SKILLS) or set(data["enabled_tools"]) - set(build_catalog(self.app)):
                raise AssistantError("invalid_params", "Unknown skill or tool identifier")
            if data["default_profile_id"]:
                await self.db("profile", owner, data["default_profile_id"])
            result = await self.db("save_settings", owner, data)
            # A kill switch also stops generations already running in this process.
            if not data["enabled"]:
                for run_id, task in list(self.tasks.items()):
                    if self.task_owners.get(run_id) == owner:
                        task.cancel()
            for session in await self.db("sessions", owner):
                await self.event(session["id"], "settings.updated", {"enabled": data["enabled"], "mutations_enabled": data["mutations_enabled"], "enabled_tools": data["enabled_tools"]})
            return result
        if method == "profiles.save":
            data = ProfileInput.model_validate(params).model_dump()
            return await self.db("save_profile", owner, data)
        if method == "profiles.delete":
            profile_id = str(params.get("id", ""))
            settings = await self.settings(owner)
            if profile_id == settings["default_profile_id"]:
                raise AssistantError("conflict", "Choose a different default profile before deleting this one")
            await self.db("delete_profile", owner, profile_id)
            return {"deleted": True}
        if method == "sessions.list":
            return await self.db("sessions", owner, max(1, min(int(params.get("limit", 100)), 100)), float(params["before"]) if params.get("before") else None)
        if method == "sessions.create":
            data = SessionCreate.model_validate(params)
            profile_id = data.profile_id or (await self.settings(owner))["default_profile_id"]
            if not profile_id:
                raise AssistantError("invalid_params", "Select a provider profile first")
            await self.db("profile", owner, profile_id)
            return await self.db("create_session", owner, data.title, profile_id)
        if method == "sessions.get":
            data = SessionRef.model_validate(params)
            return await self.snapshot(owner, data.session_id)
        if method == "messages.list":
            data = MessagesPage.model_validate(params)
            return await self.db("message_page", owner, data.session_id, data.before_id, data.limit)
        if method == "sessions.delete":
            data = SessionRef.model_validate(params)
            await self.db("delete_session", owner, data.session_id)
            return {"deleted": True}
        if method == "runs.start":
            data = RunStart.model_validate(params)
            settings = await self.settings(owner)
            if not settings["enabled"]:
                raise AssistantError("disabled", "Activate the assistant in its settings first")
            session = await self.db("session", owner, data.session_id)
            profile_id = data.profile_id or session["profile_id"] or settings["default_profile_id"]
            profile = await self.db("profile", owner, profile_id)
            if not profile["enabled"]:
                raise AssistantError("disabled", "This provider profile is disabled")
            run, created = await self.db("create_run", owner, data.session_id, data.request_id, {"message": data.message, "profile_id": profile_id, "usage": {}})
            if created:
                await self.event(data.session_id, "message.created", {"role": "user", "content": data.message, "run_id": run["id"]})
                self.launch(owner, run["id"])
            return self.public_run(run)
        if method == "runs.resume":
            data = RunResume.model_validate(params)
            run = await self.db("run", owner, data.run_id)
            if run["session_id"] != data.session_id:
                raise AssistantError("not_found", "Run not found")
            if run["status"] == "interrupted":
                raise AssistantError("conflict", "Inspect the interrupted run's activity and start a new conversation to avoid repeating changes")
            if not (await self.settings(owner))["enabled"]:
                raise AssistantError("disabled", "Activate the assistant before resuming")
            from src.assistant.runtime import normalize_resume
            payload = {"responses": data.responses} if data.responses is not None else ({"decisions": data.decisions} if data.decisions is not None else data.answer)
            resume = normalize_resume(run.get("interrupts", []), payload)
            run, created = await self.db("resume", owner, data.session_id, data.run_id, data.request_id, resume)
            if created:
                # The store records interrupt.resolved in the same transaction.
                self.notify(data.session_id)
                self.launch(owner, run["id"])
            return self.public_run(run)
        if method == "runs.cancel":
            data = RunRef.model_validate(params)
            run = await self.db("run", owner, data.run_id)
            if run["session_id"] != data.session_id:
                raise AssistantError("not_found", "Run not found")
            if run["status"] not in TERMINAL:
                status = "cancelling" if run["status"] == "running" else "cancelled"
                run = await self.db("update_run", owner, data.run_id, status)
                if data.run_id in self.tasks:
                    self.tasks[data.run_id].cancel()
                await self.event(data.session_id, "run.status", {"run_id": run["id"], "status": status})
            return self.public_run(run)
        if method == "usage.get":
            return await self.db("usage", owner)
        if method == "ping":
            return {"time": time.time()}
        raise AssistantError("method_not_found", "Unknown assistant command")

    async def snapshot(self, owner: str, session_id: str) -> dict:
        result = await self.db("snapshot", owner, session_id)
        result["run"] = self.public_run(result["run"])
        return result

    @staticmethod
    def public_run(run):
        if run is None:
            return None
        return {k: v for k, v in run.items() if k not in {"owner", "worker", "resume", "message", "request_id", "heartbeat"}}

    def launch(self, owner: str, run_id: str):
        if run_id not in self.tasks:
            task = asyncio.create_task(self._execute(owner, run_id), name=f"assistant-{run_id}")
            self.tasks[run_id] = task
            self.task_owners[run_id] = owner
            def done(_):
                self.tasks.pop(run_id, None)
                self.task_owners.pop(run_id, None)
            task.add_done_callback(done)

    async def _execute(self, owner: str, run_id: str):
        run = None
        session_id = None
        heartbeat = None
        execution_task = asyncio.current_task()
        previous_usage = {}
        cumulative_usage = {}
        async def emit(kind: str, data: dict):
            # Runtime emits only safe structured content. Do not store model
            # credentials or live auth tokens in event or checkpoint metadata.
            if kind == "usage":
                for key in ("input_tokens", "output_tokens", "total_tokens", "model_calls"):
                    cumulative_usage[key] = previous_usage.get(key, 0) + int(data.get(key, 0))
                data = dict(cumulative_usage)
            await self.event(session_id, kind, {**data, "run_id": run_id})
        async def keep_alive():
            while True:
                await asyncio.sleep(3)
                current = await self.db("run", owner, run_id)
                policy = await self.settings(owner)
                if current["status"] != "running" or current["worker"] != self.worker_id or not policy["enabled"]:
                    if execution_task:
                        execution_task.cancel()
                    return
                # The lease can change after the read above. A conditional
                # heartbeat that updated no row means this task must stop too.
                renewed = await self.db("heartbeat", run_id, worker=self.worker_id)
                if renewed is False:
                    if execution_task:
                        execution_task.cancel()
                    return
        async def finish_owned(status: str, **details) -> bool:
            """Publish failure/cancellation only while this worker owns the run."""
            nonlocal session_id
            try:
                current = await self.db("run", owner, run_id)
                if current["worker"] != self.worker_id or current["status"] not in {"running", "cancelling"}:
                    return False
                session_id = current["session_id"]
                # The MySQL store checks this again under its row lock; a
                # recovery/reassignment between these awaits cannot be undone.
                await self.db("update_run", owner, run_id, status,
                              expected_worker=self.worker_id, usage=cumulative_usage, **details)
            except AssistantError as exc:
                if exc.code in {"ownership_lost", "not_found"}:
                    return False
                raise
            await emit("run.status", {"status": status, **details})
            return True

        async def execution_policy():
            current = await self.db("run", owner, run_id)
            settings = await self.settings(owner)
            if current["status"] != "running" or current["worker"] != self.worker_id:
                return {**settings, "enabled": False, "mutations_enabled": False}
            return settings
        try:
            run = await self.db("run", owner, run_id)
            session_id = run["session_id"]
            previous_usage = dict(run.get("usage") or {})
            cumulative_usage = dict(previous_usage)
            if not await self.db("claim", owner, run_id, self.worker_id):
                return
            await self.authorize(self.tokens.get(owner, ""))
            settings = await self.settings(owner)
            if not settings["enabled"]:
                raise AssistantError("disabled", "The assistant has been disabled")
            profile = await self.db("profile", owner, run["profile_id"], decrypt=True)
            if not profile["enabled"]:
                raise AssistantError("disabled", "The provider profile has been disabled")
            await emit("run.status", {"status": "running"})
            heartbeat = asyncio.create_task(keep_alive())
            from src.assistant.runtime import RuntimeContext, run_agent
            from src.assistant.tools import AssistantToolExecutor
            executor = AssistantToolExecutor(
                self.app, lambda: self.tokens.get(owner, ""), owner,
                execution_policy, audit_callback=lambda record: emit("tool.audit", record),
            )
            context = RuntimeContext(session_id=session_id, run_id=run_id,
                message=run["message"] if "resume" not in run else None,
                profile=profile, settings=settings, checkpoint_path=getattr(self.store, "checkpoint_path", ""),
                checkpoint_backend="mysql",
                executor=executor, resume=run.get("resume"),
                checkpoint_thread_id=f"{session_id}:{run_id}",
                history=await self.db("history", owner, session_id))
            runner = self.runner or run_agent
            async with asyncio.timeout(float(os.getenv("ASSISTANT_RUN_TIMEOUT_SECONDS", "1800"))):
                result = await runner(context, emit)
            current = await self.db("run", owner, run_id)
            if current["status"] != "running" or current["worker"] != self.worker_id:
                return
            if result.content and result.status == "completed":
                message = await self.db("add_message", session_id, run_id, "assistant", result.content)
                await emit("message.completed", message)
            if not cumulative_usage:
                cumulative_usage = result.usage
            await self.db("update_run", owner, run_id, result.status, expected_worker=self.worker_id, interrupts=result.interrupts, usage=cumulative_usage)
            await emit("run.status", {"status": result.status})
        except asyncio.CancelledError:
            await finish_owned("cancelled")
        except Exception as exc:
            if isinstance(exc, AssistantError) and exc.code == "ownership_lost":
                return
            # Provider exceptions often include URLs, headers or request bodies.
            # Persist an actionable category, never the provider's raw exception.
            if isinstance(exc, AssistantError):
                message = exc.message
            elif isinstance(exc, (ImportError, ModuleNotFoundError)):
                message = "Assistant dependencies are missing; install requirements-assistant.txt on the server"
            elif isinstance(exc, TimeoutError):
                message = "The run reached its execution time limit"
            else:
                message = "The assistant could not finish. Check the provider profile, model tool support and server configuration."
            logger.warning("Assistant run %s failed (%s)", run_id, type(exc).__name__)
            await finish_owned("failed", error=message)
        finally:
            if heartbeat:
                heartbeat.cancel()
                await asyncio.gather(heartbeat, return_exceptions=True)


def create_service(app) -> AssistantService:
    return AssistantService(app, AssistantStore())
