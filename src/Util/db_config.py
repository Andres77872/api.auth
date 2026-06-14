"""
Centralized Database Configuration

This module provides centralized database connection configuration
to eliminate duplication across database modules.
"""

import logging
import os
import time
from typing import Optional

import pymysql
import redis
from dbutils.persistent_db import PersistentDB

logger = logging.getLogger(__name__)


def _require_env(*names: str) -> str:
    for name in names:
        value = os.environ.get(name)
        if value is not None and str(value).strip():
            return value
    joined_names = " or ".join(names)
    raise RuntimeError(f"Missing required environment variable: {joined_names}")


def _get_int_env(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None or not str(value).strip():
        return default

    try:
        return int(value)
    except ValueError as exc:
        raise RuntimeError(f"Invalid integer value for environment variable {name}: {value}") from exc


CONNECTION_CONFIG = {
    "host": _require_env("DB_HOST"),
    "port": _get_int_env("DB_PORT", 3306),
    "user": _require_env("DB_USER"),
    "password": _require_env("DB_MYSQL_PASSWORD", "DB_PASSWORD"),
    "database": _require_env("DB_NAME"),
    "charset": "utf8mb4",
    "autocommit": False,
}

# Phase 1.1a: DBUtils PersistentDB pool configuration
DB_POOL_MAXUSAGE = _get_int_env("DB_POOL_MAXUSAGE", 1000)  # connections before recycle
DB_POOL_PING = _get_int_env("DB_POOL_PING", 1)              # 0=no ping, 1=ping on borrow

# Module-level pool, lazily initialized on first get_connection() call
_pool: Optional[PersistentDB] = None

# Redis connection configuration
REDIS_CONFIG = {
    "host": _require_env("REDIS_HOST"),
    "port": _get_int_env("REDIS_PORT", 6379),
    "db": _get_int_env("REDIS_DB", 0),
    "password": os.environ.get("DB_REDIS_PASSWORD")
}


def get_connection():
    """Get MySQL database connection from PersistentDB pool.

    Pool is lazily initialized on first call using DBUtils PersistentDB.
    Interface unchanged — all existing callers work without modification.
    Phase 0 instrumentation preserved for before/after measurement.
    """
    global _pool
    if _pool is None:
        _pool = PersistentDB(
            creator=lambda: pymysql.connect(**CONNECTION_CONFIG),
            maxusage=DB_POOL_MAXUSAGE,
            ping=DB_POOL_PING,
        )
    t0 = time.monotonic()
    try:
        conn = _pool.connection()
        duration_ms = (time.monotonic() - t0) * 1000
        logger.info(f"AUTH_PERF|db_connection|{duration_ms:.3f}")
        return conn
    except Exception:
        duration_ms = (time.monotonic() - t0) * 1000
        logger.info(f"AUTH_PERF|db_connection|{duration_ms:.3f}")
        raise


def get_redis_client():
    """Get Redis client connection"""
    return redis.StrictRedis(**REDIS_CONFIG)


# Global Redis client instance
redis_client = get_redis_client()
