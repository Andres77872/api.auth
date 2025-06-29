"""
Centralized Database Configuration

This module provides centralized database connection configuration
to eliminate duplication across database modules.
"""

import os

import pymysql
import redis

# Database connection settings
DB_HOST = "192.168.1.90"
# DB_HOST = "127.0.0.1"

CONNECTION_CONFIG = {
    "host": DB_HOST,
    "user": "root",
    "password": os.environ.get("DB_MYSQL_PASSWORD"),
    "database": "magic_auth"
}

# Redis connection configuration
REDIS_CONFIG = {
    "host": DB_HOST,
    "port": 6379,
    "db": 0,
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
