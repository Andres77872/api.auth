"""RED integration contracts for email outbox and worker behavior.

Trace: `.dev/sdd/changes/email-activation/tasks.md` task 1.7.
"""

from __future__ import annotations

from pathlib import Path

from src.Util.email.security import encrypt_render_payload


ROOT = Path(__file__).resolve().parents[2]
SP_SQL = ROOT / "schemas/stored_procedures/14_email_activation.sql"


class WorkerDbStub:
    def __init__(self) -> None:
        self.attempts = []
        self.finalized = []

    def is_recipient_suppressed(self, recipient_hash):
        return False

    def record_email_delivery_attempt(self, **kwargs):
        self.attempts.append(kwargs)

    def finalize_email_message(self, **kwargs):
        self.finalized.append(kwargs)


def _dynamic_template_row(**overrides):
    row = {
        "template_code": "ops_notice",
        "purpose": "delivery_operation",
        "allowed_variables": ["notice"],
        "required_variables": ["notice"],
        "is_builtin": False,
        "is_enabled": True,
        "revision": 1,
        "version": 1,
        "subject_template": "Notice $notice",
        "html_template": "<p>$notice</p>",
        "text_template": "$notice",
        "is_active": 1,
    }
    row.update(overrides)
    return row


def _message(worker, *, template_code: str = "ops_notice", variables=None, message_id: str = "emsg-template"):
    return {
        "id": message_id,
        "purpose": "delivery_operation",
        "template_code": template_code,
        "recipient_hash": b"3" * 32,
        "recipient_email": "recipient@example.test",
        "recipient_masked": "r***@example.test",
        "render_payload_ciphertext": encrypt_render_payload(
            dict(variables or {}),
            key=worker.config.payload_key,
        ),
        "attempt_count": 0,
        "max_attempts": 8,
    }


def test_add_email_and_enqueue_procedure_uses_single_transaction_boundary():
    sql = SP_SQL.read_text()

    assert "sp_user_email_add_and_enqueue" in sql
    assert "START TRANSACTION" in sql
    assert "user_emails" in sql
    assert "user_email_link_tokens" in sql
    assert "email_messages" in sql
    assert "COMMIT" in sql
    assert "ROLLBACK" in sql


def test_claim_email_messages_uses_mysql8_skip_locked():
    sql = SP_SQL.read_text()

    assert "sp_claim_email_messages" in sql
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "lease_until" in sql
    assert "claimed_by" in sql


def test_worker_processes_two_claim_batches_without_duplicate_provider_send(fake_redis):
    from src.Util.email.fake_provider import FakeEmailProvider
    from src.workers.email_worker import EmailWorker

    provider = FakeEmailProvider()
    worker_a = EmailWorker(worker_id="worker-a", provider=provider, redis=fake_redis)
    worker_b = EmailWorker(worker_id="worker-b", provider=provider, redis=fake_redis)

    worker_a.drain_once(limit=50)
    worker_b.drain_once(limit=50)

    sent_message_ids = [request.message_id for request in provider.sent_messages]
    assert len(sent_message_ids) == len(set(sent_message_ids))


def test_retry_backoff_dead_letters_after_eight_attempts():
    from src.workers.email_worker import compute_next_retry, should_dead_letter

    assert should_dead_letter(attempt_count=7, max_attempts=8) is False
    assert should_dead_letter(attempt_count=8, max_attempts=8) is True

    retry = compute_next_retry(attempt_count=3, base_schedule_seconds=[10, 30, 120, 600], jitter_seed=1)
    assert 0 <= retry.delay_seconds <= 600


def test_suppression_skip_records_sanitized_attempt(fake_redis):
    from src.Util.email.fake_provider import FakeEmailProvider
    from src.workers.email_worker import EmailWorker

    provider = FakeEmailProvider()
    worker = EmailWorker(worker_id="worker-suppressed", provider=provider, redis=fake_redis)

    result = worker.process_message(
        {
            "id": "emsg-suppressed",
            "recipient_hash": b"1" * 32,
            "recipient_email": "suppressed@example.com",
            "template_code": "email_activation",
            "status": "processing",
            "attempt_count": 0,
            "max_attempts": 8,
            "suppressed": True,
        }
    )

    assert result.status == "suppressed"
    assert provider.sent_messages == []
    assert "suppressed@example.com" not in str(result.attempt_metadata)


def test_worker_sends_patreon_link_proof_without_logging_email_or_token(fake_redis, monkeypatch):
    from src.Util.db import db_email_templates
    from src.Util.email.fake_provider import FakeEmailProvider
    from src.workers.email_worker import EmailWorker

    monkeypatch.setattr(db_email_templates, "get_active_template", lambda code: None)

    class DbStub:
        def __init__(self) -> None:
            self.attempts = []
            self.finalized = []

        def is_recipient_suppressed(self, recipient_hash):
            return False

        def record_email_delivery_attempt(self, **kwargs):
            self.attempts.append(kwargs)

        def finalize_email_message(self, **kwargs):
            self.finalized.append(kwargs)

    raw_patreon_email = "patron-different@example.test"
    proof_token = "lookupABC1234.secretDEF5678"
    proof_url = f"https://auth.example.test/auth/patreon/link/confirm?token={proof_token}"
    provider = FakeEmailProvider()
    db = DbStub()
    worker = EmailWorker(worker_id="worker-patreon-proof", provider=provider, redis=fake_redis, db_module=db)
    ciphertext = encrypt_render_payload(
        {
            "purpose": "patreon_link_proof",
            "patreon_link_proof_url": proof_url,
            "proof_token": proof_token,
            "lookup_id": "lookupABC1234",
            "recipient_masked": "p***@example.test",
            "expires_at": "2026-01-01T00:15:00Z",
            "recipient_email": raw_patreon_email,  # must be ignored by the renderer/log metadata
        },
        key=worker.config.payload_key,
    )

    result = worker.process_message(
        {
            "id": "emsg-patreon-proof",
            "purpose": "patreon_link_proof",
            "template_code": "patreon_link_proof",
            "recipient_hash": b"2" * 32,
            "recipient_email": raw_patreon_email,
            "recipient_masked": "p***@example.test",
            "provider_idempotency_key": "patreon-link-proof-lookupABC1234",
            "render_payload_ciphertext": ciphertext,
            "attempt_count": 0,
            "max_attempts": 8,
        }
    )

    assert result.status == "sent"
    assert len(provider.sent_messages) == 1
    outbound = provider.sent_messages[0]
    assert outbound.to == [raw_patreon_email]
    assert proof_token in outbound.text
    assert proof_url in outbound.html
    assert outbound.tags["purpose"] == "patreon_link_proof"

    recorded = f"{result.attempt_metadata} {db.attempts} {db.finalized}"
    assert raw_patreon_email not in recorded
    assert proof_token not in recorded
    assert proof_url not in recorded


def test_worker_uses_latest_active_template_at_render_time(fake_redis, monkeypatch):
    from src.Util.db import db_email_templates
    from src.Util.email.fake_provider import FakeEmailProvider
    from src.workers.email_worker import EmailWorker

    active_row = _dynamic_template_row(
        version=1,
        revision=1,
        subject_template="Old $notice",
        html_template="<p>Old $notice</p>",
        text_template="Old $notice",
    )
    monkeypatch.setattr(db_email_templates, "get_active_template", lambda code: dict(active_row))

    provider = FakeEmailProvider()
    db = WorkerDbStub()
    worker = EmailWorker(worker_id="worker-latest-template", provider=provider, redis=fake_redis, db_module=db)
    message = _message(worker, variables={"notice": "delivery state"})

    active_row.update(
        version=2,
        revision=2,
        subject_template="Latest $notice",
        html_template="<p>Latest $notice</p>",
        text_template="Latest $notice",
    )

    result = worker.process_message(message)

    assert result.status == "sent"
    assert len(provider.sent_messages) == 1
    outbound = provider.sent_messages[0]
    assert outbound.subject == "Latest delivery state"
    assert outbound.headers["X-Template-Version"] == "2"
    assert outbound.headers["X-Template-Revision"] == "2"


def test_worker_cancels_disabled_template_without_provider_send(fake_redis, monkeypatch):
    from src.Util.db import db_email_templates
    from src.Util.email.fake_provider import FakeEmailProvider
    from src.workers.email_worker import EmailWorker

    monkeypatch.setattr(
        db_email_templates,
        "get_active_template",
        lambda code: _dynamic_template_row(
            is_enabled=False,
            revision=7,
            version=3,
            subject_template="",
            html_template="",
            text_template="",
        ),
    )

    provider = FakeEmailProvider()
    db = WorkerDbStub()
    worker = EmailWorker(worker_id="worker-disabled-template", provider=provider, redis=fake_redis, db_module=db)
    result = worker.process_message(_message(worker, variables={"notice": "do not send"}))

    assert result.status == "cancelled"
    assert provider.sent_messages == []
    assert db.attempts[-1]["status"] == "cancelled"
    assert db.attempts[-1]["error_code"] == "EMAIL_TEMPLATE_DISABLED"
    assert db.finalized[-1]["status"] == "cancelled"
    assert db.finalized[-1]["error_code"] == "EMAIL_TEMPLATE_DISABLED"


def test_worker_retries_template_lookup_failure_without_fallback_send(fake_redis, monkeypatch):
    from src.Util.db import db_email_templates
    from src.Util.email.fake_provider import FakeEmailProvider
    from src.workers.email_worker import EmailWorker

    def boom(code):
        raise RuntimeError("template catalog unavailable")

    monkeypatch.setattr(db_email_templates, "get_active_template", boom)

    provider = FakeEmailProvider()
    db = WorkerDbStub()
    worker = EmailWorker(worker_id="worker-template-lookup-failed", provider=provider, redis=fake_redis, db_module=db)
    result = worker.process_message(
        _message(
            worker,
            template_code="delivery_operation",
            variables={"status_summary": "latest state"},
        )
    )

    assert result.status == "retry"
    assert provider.sent_messages == []
    assert db.attempts[-1]["status"] == "temporary_failure"
    assert db.attempts[-1]["error_code"] == "EMAIL_TEMPLATE_LOOKUP_FAILED"
    assert db.finalized[-1]["status"] == "retry"
    assert db.finalized[-1]["error_code"] == "EMAIL_TEMPLATE_LOOKUP_FAILED"


def test_worker_dead_letters_invalid_active_template(fake_redis, monkeypatch):
    from src.Util.db import db_email_templates
    from src.Util.email.fake_provider import FakeEmailProvider
    from src.workers.email_worker import EmailWorker

    monkeypatch.setattr(
        db_email_templates,
        "get_active_template",
        lambda code: {
            "template_code": "delivery_operation",
            "purpose": "delivery_operation",
            "allowed_variables": ["app_name", "support_email", "status_summary"],
            "required_variables": ["status_summary"],
            "is_builtin": True,
            "is_enabled": True,
            "revision": 4,
            "version": 2,
            "subject_template": "Broken template",
            "html_template": "<p>No status summary placeholder</p>",
            "text_template": "No status summary placeholder",
            "is_active": 1,
        },
    )

    provider = FakeEmailProvider()
    db = WorkerDbStub()
    worker = EmailWorker(worker_id="worker-invalid-template", provider=provider, redis=fake_redis, db_module=db)
    result = worker.process_message(
        _message(
            worker,
            template_code="delivery_operation",
            variables={"status_summary": "latest state"},
        )
    )

    assert result.status == "dead"
    assert provider.sent_messages == []
    assert db.attempts[-1]["status"] == "permanent_failure"
    assert db.attempts[-1]["error_code"] == "EMAIL_RENDER_FAILED"
    assert db.finalized[-1]["status"] == "dead"
    assert db.finalized[-1]["error_code"] == "EMAIL_RENDER_FAILED"
