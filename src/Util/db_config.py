"""
Centralized Database Configuration

This module provides centralized database connection configuration
to eliminate duplication across database modules.
"""

import os

import pymysql
import redis


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if value is None or not str(value).strip():
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


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
    "password": _require_env("DB_MYSQL_PASSWORD"),
    "database": _require_env("DB_NAME"),
    "charset": "utf8mb4",
    "autocommit": False,
}

# Redis connection configuration
REDIS_CONFIG = {
    "host": _require_env("REDIS_HOST"),
    "port": _get_int_env("REDIS_PORT", 6379),
    "db": _get_int_env("REDIS_DB", 0),
    "password": os.environ.get("DB_REDIS_PASSWORD")
}


def get_connection():
    """Get MySQL database connection"""
    return pymysql.connect(**CONNECTION_CONFIG)


def get_redis_client():
    """Get Redis client connection"""
    return redis.StrictRedis(**REDIS_CONFIG)


# Global Redis client instance
redis_client = get_redis_client()
