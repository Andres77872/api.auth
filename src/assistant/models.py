"""Validated WebSocket configuration and command contracts."""
from __future__ import annotations

import os
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AssistantError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Features(StrictModel):
    planning: bool = True
    memory: bool = True
    ask_user: bool = True
    subagents: Literal[True] = True


class Settings(StrictModel):
    enabled: bool = False
    mutations_enabled: bool = False
    enabled_skills: list[str] = Field(default_factory=list, max_length=100)
    enabled_tools: list[str] = Field(default_factory=list, max_length=2000)
    features: Features = Field(default_factory=Features)
    default_profile_id: str | None = "ollama-default"


class ProfileInput(StrictModel):
    id: str | None = Field(default=None, max_length=100)
    name: str = Field(min_length=1, max_length=100)
    provider: Literal["ollama", "openai", "anthropic"]
    base_url: str = Field(max_length=1000)
    model: str = Field(min_length=1, max_length=200)
    enabled: bool = True
    api_key: str | None = Field(default=None, max_length=8192)
    temperature: float = Field(default=0, ge=0, le=2)
    max_tokens: int = Field(default=4096, ge=128, le=32768)
    context_window: int = Field(default=32768, ge=4096, le=262144)

    @field_validator("base_url")
    @classmethod
    def endpoint_url(cls, value: str) -> str:
        try:
            url = urlsplit(value)
            port = url.port
        except ValueError:
            raise ValueError("Invalid provider URL") from None
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError("Use an HTTP(S) provider URL without credentials, query or fragment")
        # Root config is trusted, but endpoint access is still deployment-scoped.
        # Custom compatible endpoints are explicitly allowed by the operator.
        hosts = {"localhost", "127.0.0.1", "::1", "api.openai.com", "api.anthropic.com"}
        hosts.update(x.strip().lower() for x in os.getenv("ASSISTANT_PROVIDER_HOSTS", "").split(",") if x.strip())
        if url.hostname.lower() not in hosts:
            raise ValueError("Provider host must be listed in ASSISTANT_PROVIDER_HOSTS")
        if url.scheme == "http" and url.hostname in {"api.openai.com", "api.anthropic.com"}:
            raise ValueError("Cloud providers require HTTPS")
        if port == 0:
            raise ValueError("Invalid provider port")
        return value.rstrip("/")


class Command(StrictModel):
    id: str = Field(min_length=1, max_length=100)
    method: str = Field(min_length=1, max_length=100)
    params: dict[str, Any] = Field(default_factory=dict)


class SessionCreate(StrictModel):
    title: str = Field(default="New conversation", min_length=1, max_length=160)
    profile_id: str | None = Field(default=None, max_length=100)


class SessionRef(StrictModel):
    session_id: str = Field(min_length=1, max_length=100)


class Subscribe(SessionRef):
    after_seq: int = Field(default=0, ge=0)


class RunStart(SessionRef):
    message: str = Field(min_length=1, max_length=32000)
    request_id: str = Field(min_length=1, max_length=100)
    profile_id: str | None = Field(default=None, max_length=100)

    @field_validator("message")
    @classmethod
    def nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Message cannot be blank")
        return value


class RunRef(SessionRef):
    run_id: str = Field(min_length=1, max_length=100)


class RunResume(RunRef):
    request_id: str = Field(min_length=1, max_length=100)
    answer: Any = None
    responses: dict[str, Any] | None = None
    decisions: list[dict[str, Any]] | None = Field(default=None, max_length=100)


class MessagesPage(SessionRef):
    before_id: str | None = Field(default=None, max_length=100)
    limit: int = Field(default=100, ge=1, le=200)
