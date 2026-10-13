"""Create the first root account with an operator-supplied Argon2id password."""

from __future__ import annotations

import getpass
import os
import secrets
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.Util.password_security import assert_password_policy, hash_password


def read_root_password() -> str:
    password = os.getenv("BOOTSTRAP_ROOT_PASSWORD")
    if not password:
        password = getpass.getpass("Password for the new root account: ")
        confirmation = getpass.getpass("Confirm the root password: ")
        if password != confirmation:
            raise ValueError("Root passwords do not match")
    assert_password_policy(password, username="root")
    return password


def bootstrap_root_user(connection, *, password: str) -> bool:
    """Create root only when no active root exists; never replace another account."""
    assert_password_policy(password, username="root")
    password_hash = hash_password(password)
    with connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) AS count FROM users WHERE user_type = 'root' AND is_active = TRUE")
        row = cursor.fetchone()
        count = row["count"] if isinstance(row, dict) else row[0]
        if count:
            return False
        cursor.execute(
            "INSERT INTO users (id, user_hash, username, password_hash, user_type, is_active, created_at) "
            "VALUES (%s, %s, 'root', %s, 'root', TRUE, NOW())",
            (f"usr-{secrets.token_hex(24)}", f"usr-{secrets.token_hex(24)}", password_hash),
        )
    connection.commit()
    return True
