from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.Util.billing import sync as billing_sync
from src.Util.billing.provider import BillingSyncJob, BillingSyncResult
from src.Util.stripe import sync as stripe_sync
from src.workers import billing_sync_worker


@pytest.mark.asyncio
async def test_worker_uses_billing_group_client_for_stripe_sync(monkeypatch):
    captured: dict[str, object] = {}
    fake_client = object()

    monkeypatch.setattr(
        billing_sync_worker,
        "get_stripe_client_for_group",
        lambda **kwargs: captured.setdefault("client_kwargs", kwargs) and fake_client,
    )

    def _source_of_truth_resync(**kwargs):
        captured["sync_client"] = kwargs["client"]
        return BillingSyncResult(provider="stripe", job_id=kwargs["job"].job_id, status="completed")

    monkeypatch.setattr(billing_sync_worker.stripe_source_sync, "source_of_truth_resync", _source_of_truth_resync)

    worker = billing_sync_worker.BillingSyncWorker(
        worker_id="test-worker",
        config=SimpleNamespace(sync_enabled=True, decryption_keys_by_id={"key-1": "secret"}),
        stripe_config=SimpleNamespace(sync_enabled=True, api_version="2026-05-27.dahlia"),
        db=SimpleNamespace(),
    )
    job = billing_sync.ClaimedBillingSyncJob(
        job_id="bsync-1",
        provider="stripe",
        job_type="subscription",
        user_id="usr-1",
        billing_group_id="bg-1",
        subscription_id="bsub-1",
    )

    result = await worker._dispatch_stripe_sync(job=job, row={})

    assert result.status == "completed"
    assert captured["sync_client"] is fake_client
    assert captured["client_kwargs"]["billing_group_id"] == "bg-1"
    assert captured["client_kwargs"]["decryption_keys_by_id"] == {"key-1": "secret"}


def test_source_sync_missing_operational_ref_is_non_retryable():
    result = stripe_sync.source_of_truth_resync(
        job=BillingSyncJob(job_id="bsync-2", provider="stripe", job_type="subscription", billing_group_id="bg-1"),
        client=object(),
        operational_refs={},
        decryption_keys_by_id={},
    )

    assert result.status == "failed"
    assert result.retryable is False
    assert result.reason == "missing_operational_ref"
