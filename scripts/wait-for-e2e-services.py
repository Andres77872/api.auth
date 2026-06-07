import os
import sys
import time

import pymysql
import redis


def _env_int(name: str, default: str) -> int:
    return int(os.environ.get(name, default))


def _redis_password():
    value = os.environ.get("DB_REDIS_PASSWORD")
    return value or None


deadline = time.time() + _env_int("E2E_SERVICE_WAIT_SECONDS", "120")
last_error = None
db_name = os.environ.get("REAL_DB_NAME") or os.environ.get("DB_NAME", "magic_auth")

while time.time() < deadline:
    try:
        conn = pymysql.connect(
            host=os.environ.get("REAL_DB_HOST") or os.environ.get("DB_HOST", "mysql-test"),
            port=_env_int("REAL_DB_PORT", os.environ.get("DB_PORT", "3306")),
            user=os.environ.get("REAL_DB_USER") or os.environ.get("DB_USER", "test_user"),
            password=os.environ.get("REAL_DB_PASSWORD")
            or os.environ.get("DB_MYSQL_PASSWORD", "test_mysql_password"),
            database=db_name,
        )
        with conn.cursor() as cur:
            cur.execute(
                "SHOW PROCEDURE STATUS WHERE Db = %s AND Name = 'sp_create_api_key'",
                (db_name,),
            )
            if cur.fetchone() is None:
                raise RuntimeError("sp_create_api_key is not loaded")
        conn.close()

        redis_client = redis.StrictRedis(
            host=os.environ.get("REAL_REDIS_HOST") or os.environ.get("REDIS_HOST", "redis-test"),
            port=_env_int("REAL_REDIS_PORT", os.environ.get("REDIS_PORT", "6379")),
            db=_env_int("REDIS_DB", "0"),
            password=_redis_password(),
        )
        redis_client.ping()
        sys.exit(0)
    except Exception as exc:
        last_error = exc
        time.sleep(1)

raise SystemExit(f"Timed out waiting for test MySQL/Redis readiness: {last_error!r}")
