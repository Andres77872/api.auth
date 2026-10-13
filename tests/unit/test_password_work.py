"""Resource admission invariants independent of HTTP and database state."""

import asyncio
import contextvars
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import fakeredis
import pytest

from src.Util.email.rate_limit import RateLimitExceeded
from src.Util.password_work import PasswordWorkLimiter, PasswordWorkPolicy, PasswordWorkPool, load_password_work_policy


def test_policy_defaults_and_positive_configuration():
    assert load_password_work_policy({}) == PasswordWorkPolicy(60, 20, 60, 1)
    assert load_password_work_policy({"AUTH_PASSWORD_WORK_CONCURRENCY": "2"}).concurrency == 2
    for name in ("GLOBAL_LIMIT", "IP_LIMIT", "WINDOW_SECONDS", "CONCURRENCY"):
        for value in ("0", "-1", "invalid", ""):
            with pytest.raises(ValueError):
                load_password_work_policy({f"AUTH_PASSWORD_WORK_{name}": value})


def test_shared_ip_and_global_limits_expire_without_extending_on_rejection():
    redis = fakeredis.FakeStrictRedis()
    limiter = PasswordWorkLimiter(redis=redis, policy=PasswordWorkPolicy(global_limit=3, ip_limit=2))
    limiter.check_allowed("192.0.2.1")
    limiter.check_allowed("192.0.2.1")
    with pytest.raises(RateLimitExceeded) as limited:
        limiter.check_allowed("192.0.2.1")
    assert limited.value.bucket == "password_work_ip"
    assert 1 <= limited.value.retry_after <= 60
    limiter.check_allowed("192.0.2.2")
    keys_before = set(redis.keys())
    global_key = next(key for key in keys_before if key.endswith(b":global"))
    redis.expire(global_key, 7)
    with pytest.raises(RateLimitExceeded) as limited:
        limiter.check_allowed("192.0.2.3")
    assert limited.value.bucket == "password_work_global"
    assert limited.value.retry_after <= 7
    assert set(redis.keys()) == keys_before
    assert redis.get(global_key) == b"3"
    redis.delete(*keys_before)  # simulate expiration without waiting on a clock
    limiter.check_allowed("192.0.2.1")


def test_two_limiter_instances_admit_only_global_budget_under_concurrency():
    server = fakeredis.FakeServer()
    policy = PasswordWorkPolicy(global_limit=10, ip_limit=100)
    replicas = [PasswordWorkLimiter(redis=fakeredis.FakeStrictRedis(server=server), policy=policy) for _ in range(2)]

    def attempt(index):
        try:
            replicas[index % 2].check_allowed(f"192.0.2.{index + 1}")
            return True
        except RateLimitExceeded:
            return False

    with ThreadPoolExecutor(max_workers=8) as executor:
        assert sum(executor.map(attempt, range(50))) == 10


def test_redis_errors_fail_closed():
    redis = Mock()
    redis.eval.side_effect = ConnectionError("unavailable")
    with pytest.raises(RateLimitExceeded) as limited:
        PasswordWorkLimiter(redis=redis).check_allowed("192.0.2.1")
    assert limited.value.retry_after == 1


@pytest.mark.asyncio
async def test_capacity_cancellation_and_context_propagation():
    pool = PasswordWorkPool(1)
    entered, release = threading.Event(), threading.Event()
    context = contextvars.ContextVar("test-password-context", default=None)
    context.set("request-context")

    def operation():
        assert context.get() == "request-context"
        entered.set()
        assert release.wait(timeout=5)
        return "done"

    task = asyncio.create_task(pool.run(operation))
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        assert pool.active_jobs == 1
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert pool.active_jobs == 1
        with pytest.raises(RateLimitExceeded):
            await pool.run(lambda: pytest.fail("overflow job was submitted"))
    finally:
        release.set()
        await pool.aclose()
    assert pool.active_jobs == 0


@pytest.mark.asyncio
async def test_exceptions_release_capacity_and_shutdown_rejects_new_work():
    pool = PasswordWorkPool(1)

    def failing():
        raise ValueError("worker failed")

    with pytest.raises(ValueError, match="worker failed"):
        await pool.run(failing)
    assert await pool.run(lambda: 42) == 42
    await pool.aclose()
    with pytest.raises(RateLimitExceeded):
        await pool.run(lambda: pytest.fail("closed pool ran a job"))


@pytest.mark.asyncio
async def test_shutdown_waits_for_running_work():
    pool = PasswordWorkPool()
    entered, release = threading.Event(), threading.Event()

    def operation():
        entered.set()
        assert release.wait(timeout=5)

    running = asyncio.create_task(pool.run(operation))
    closing = None
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        closing = asyncio.create_task(pool.aclose())
        await asyncio.sleep(0)
        assert not closing.done()
        with pytest.raises(RateLimitExceeded):
            await pool.run(lambda: None)
    finally:
        release.set()
        await running
        if closing is not None:
            await closing
        else:
            await pool.aclose()
