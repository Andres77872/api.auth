"""Atomic budgets across independent clients against disposable Redis."""

from concurrent.futures import ThreadPoolExecutor

import pytest
import redis

from src.Util.email.rate_limit import RateLimitExceeded
from src.Util.password_work import PasswordWorkLimiter, PasswordWorkPolicy
from tests.integration.conftest import _REAL_REDIS_CONFIG


@pytest.mark.real_db
def test_multiple_redis_clients_enforce_one_atomic_global_budget(live_redis):
    clients = [redis.StrictRedis(**_REAL_REDIS_CONFIG) for _ in range(2)]
    policy = PasswordWorkPolicy(global_limit=10, ip_limit=20)
    replicas = [PasswordWorkLimiter(redis=client, policy=policy) for client in clients]

    def attempt(index):
        try:
            replicas[index % 2].check_allowed(f"192.0.2.{index + 1}")
            return True
        except RateLimitExceeded:
            return False

    try:
        with ThreadPoolExecutor(max_workers=8) as executor:
            assert sum(executor.map(attempt, range(100))) == 10
        assert int(live_redis.get("auth:{public-password-work}:global")) == 10
        assert len(list(live_redis.scan_iter("auth:{public-password-work}:ip:*"))) == 10
    finally:
        for client in clients:
            client.close()
