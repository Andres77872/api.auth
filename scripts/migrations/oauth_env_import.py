"""Import the environment Google OAuth configuration into the database.

Operator-run, explicit, idempotent and redacted. It is deliberately NOT a start-up side
effect: a stale environment variable must never silently re-create a connection an
administrator deleted.

What it writes (``--apply``):
  * one ``google`` connection (platform-owned) with the client secret ENCRYPTED;
  * one binding for the project you name, carrying today's behaviour verbatim:
    provisioning mode, redirect URIs, return origins and the legacy companion redeem
    bridge (``init_mode='legacy_redeem'``) with its URL and bearer ENCRYPTED.

Because a database binding never trusts a caller-asserted project or group, you must name
the project and -- when auto-create is on -- the default user group. They must be the SAME
project and group the companion backend sends today, otherwise the bridge will (correctly)
reject its redemptions. Verify in staging before production.

After a successful import set ``OAUTH_CONFIG_SOURCE=db``. Rollback is ``OAUTH_CONFIG_SOURCE=env``;
the imported rows are inert while the source is ``env``.

Config (env, never printed):
  GOOGLE_OAUTH_CLIENT_ID / _CLIENT_SECRET / _SCOPES / _REDIRECT_URIS / _RETURN_ORIGINS /
  _PROVISIONING_MODE / _ALLOWED_HOSTED_DOMAINS, PROVIDER_INIT_REDEEM_URL / _TOKEN,
  OAUTH_SECRET_ENCRYPTION_KEY / _KEY_ID, OAUTH_SECRET_HMAC_KEY, DB_*.

Usage:
  python scripts/migrations/oauth_env_import.py --env-file .env --project-hash <hash> \\
      [--default-user-group-hash <hash>] [--dry-run | --apply | --check-db]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sys
from pathlib import Path
from typing import Any

import pymysql
import pymysql.cursors


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REQUIRED_TABLES = ("oauth_provider_catalog", "oauth_connections", "project_oauth_bindings", "project_oauth_allowed_urls")
CONNECTION_KEY = "google"
PROVIDER = "google"


class ImportError_(RuntimeError):
    """Neutral import failure. Never carries secret material."""


def _load_env_file(path: Path) -> None:
    if not path.exists():
        raise ImportError_(f"Env file not found: {path}")
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)


def _connect():
    password = os.getenv("DB_MYSQL_PASSWORD") or os.getenv("DB_PASSWORD")
    if not password:
        raise ImportError_("Missing DB_MYSQL_PASSWORD or DB_PASSWORD for --apply/--check-db")
    return pymysql.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "3306")),
        user=os.getenv("DB_USER", "root"),
        password=password,
        database=os.getenv("DB_NAME", "magic_auth"),
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )


def _csv(name: str) -> list[str]:
    seen: list[str] = []
    for item in (os.getenv(name) or "").split(","):
        value = item.strip()
        if value and value not in seen:
            seen.append(value)
    return seen


def _deterministic_hash(*parts: str) -> str:
    return hashlib.sha256(":".join(parts).encode("utf-8")).hexdigest().upper()


def _plan(project_hash: str, group_hash: str | None) -> dict[str, Any]:
    """Validate the environment and return a redacted plan (no secret values)."""

    client_id = (os.getenv("GOOGLE_OAUTH_CLIENT_ID") or "").strip()
    client_secret = (os.getenv("GOOGLE_OAUTH_CLIENT_SECRET") or "").strip()
    mode = ((os.getenv("GOOGLE_OAUTH_PROVISIONING_MODE") or "disabled").strip().lower())
    problems: list[str] = []
    if not client_id:
        problems.append("GOOGLE_OAUTH_CLIENT_ID is not set")
    if not client_secret:
        problems.append("GOOGLE_OAUTH_CLIENT_SECRET is not set")
    if mode not in {"disabled", "link_only", "auto_create", "both"}:
        problems.append("GOOGLE_OAUTH_PROVISIONING_MODE is invalid")
    if mode in {"auto_create", "both"} and not group_hash:
        problems.append("--default-user-group-hash is required because provisioning mode allows auto-create")
    redirect_uris = _csv("GOOGLE_OAUTH_REDIRECT_URIS")
    return_origins = _csv("GOOGLE_OAUTH_RETURN_ORIGINS")
    if not redirect_uris:
        problems.append("GOOGLE_OAUTH_REDIRECT_URIS is empty")
    if not return_origins:
        problems.append("GOOGLE_OAUTH_RETURN_ORIGINS is empty")
    for name in ("OAUTH_SECRET_ENCRYPTION_KEY", "OAUTH_SECRET_ENCRYPTION_KEY_ID", "OAUTH_SECRET_HMAC_KEY"):
        if not (os.getenv(name) or "").strip():
            problems.append(f"{name} is not set (needed to encrypt the client secret)")
    redeem_url = (os.getenv("PROVIDER_INIT_REDEEM_URL") or "").strip()
    redeem_token = (os.getenv("PROVIDER_INIT_REDEEM_TOKEN") or "").strip()
    if bool(redeem_url) != bool(redeem_token):
        problems.append("PROVIDER_INIT_REDEEM_URL and PROVIDER_INIT_REDEEM_TOKEN must both be set or both be empty")
    return {
        "problems": problems,
        "project": project_hash[:8] + "…",
        "provisioning_mode": mode,
        "redirect_uris": len(redirect_uris),
        "return_origins": len(return_origins),
        "hosted_domains": len(_csv("GOOGLE_OAUTH_ALLOWED_HOSTED_DOMAINS")),
        "legacy_redeem_bridge": bool(redeem_url),
        "_redirect_uris": redirect_uris,
        "_return_origins": return_origins,
    }


def _check_db() -> None:
    connection = _connect()
    try:
        with connection.cursor() as cursor:
            placeholders = ", ".join(["%s"] * len(REQUIRED_TABLES))
            cursor.execute(
                "SELECT table_name AS table_name FROM information_schema.tables "
                f"WHERE table_schema = DATABASE() AND table_name IN ({placeholders})",
                REQUIRED_TABLES,
            )
            found = {row["table_name"] for row in cursor.fetchall()}
            cursor.execute("SELECT status FROM oauth_provider_catalog WHERE provider_type = %s LIMIT 1", (PROVIDER,))
            catalog = cursor.fetchone()
    finally:
        connection.close()
    missing = set(REQUIRED_TABLES) - found
    if missing:
        raise ImportError_(f"Database not ready: missing tables {sorted(missing)}; run scripts/schema_sync.py --apply first")
    if not catalog:
        raise ImportError_("Provider catalog has no 'google' row; run scripts/schema_sync.py --apply first")


def _apply(plan: dict[str, Any], project_hash: str, group_hash: str | None) -> dict[str, Any]:
    from src.Util.oauth.secrets import (
        KIND_CLIENT_SECRET,
        KIND_LEGACY_REDEEM_TOKEN,
        KIND_LEGACY_REDEEM_URL,
        encrypt_secret,
    )

    summary: dict[str, Any] = {"connection": None, "binding": None, "urls_added": 0, "legacy_redeem_bridge": False}
    connection_hash = _deterministic_hash("oauth-connection", PROVIDER, os.getenv("GOOGLE_OAUTH_CLIENT_ID", ""))
    hosted = _csv("GOOGLE_OAUTH_ALLOWED_HOSTED_DOMAINS")

    connection = _connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id FROM projects WHERE project_hash = %s LIMIT 1", (project_hash,))
            project = cursor.fetchone()
            if not project:
                raise ImportError_("Project not found for --project-hash")
            group_id = None
            if group_hash:
                cursor.execute("SELECT id FROM user_groups WHERE group_hash = %s AND is_active = 1 LIMIT 1", (group_hash,))
                group = cursor.fetchone()
                if not group:
                    raise ImportError_("Active user group not found for --default-user-group-hash")
                group_id = group["id"]

            cursor.execute("SELECT id FROM oauth_connections WHERE connection_hash = %s LIMIT 1", (connection_hash,))
            existing = cursor.fetchone()
            if existing:
                connection_id = existing["id"]
            else:
                connection_id = f"oac-{secrets.token_hex(24)}"
                cursor.callproc(
                    "sp_oauth_connection_create",
                    (connection_id, connection_hash, PROVIDER, None, "Google", os.environ["GOOGLE_OAUTH_CLIENT_ID"].strip(),
                     None, None, None, None, None, None,
                     (os.getenv("GOOGLE_OAUTH_SCOPES") or "openid email").strip(),
                     json.dumps({"hosted_domains": hosted}) if hosted else None, None, "google", None),
                )
                cursor.fetchall()
                while cursor.nextset():
                    pass

            secret = encrypt_secret(owner_id=connection_id, kind=KIND_CLIENT_SECRET, value=os.environ["GOOGLE_OAUTH_CLIENT_SECRET"].strip())
            cursor.callproc(
                "sp_oauth_connection_set_credentials",
                (connection_id, secret.ciphertext, secret.digest, secret.fingerprint, None, None, None, secret.key_id, None),
            )
            cursor.fetchall()
            while cursor.nextset():
                pass
            cursor.callproc("sp_oauth_connection_set_status", (connection_id, "active", None))
            cursor.fetchall()
            while cursor.nextset():
                pass
            summary["connection"] = {"hash_prefix": connection_hash[:12], "client_secret_fingerprint": secret.fingerprint}

            has_bridge = bool(plan["legacy_redeem_bridge"])
            binding_id = f"pob-{secrets.token_hex(24)}"
            cursor.callproc(
                "sp_oauth_binding_upsert",
                (binding_id, project["id"], connection_id, CONNECTION_KEY, True, True, True, plan["provisioning_mode"],
                 group_id, "deny", "legacy_redeem" if has_bridge else "api", "bff", None, None, None),
            )
            row = cursor.fetchone()
            while cursor.nextset():
                pass
            binding_id = row["binding_id"] if row else binding_id
            summary["binding"] = {"connection_key": CONNECTION_KEY, "init_mode": "legacy_redeem" if has_bridge else "api"}

            for kind, urls in (("redirect_uri", plan["_redirect_uris"]), ("return_origin", plan["_return_origins"])):
                for url in urls:
                    cursor.callproc(
                        "sp_oauth_binding_url_add",
                        (f"pau-{secrets.token_hex(24)}", binding_id, kind, url, hashlib.sha256(url.encode("utf-8")).digest(), None),
                    )
                    cursor.fetchall()
                    while cursor.nextset():
                        pass
                    summary["urls_added"] += 1

            if has_bridge:
                url = encrypt_secret(owner_id=binding_id, kind=KIND_LEGACY_REDEEM_URL, value=os.environ["PROVIDER_INIT_REDEEM_URL"].strip())
                token = encrypt_secret(owner_id=binding_id, kind=KIND_LEGACY_REDEEM_TOKEN, value=os.environ["PROVIDER_INIT_REDEEM_TOKEN"].strip())
                cursor.callproc("sp_oauth_binding_set_legacy_redeem", (binding_id, url.ciphertext, token.ciphertext, url.key_id, None))
                cursor.fetchall()
                while cursor.nextset():
                    pass
                summary["legacy_redeem_bridge"] = True
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return summary


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import the environment Google OAuth configuration into the database")
    parser.add_argument("--env-file", help="Explicit env file for DB/secrets; never loaded by default")
    parser.add_argument("--project-hash", required=True, help="Project that owns today's Google sign-in")
    parser.add_argument("--default-user-group-hash", help="Provisioning group (required when auto-create is on)")
    parser.add_argument("--apply", action="store_true", help="Write the connection, binding, URLs and legacy bridge")
    parser.add_argument("--dry-run", action="store_true", help="Validate only (default)")
    parser.add_argument("--check-db", action="store_true", help="Validate the OAuth tables and catalog exist")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.env_file:
            _load_env_file(Path(args.env_file))
        plan = _plan(args.project_hash, args.default_user_group_hash)
        public_plan = {key: value for key, value in plan.items() if not key.startswith("_")}
        if plan["problems"]:
            print("oauth-env-import: NOT READY")
            for problem in plan["problems"]:
                print(f"  - {problem}")
            return 2
        if args.check_db or args.apply:
            _check_db()
        if not args.apply:
            print(f"oauth-env-import: mode=dry-run plan={json.dumps(public_plan, sort_keys=True)}")
            return 0
        summary = _apply(plan, args.project_hash, args.default_user_group_hash)
        print(f"oauth-env-import: applied {json.dumps(summary, sort_keys=True)}")
        print("Next: set OAUTH_CONFIG_SOURCE=db (rollback: OAUTH_CONFIG_SOURCE=env).")
        return 0
    except ImportError_ as exc:
        print(f"oauth-env-import: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
