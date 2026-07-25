from contextlib import asynccontextmanager
from unittest.mock import patch

import httpx
import pytest
from fastapi import FastAPI

from src.routes import internal_email
from src.routes.user_types_auth import require_root_user


async def _root_user_override():
    return object()


@asynccontextmanager
async def _client():
    app = FastAPI()
    app.include_router(internal_email.router)
    app.dependency_overrides[require_root_user] = _root_user_override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_email_message_status_returns_redacted_delivery_state():
    with patch("src.routes.internal_email.db_email.get_email_delivery_log") as mock_log:
        mock_log.return_value = {
            "id": "em_test",
            "user_id": 123,
            "purpose": "delivery_operation",
            "template_code": "email_credit_grant_notification",
            "recipient_hash": "secret-hash",
            "recipient_masked": "i***@example.com",
            "provider": "smtp",
            "provider_message_id": "provider-123",
            "status": "sent",
            "priority": 4,
            "attempt_count": 1,
            "max_attempts": 5,
            "next_attempt_at": None,
            "sent_at": "2026-06-18T01:00:00",
            "terminal_at": None,
            "last_error_code": None,
            "created_at": "2026-06-18T00:59:00",
            "updated_at": "2026-06-18T01:00:00",
        }
        async with _client() as client:
            response = await client.post(
                "/internal/email/message-status",
                json={"email_message_id": "em_test"},
            )

    assert response.status_code == 200
    assert response.json() == {
        "email_message_id": "em_test",
        "purpose": "delivery_operation",
        "template_code": "email_credit_grant_notification",
        "recipient_masked": "i***@example.com",
        "provider": "smtp",
        "provider_message_id": "provider-123",
        "status": "sent",
        "attempt_count": 1,
        "max_attempts": 5,
        "sent_at": "2026-06-18T01:00:00",
        "terminal_at": None,
        "last_error_code": None,
        "created_at": "2026-06-18T00:59:00",
        "updated_at": "2026-06-18T01:00:00",
    }
    assert "recipient_hash" not in response.json()
    assert "user_id" not in response.json()


@pytest.mark.asyncio
async def test_email_message_status_returns_404_for_unknown_message():
    with patch("src.routes.internal_email.db_email.get_email_delivery_log", return_value=None):
        async with _client() as client:
            response = await client.post(
                "/internal/email/message-status",
                json={"email_message_id": "em_missing"},
            )

    assert response.status_code == 404
    assert response.json()["detail"] == "email_message_id not found"
