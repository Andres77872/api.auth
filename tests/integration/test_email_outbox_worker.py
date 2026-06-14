"""RED integration contracts for email outbox and worker behavior.

Trace: `.dev/sdd/changes/email-activation/tasks.md` task 1.7.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SP_SQL = ROOT / "schemas/stored_procedures/14_email_activation.sql"


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
