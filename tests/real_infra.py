"""Shared real infrastructure helpers for tests that exercise Docker services.

E2E in this repository means real infrastructure. These helpers intentionally
fail loudly when MySQL or Redis is unavailable instead of skipping tests or
installing fake responses.
"""

import os
from contextlib import contextmanager
from typing import Callable, Iterable
from unittest.mock import patch

import pymysql
import pytest
import redis


REAL_DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "127.0.0.1"),
    "port": int(os.environ.get("DB_PORT", "3306")),
    "user": os.environ.get("DB_USER", "test_user"),
    "password": os.environ.get("DB_MYSQL_PASSWORD", "test_mysql_password"),
    "database": os.environ.get("DB_NAME", "magic_auth"),
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor,
}

REAL_REDIS_CONFIG = {
    "host": os.environ.get("REDIS_HOST", "127.0.0.1"),
    "port": int(os.environ.get("REDIS_PORT", "6379")),
    "db": int(os.environ.get("REDIS_DB", "0")),
    "password": os.environ.get("DB_REDIS_PASSWORD") or None,
    "decode_responses": True,
}


DB_PATCH_LOCATIONS = [
    "src.Util.db_config.get_connection",
    "src.Util.api_audit_logger.get_connection",
    "src.Util.activity_logger.get_connection",
    "src.Util.db.db_error_logger.get_connection",
    "src.Util.db.db_users.get_connection",
    "src.Util.db.db_projects.get_connection",
    "src.Util.db.db_user_groups.get_connection",
    "src.Util.db.db_project_groups.get_connection",
    "src.Util.db.db_global_roles.get_connection",
    "src.Util.db.db_permission_assignments.get_connection",
    "src.Util.db.db_session_analytics.get_connection",
    "src.Util.db.db_audit_analytics.get_connection",
    "src.Util.db.db_api_keys.get_connection",
    "src.Util.system_metrics.get_connection",
    "src.Util.bulk_operations.get_connection",
]

REDIS_PATCH_LOCATIONS = [
    "src.Util.db_config.redis_client",
    "src.Util.cache_manager.redis_client",
    "src.Util.auth_lifecycle.redis_client",
    "src.Util.db.db_enhanced.client",
    "src.Util.db.db_users.client",
    "src.Util.db.db_session_analytics.redis_client",
    "src.Util.system_metrics.redis_client",
    "src.routes.auth.redis_client",
]


def get_real_connection(*, dict_cursor: bool = True):
    """Return a real MySQL connection using .env.test-backed DB_* settings."""
    cfg = {**REAL_DB_CONFIG}
    if not dict_cursor:
        cfg.pop("cursorclass", None)
    return pymysql.connect(**cfg)


def get_live_redis():
    """Return a real Redis client using .env.test-backed REDIS_* settings."""
    return redis.StrictRedis(**REAL_REDIS_CONFIG)


def require_mysql_available() -> None:
    try:
        conn = get_real_connection()
        conn.close()
    except Exception as exc:  # pragma: no cover - exercised only when infra is down
        pytest.fail(
            "Real MySQL is unavailable for real infrastructure tests. "
            "Run `scripts/run-e2e.sh` to recreate Docker services from .env.test. "
            f"Connection config: {REAL_DB_CONFIG!r}. Error: {exc!r}",
            pytrace=False,
        )


def require_redis_available() -> None:
    try:
        get_live_redis().ping()
    except Exception as exc:  # pragma: no cover - exercised only when infra is down
        pytest.fail(
            "Real Redis is unavailable for real infrastructure tests. "
            "Run `scripts/run-e2e.sh` to recreate Docker services from .env.test. "
            f"Connection config: {REAL_REDIS_CONFIG!r}. Error: {exc!r}",
            pytrace=False,
        )


def require_full_infra_available() -> None:
    require_mysql_available()
    require_redis_available()


def _patches_for(locations: Iterable[str], replacement):
    return [patch(location, replacement) for location in locations]


@contextmanager
def patch_all_infra(
    *,
    db_connection_factory: Callable = None,
    redis_client=None,
    db_patch_locations: Iterable[str] = None,
    redis_patch_locations: Iterable[str] = None,
):
    """Patch imported infrastructure singletons to real Docker services.

    Some modules import get_connection/redis_client into local module scope or
    capture Redis at construction time. This redirects those import-time aliases
    to the same real Docker-backed services without faking responses.
    """
    db_connection_factory = db_connection_factory or (lambda: get_real_connection(dict_cursor=False))
    redis_client = redis_client or get_live_redis()
    db_patch_locations = list(db_patch_locations or DB_PATCH_LOCATIONS)
    redis_patch_locations = list(redis_patch_locations or REDIS_PATCH_LOCATIONS)

    patches = _patches_for(db_patch_locations, db_connection_factory)
    patches += _patches_for(redis_patch_locations, redis_client)
    patches.append(patch("src.Util.cache_manager.cache_manager.redis", redis_client))

    for patcher in patches:
        patcher.start()
    try:
        yield
    finally:
        for patcher in reversed(patches):
            patcher.stop()
