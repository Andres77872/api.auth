"""Bounded, session-authenticated tools using the application's ASGI routes.

No tool accepts a URL, SQL, Python or shell command. Read/write capability checks
run for every invocation, including delegated subagents and resumed generations.
"""
from __future__ import annotations

import asyncio
import csv
import inspect
import io
import json
import re
from collections.abc import Awaitable, Callable, Mapping
from typing import Any
from urllib.parse import quote, unquote

import httpx
from fastapi import FastAPI
from fastapi.routing import APIRoute
from starlette.routing import Match

from src.assistant.catalog import SKILLS, ToolSpec, build_catalog

MAX_ARGUMENT_BYTES = 64_000
MAX_RESPONSE_BYTES = 512_000
MAX_OUTPUT_CHARS = 32_000
MAX_ITEMS = 100
_SECRET_KEYS = re.compile(
    r"(?:^|_)(?:passwords?|passwd|secrets?|tokens?|authorization|cookies?|private_key|api_keys?|credentials?)(?:$|_)", re.I
)
_SAFE_SECRET_SUFFIXES = ("_status", "_configured", "_present", "_fingerprint", "_count", "_type", "_set_at", "_key_id", "_expires_at")
_CREDENTIAL_TEXT = re.compile(
    r"\b(?:Bearer\s+[A-Za-z0-9._~+/=-]+|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+|sk_[A-Za-z0-9_.-]{12,}|sk-(?:ant-)?[A-Za-z0-9_-]{12,})",
    re.I,
)
_SECRET_ASSIGNMENT = re.compile(
    r"((?:password|passwd|secret|access_token|refresh_token|api_key|authorization)\s*[=:]\s*)([^\s&,;]+)", re.I
)


def _secret_key(key: str) -> bool:
    normalized = re.sub(r"(?<=[a-z])(?=[A-Z])", "_", key).lower().replace("-", "_")
    return bool(_SECRET_KEYS.search(normalized)) and not normalized.endswith(_SAFE_SECRET_SUFFIXES)


def sensitive_values(value: Any) -> list[str]:
    """Collect submitted secrets so echoed validation messages can be scrubbed."""
    found: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            if _secret_key(str(key)) and isinstance(item, str) and item:
                found.append(item)
            else:
                found.extend(sensitive_values(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(sensitive_values(item))
    return found


def redact(value: Any, secrets: tuple[str, ...] | list[str] = (), *, max_items: int = MAX_ITEMS) -> Any:
    """Recursively redact credentials before results enter model context or logs."""
    def clean(item: Any, depth: int = 0, sensitive_context: bool = False) -> Any:
        if depth > 12:
            return "[nested data omitted]"
        if isinstance(item, Mapping):
            result = {}
            for key, child in list(item.items())[:max_items]:
                # Preserve booleans/numbers such as credentials-present and token
                # usage. Actual credential strings are never sent to the model.
                public_status = str(key).lower().endswith(_SAFE_SECRET_SUFFIXES) or str(key).lower() in {"status", "configured", "present", "fingerprint", "type", "provider", "key_id", "set_at"}
                secret = _secret_key(str(key)) or (sensitive_context and not public_status)
                if secret and child is not None and not isinstance(child, (bool, int, float, dict, list)):
                    result[str(key)] = "[REDACTED]"
                else:
                    result[str(key)] = clean(child, depth + 1, secret)
            if len(item) > max_items:
                result["_truncated_fields"] = len(item) - max_items
            return result
        if isinstance(item, (list, tuple)):
            result = [clean(child, depth + 1, sensitive_context) for child in item[:max_items]]
            if len(item) > max_items:
                result.append({"_truncated_items": len(item) - max_items})
            return result
        if isinstance(item, str):
            if sensitive_context:
                return "[REDACTED]"
            for secret in secrets:
                if secret:
                    item = item.replace(secret, "[REDACTED]")
            # Audit payloads frequently contain serialized JSON within strings.
            if item.lstrip().startswith(("{", "[")):
                try:
                    return clean(json.loads(item), depth + 1)
                except (ValueError, RecursionError):
                    pass
            item = _CREDENTIAL_TEXT.sub("[REDACTED]", item)
            item = _SECRET_ASSIGNMENT.sub(r"\1[REDACTED]", item)
            return item[:4000] + ("… [truncated]" if len(item) > 4000 else "")
        return item if item is None or isinstance(item, (bool, int, float)) else str(item)[:4000]

    return clean(value)


async def _require_live_root(token: str, user_id: str) -> None:
    # Import lazily: catalog discovery must not connect to the database.
    from src.Util.db.db_enhanced import validate_session
    from src.Util.db.db_users import get_user_type

    def validate() -> bool:
        session = validate_session(token)
        return bool(session and session.user_id == user_id and session.user_type == "root" and get_user_type(user_id) == "root")

    if not token or not await asyncio.to_thread(validate):
        raise PermissionError("The root session expired, was revoked, or lost root access. Sign in again.")


class _ResponseTooLarge(Exception):
    pass


async def _maybe_await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


class AssistantToolExecutor:
    def __init__(
        self,
        app: FastAPI,
        session_token: str | Callable[[], str | Awaitable[str]],
        user_id: str,
        policy_loader: Callable[[], Any],
        audit_callback: Callable[[dict], Any] | None = None,
    ) -> None:
        self.app = app
        self.session_token = session_token
        self.user_id = user_id
        self.policy_loader = policy_loader
        self.audit_callback = audit_callback
        self.catalog = build_catalog(app)

    async def _record(self, spec: ToolSpec, result: dict[str, Any]) -> None:
        if self.audit_callback:
            await _maybe_await(self.audit_callback({
                "operation": spec.id, "skill": spec.skill, "mutates": spec.mutates,
                "ok": result.get("ok", False), "status": result.get("status"),
                "error": result.get("error"),
            }))

    async def execute(self, operation: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        spec = self.catalog.get(operation)
        if not spec:
            return {"ok": False, "error": "unknown_tool", "message": "This operation is not registered."}
        result = await self._execute(spec, arguments or {})
        await self._record(spec, result)
        return result

    async def _execute(self, spec: ToolSpec, arguments: dict[str, Any]) -> dict[str, Any]:
        policy = await _maybe_await(self.policy_loader())
        if not isinstance(policy, Mapping) or not policy.get("enabled", False):
            return {"ok": False, "error": "assistant_disabled", "message": "Enable the assistant in its configuration first."}
        enabled_skills = policy.get("enabled_skills", list(SKILLS))
        enabled_tools = policy.get("enabled_tools", [tool.id for tool in self.catalog.values() if not tool.mutates])
        if spec.skill not in enabled_skills or spec.id not in enabled_tools:
            return {"ok": False, "error": "tool_disabled", "message": "This skill or tool is disabled in assistant configuration."}
        if spec.mutates and not policy.get("mutations_enabled", False):
            return {"ok": False, "error": "mutations_disabled", "message": "Application changes are disabled. The root user must explicitly enable changes and this tool in assistant configuration."}
        token = await _maybe_await(self.session_token() if callable(self.session_token) else self.session_token)
        try:
            await _require_live_root(token, self.user_id)
        except PermissionError as exc:
            return {"ok": False, "error": "root_session_required", "message": str(exc)}
        except Exception:
            return {"ok": False, "error": "authentication_unavailable", "message": "Root access could not be verified. No operation was executed."}
        try:
            path, query, body = self._arguments(spec, arguments)
        except (ValueError, TypeError, OverflowError) as exc:
            return {"ok": False, "error": "invalid_arguments", "message": str(exc)}
        secrets = [token, *sensitive_values(arguments)]
        size = 0

        async def bounded_app(scope, receive, send):
            async def bounded_send(message):
                nonlocal size
                if message["type"] == "http.response.body":
                    size += len(message.get("body", b""))
                    if size > MAX_RESPONSE_BYTES:
                        raise _ResponseTooLarge()
                await send(message)
            await self.app(scope, receive, bounded_send)

        transport = httpx.ASGITransport(app=bounded_app, raise_app_exceptions=True)
        request_kwargs: dict[str, Any] = {"params": query}
        if "body" in arguments:
            if spec.content_type == "application/x-www-form-urlencoded":
                request_kwargs["data"] = body
            elif spec.content_type == "multipart/form-data":
                # Current reviewed tools use text form inputs only, never uploads.
                request_kwargs["files"] = [(key, (None, _form_value(value))) for key, value in body.items() if value is not None]
            else:
                request_kwargs["json"] = body
        try:
            async with asyncio.timeout(60):
                async with httpx.AsyncClient(
                    transport=transport, base_url="http://assistant.internal", follow_redirects=False,
                    headers={"Authorization": f"Bearer {token}", "User-Agent": "MagicAuthAssistant/1", "X-Assistant-Operation": spec.id},
                ) as client:
                    response = await client.request(spec.method, path, **request_kwargs)
        except (TimeoutError, _ResponseTooLarge):
            return {"ok": False, "error": "result_unavailable", "message": "The operation timed out or returned too much data. It may have completed; inspect current state before retrying.", "may_have_completed": spec.mutates}
        except Exception:
            return {"ok": False, "error": "application_error", "message": "The application could not return the operation result. Inspect current state before retrying a change.", "may_have_completed": spec.mutates}
        try:
            data = response.json()
        except ValueError:
            if "text/csv" in response.headers.get("content-type", ""):
                data = list(csv.DictReader(io.StringIO(response.text)))[:MAX_ITEMS]
            else:
                # Do not expose HTML/debug tracebacks or credential-bearing raw
                # responses. Reviewed application operations return JSON or CSV.
                data = {"message": "The application returned a non-JSON response.", "content_type": response.headers.get("content-type", "")}
        safe = redact(data, secrets)
        serialized = json.dumps(safe, ensure_ascii=False, default=str)
        if len(serialized) > MAX_OUTPUT_CHARS:
            safe = {"truncated": True, "preview": serialized[:MAX_OUTPUT_CHARS], "message": "Narrow filters or paginate for the remaining data."}
        return {"ok": response.is_success and not (isinstance(data, dict) and data.get("success") is False), "status": response.status_code, "operation": spec.id, "data": safe}

    def _arguments(self, spec: ToolSpec, arguments: dict[str, Any]) -> tuple[str, dict, Any]:
        if not isinstance(arguments, dict):
            raise ValueError("Tool arguments must be an object.")
        if len(json.dumps(arguments, ensure_ascii=False).encode()) > MAX_ARGUMENT_BYTES:
            raise ValueError("Tool arguments exceed the maximum size; split the operation into smaller batches.")
        properties = spec.input_schema["properties"]
        if set(arguments) - set(properties):
            raise ValueError("Use only the path, query and body fields declared in this tool's schema.")
        if set(spec.input_schema.get("required", [])) - set(arguments):
            raise ValueError("Required request fields are missing. Check the tool schema.")
        path_values = arguments.get("path", {})
        query = dict(arguments.get("query", {}))
        for name, values in (("path", path_values), ("query", query)):
            if not isinstance(values, dict):
                raise ValueError(f"{name} must be an object.")
            declared = properties.get(name, {}).get("properties", {})
            if set(values) - set(declared):
                raise ValueError(f"Undeclared {name} parameter. Check the tool schema.")
            required = properties.get(name, {}).get("required", [])
            if set(required) - set(values):
                raise ValueError(f"Required {name} parameter is missing.")
        path = spec.path
        for key, value in path_values.items():
            if not isinstance(value, (str, int)) or isinstance(value, bool):
                raise ValueError("Path parameters must be identifiers.")
            text = str(value)
            if not text or text in {".", ".."} or any(char in text for char in "/\\%?#\r\n"):
                raise ValueError("Path parameters must be a single safe identifier.")
            path = path.replace("{" + key + "}", quote(text, safe=""))
        if "{" in path or "}" in path:
            raise ValueError("A required path parameter is missing.")
        # A public identifier such as "api-keys" can otherwise shadow an
        # earlier static route (/users/api-keys vs /users/{user_hash}) and bypass
        # the separately configured operation's capability gate.
        scope = {"type": "http", "method": spec.method, "path": unquote(path), "root_path": ""}
        for route in self.app.routes:
            match, _ = route.matches(scope)
            if match == Match.FULL:
                if not isinstance(route, APIRoute) or route.path != spec.path:
                    raise ValueError("This identifier resolves to a different application operation.")
                break
        else:
            raise ValueError("The registered application operation is unavailable.")
        for key, field in properties.get("query", {}).get("properties", {}).items():
            if key in {"limit", "page_size", "per_page"}:
                maximum = min(MAX_ITEMS, field.get("maximum", MAX_ITEMS))
                if key not in query:
                    query[key] = min(field.get("default", maximum) or maximum, maximum)
                elif not isinstance(query[key], int) or isinstance(query[key], bool) or not 1 <= query[key] <= maximum:
                    raise ValueError(f"{key} must be between 1 and {maximum}; paginate additional results.")
        query.update(spec.fixed_query)
        body = arguments.get("body")
        if spec.content_type in {"application/x-www-form-urlencoded", "multipart/form-data"}:
            if body is not None and not isinstance(body, dict):
                raise ValueError("Form body must be an object.")
            body = {key: _form_value(value) for key, value in (body or {}).items() if value is not None}
        if spec.path == "/admin/audit/export" and isinstance(body, dict):
            body = {**body, "limit": min(MAX_ITEMS, int(body.get("limit") or MAX_ITEMS))}
        return path, query, body


def _form_value(value: Any) -> Any:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, separators=(",", ":"))
    return str(value)


def build_agent_tools(
    executor: AssistantToolExecutor,
    enabled_skills: list[str] | None = None,
    enabled_tools: list[str] | None = None,
) -> list[Any]:
    """Build LangChain tools; runtime middleware controls progressive disclosure."""
    from langchain_core.tools import StructuredTool

    skills = set(SKILLS if enabled_skills is None else enabled_skills)
    allowed = set(executor.catalog if enabled_tools is None else enabled_tools)
    tools = []
    for spec in executor.catalog.values():
        if spec.skill not in skills or spec.id not in allowed:
            continue

        def make_call(operation_id: str):
            async def call(**arguments):
                return await executor.execute(operation_id, arguments)
            return call

        tools.append(StructuredTool(
            name=spec.name, description=spec.description, args_schema=spec.input_schema,
            coroutine=make_call(spec.id), metadata={"skill": spec.skill, "mutates": spec.mutates, "operation_id": spec.id},
        ))
    return tools
