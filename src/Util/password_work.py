"""Shared admission and bounded execution for public password operations."""

from __future__ import annotations

import asyncio
import contextvars
import hashlib
import logging
import os
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable, Mapping, TypeVar

from src.Util.email.rate_limit import RateLimitExceeded

logger = logging.getLogger(__name__)
T = TypeVar("T")


@dataclass(frozen=True)
class PasswordWorkPolicy:
    global_limit: int = 60
    ip_limit: int = 20
    window_seconds: int = 60
    concurrency: int = 1

    def __post_init__(self):
        for name, value in vars(self).items():
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"Password work {name} must be a positive integer")


def load_password_work_policy(env: Mapping[str, str] | None = None) -> PasswordWorkPolicy:
    values = os.environ if env is None else env
    defaults = PasswordWorkPolicy()
    options = {}
    for field, suffix in (
        ("global_limit", "GLOBAL_LIMIT"), ("ip_limit", "IP_LIMIT"),
        ("window_seconds", "WINDOW_SECONDS"), ("concurrency", "CONCURRENCY"),
    ):
        name = f"AUTH_PASSWORD_WORK_{suffix}"
        try:
            options[field] = int(values.get(name, str(getattr(defaults, field))))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be a positive integer") from exc
    return PasswordWorkPolicy(**options)


# Both keys share a cluster hash slot. Check every limit before creating keys:
# rejected attempts cannot allocate arbitrary IP buckets or extend the window.
_ADMIT_SCRIPT = """
local retry = 0
local bucket = 0
for i = 1, 2 do
    local count = tonumber(redis.call('GET', KEYS[i]) or '0')
    if count >= tonumber(ARGV[i]) then
        local ttl = redis.call('TTL', KEYS[i])
        if ttl < 0 then
            redis.call('EXPIRE', KEYS[i], ARGV[3])
            ttl = tonumber(ARGV[3])
        end
        if ttl >= retry then
            retry = ttl
            bucket = i
        end
    end
end
if bucket ~= 0 then return {0, math.max(1, retry), bucket} end
for i = 1, 2 do
    redis.call('INCR', KEYS[i])
    if redis.call('TTL', KEYS[i]) < 0 then
        redis.call('EXPIRE', KEYS[i], ARGV[3])
    end
end
return {1, 0, 0}
"""


class PasswordWorkLimiter:
    def __init__(self, *, redis=None, policy: PasswordWorkPolicy | None = None):
        if redis is None:
            from src.Util.db_config import redis_client

            redis = redis_client
        self.redis = redis
        self.policy = policy or load_password_work_policy()

    def check_allowed(self, ip_address: str) -> None:
        digest = hashlib.sha256(ip_address.encode("utf-8")).hexdigest()
        prefix = "auth:{public-password-work}:"
        try:
            allowed, retry_after, bucket = self.redis.eval(
                _ADMIT_SCRIPT, 2, prefix + "global", prefix + "ip:" + digest,
                self.policy.global_limit, self.policy.ip_limit, self.policy.window_seconds,
            )
            allowed, retry_after, bucket = int(allowed), int(retry_after), int(bucket)
        except Exception as exc:
            logger.warning("password_work_rejected bucket=redis_unavailable")
            raise RateLimitExceeded(bucket="password_work_redis", retry_after=1, limit=0) from exc
        if not allowed:
            name = "global" if bucket == 1 else "ip"
            logger.info("password_work_rejected bucket=%s", name)
            raise RateLimitExceeded(
                bucket=f"password_work_{name}", retry_after=retry_after,
                limit=self.policy.global_limit if bucket == 1 else self.policy.ip_limit,
            )


class PasswordWorkPool:
    """No waiting queue; cancellation never releases a still-running job's slot."""

    def __init__(self, concurrency: int = 1):
        if not isinstance(concurrency, int) or isinstance(concurrency, bool) or concurrency <= 0:
            raise ValueError("Password work concurrency must be a positive integer")
        self.concurrency = concurrency
        self._executor = ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="password-work")
        self._lock = threading.RLock()
        self._jobs: set[Future] = set()
        self._closed = False

    @property
    def active_jobs(self) -> int:
        with self._lock:
            return len(self._jobs)

    async def run(self, operation: Callable[[], T]) -> T:
        started = time.monotonic()
        context = contextvars.copy_context()
        with self._lock:
            if self._closed or len(self._jobs) >= self.concurrency:
                logger.info("password_work_rejected bucket=capacity active=%s", len(self._jobs))
                raise RateLimitExceeded(bucket="password_work_capacity", retry_after=1, limit=self.concurrency)
            job = self._executor.submit(context.run, operation)
            self._jobs.add(job)
            job.add_done_callback(lambda completed: self._finished(completed, started))
        wrapped = asyncio.wrap_future(job)
        # Retrieve exceptions even if the HTTP request stops waiting.
        wrapped.add_done_callback(lambda completed: None if completed.cancelled() else completed.exception())
        return await asyncio.shield(wrapped)

    def _finished(self, job: Future, started: float) -> None:
        with self._lock:
            self._jobs.discard(job)
            active = len(self._jobs)
        logger.info("password_work_completed active=%s duration_ms=%.3f", active, (time.monotonic() - started) * 1000)

    async def aclose(self) -> None:
        with self._lock:
            self._closed = True
        await asyncio.to_thread(self._executor.shutdown, wait=True, cancel_futures=False)
