"""Stand up a complete, ISOLATED development environment in a local database.

Development must never share a database with production. When it does, one binding ends
up carrying both localhost and production URLs, and every consumer of that binding has to
guess which one it meant -- see ``docs/agnostic_oauth`` F-23 and ``sole_return_origin``.

This script seeds a dev-only tenant into whatever database the dev env file points at:

  * one project (deterministic id and hash, so re-runs converge instead of duplicating);
  * its default project group, membership and the admin/user/readonly user groups, which
    is what makes the provisioning group actually *reach* the project;
  * the Google OAuth connection and a project binding carrying the dev URLs and the dev
    provider-init redeem bridge, delegated to ``oauth_env_import`` so the encryption and
    binding rules stay in exactly one place.

It refuses to touch anything that does not look like a development target: the database
host must be a loopback address and every configured URL must be local. ``--allow-remote-host``
overrides both, and exists for a containerised dev database on a LAN address -- never for
pointing dev at production.

Usage:
  python scripts/dev_env_setup.py --env-file .env.dev [--dry-run | --apply | --check-db]
      [--project-name "MagicWorlds Dev"] [--allow-remote-host]

Config (env, never printed): DB_*, GOOGLE_OAUTH_CLIENT_ID / _CLIENT_SECRET / _SCOPES /
  _REDIRECT_URIS / _RETURN_ORIGINS / _PROVISIONING_MODE, PROVIDER_INIT_REDEEM_URL / _TOKEN,
  OAUTH_SECRET_ENCRYPTION_KEY / _KEY_ID, OAUTH_SECRET_HMAC_KEY.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pymysql
import pymysql.cursors


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.migrations import oauth_env_import as oauth_import  # noqa: E402

# The root user the schema seeds in tables/05_initialize_data.sql; a project needs a real
# owner because projects.created_by and .owner_id are foreign keys into users.
ROOT_USER_ID = "usr-550e8400-e29b-41d4-a716-446655440000"
REQUIRED_TABLES = ("users", "projects", "project_groups", "user_groups", "project_group_members",
                   "user_group_project_groups", "oauth_connections", "project_oauth_bindings")
LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]", "0.0.0.0", "host.docker.internal", "db", "mysql"}
DEFAULT_PROJECT_NAME = "MagicWorlds Dev"
# create_default_groups() builds three; the binding provisions new sign-ins into "user".
PROVISIONING_GROUP = "user"


class DevSetupError(RuntimeError):
    """Neutral setup failure. Never carries secret material."""


def _load_env_file(path: Path) -> None:
    if not path.exists():
        raise DevSetupError(f"Env file not found: {path}")
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
        os.environ[key.strip()] = value


def _connect():
    password = os.getenv("DB_MYSQL_PASSWORD") or os.getenv("DB_PASSWORD")
    if not password:
        raise DevSetupError("Missing DB_MYSQL_PASSWORD or DB_PASSWORD")
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


def _is_local(host: str) -> bool:
    return host.strip().lower() in LOOPBACK_HOSTS


def _non_local_urls() -> list[str]:
    """Every configured URL that would reach outside this machine.

    A dev binding that lists a production origin is the exact defect this script exists to
    prevent, so the URLs are checked, not just the database host.
    """

    offenders: list[str] = []
    for name in ("GOOGLE_OAUTH_REDIRECT_URIS", "GOOGLE_OAUTH_RETURN_ORIGINS", "PROVIDER_INIT_REDEEM_URL"):
        for url in (u.strip() for u in (os.getenv(name) or "").split(",")):
            if url and not _is_local(urlsplit(url).hostname or ""):
                offenders.append(f"{name}={url}")
    return offenders


def _assert_dev_target(*, allow_remote_host: bool) -> dict[str, Any]:
    """Fail closed unless this really is a development target."""

    host = os.getenv("DB_HOST", "localhost")
    app_env = (os.getenv("APP_ENV") or "").strip().lower()
    problems: list[str] = []
    if app_env in {"prod", "production"}:
        problems.append(f"APP_ENV={app_env} is not a development environment")
    if not allow_remote_host and not _is_local(host):
        problems.append(f"DB_HOST={host} is not a loopback address; dev must not share production's database")
    if not allow_remote_host:
        problems.extend(f"non-local URL: {u}" for u in _non_local_urls())
    return {"db_host": host, "db_name": os.getenv("DB_NAME", "magic_auth"), "app_env": app_env or "(unset)",
            "problems": problems}


def _project_identity(project_name: str) -> tuple[str, str]:
    """Deterministic id and hash, so --apply converges rather than duplicating."""

    digest = hashlib.sha256(f"dev-project:{project_name}".encode("utf-8")).hexdigest()
    return f"proj-dev-{digest[:24]}", digest.upper()


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
            cursor.execute("SELECT id FROM users WHERE id = %s LIMIT 1", (ROOT_USER_ID,))
            root = cursor.fetchone()
    finally:
        connection.close()
    missing = set(REQUIRED_TABLES) - found
    if missing:
        raise DevSetupError(
            f"Database not ready: missing tables {sorted(missing)}; run "
            "'python scripts/create_database.py' (fresh) or 'python scripts/schema_sync.py --apply' first"
        )
    if not root:
        raise DevSetupError("Seed root user missing; recreate the database so tables/05_initialize_data.sql runs")


def _seed_tenant(cursor, project_id: str, project_hash: str, project_name: str) -> None:
    """Project plus the group graph that makes a provisioning group reach it.

    Mirrors ``src.Util.db.db_projects.create_default_groups`` -- same deterministic ids, so
    a project created through the API and one created here are indistinguishable.
    """

    cursor.execute(
        """INSERT INTO projects (id, project_hash, project_name, project_description, project_created,
                                 created_by, owner_id, is_active, archived)
           VALUES (%s, %s, %s, %s, NOW(), %s, %s, 1, 0)
           ON DUPLICATE KEY UPDATE is_active = 1, archived = 0""",
        [project_id, project_hash, project_name, f"Development tenant for {project_name}", ROOT_USER_ID, ROOT_USER_ID],
    )

    project_group_id = f"pg-default-{project_id}"
    cursor.execute(
        """INSERT INTO project_groups (id, group_hash, group_name, group_description, created_at, is_active)
           VALUES (%s, %s, %s, %s, NOW(), 1)
           ON DUPLICATE KEY UPDATE is_active = 1, updated_at = NOW()""",
        [project_group_id, f"PG-{hashlib.sha256(project_group_id.encode()).hexdigest()[:32].upper()}",
         f"default_{project_id}", f"Default project group for {project_id}"],
    )
    cursor.execute(
        """INSERT INTO project_group_members (id, project_id, project_group_id, assigned_at, is_active)
           VALUES (%s, %s, %s, NOW(), 1)
           ON DUPLICATE KEY UPDATE is_active = 1, assigned_at = NOW()""",
        [f"pgm-default-{project_id}", project_id, project_group_id],
    )

    for base_name, description in (("admin", "Project administrators"), ("user", "Regular users"),
                                   ("readonly", "Read-only users")):
        group_id = f"ug-default-{base_name}-{project_id}"
        cursor.execute(
            """INSERT INTO user_groups (id, group_hash, group_name, group_description, created_at, is_active)
               VALUES (%s, %s, %s, %s, NOW(), 1)
               ON DUPLICATE KEY UPDATE is_active = 1, updated_at = NOW()""",
            [group_id, f"UG-{hashlib.sha256(group_id.encode()).hexdigest()[:32].upper()}",
             f"{base_name}_{project_id}", description],
        )
        cursor.execute(
            """INSERT INTO user_group_project_groups (id, user_group_id, project_group_id, granted_at, is_active)
               VALUES (%s, %s, %s, NOW(), 1)
               ON DUPLICATE KEY UPDATE is_active = 1, granted_at = NOW()""",
            [f"ugpg-default-{base_name}-{project_id}", group_id, project_group_id],
        )


def _provisioning_group_hash(cursor, project_id: str) -> str:
    cursor.execute("SELECT group_hash FROM user_groups WHERE id = %s LIMIT 1",
                   (f"ug-default-{PROVISIONING_GROUP}-{project_id}",))
    row = cursor.fetchone()
    if not row:
        raise DevSetupError("Default provisioning group was not created")
    return str(row["group_hash"])


def main() -> int:
    parser = argparse.ArgumentParser(description="Set up an isolated development environment")
    parser.add_argument("--env-file", default=".env.dev", help="Dev env file to load (default: .env.dev)")
    parser.add_argument("--project-name", default=DEFAULT_PROJECT_NAME)
    parser.add_argument("--allow-remote-host", action="store_true",
                        help="Permit a non-loopback database host and non-local URLs (containerised dev only)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=True)
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--check-db", action="store_true")
    args = parser.parse_args()

    try:
        _load_env_file(Path(args.env_file))
        target = _assert_dev_target(allow_remote_host=args.allow_remote_host)
        project_id, project_hash = _project_identity(args.project_name)
        oauth_plan = oauth_import._plan(project_hash, "placeholder-until-groups-exist")
        problems = target["problems"] + [p for p in oauth_plan["problems"] if "--default-user-group-hash" not in p]

        summary: dict[str, Any] = {
            "target": {k: target[k] for k in ("db_host", "db_name", "app_env")},
            "project": args.project_name,
            "redirect_uris": oauth_plan["redirect_uris"],
            "return_origins": oauth_plan["return_origins"],
            "legacy_redeem_bridge": oauth_plan["legacy_redeem_bridge"],
            "problems": problems,
        }

        if args.check_db:
            _check_db()
            print("dev-env-setup: mode=check-db ok=true target=" + json.dumps(summary["target"]))
            return 0

        if problems:
            print("dev-env-setup: mode=" + ("apply" if args.apply else "dry-run") + " " + json.dumps(summary), file=sys.stderr)
            print("\nRefusing: the target does not look like an isolated development environment.", file=sys.stderr)
            return 2

        if not args.apply:
            print("dev-env-setup: mode=dry-run " + json.dumps(summary))
            print("\nRe-run with --apply to create the tenant and its OAuth binding.")
            return 0

        _check_db()
        connection = _connect()
        try:
            with connection.cursor() as cursor:
                _seed_tenant(cursor, project_id, project_hash, args.project_name)
                group_hash = _provisioning_group_hash(cursor, project_id)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

        oauth_summary = oauth_import._apply(oauth_import._plan(project_hash, group_hash), project_hash, group_hash)
        print("dev-env-setup: mode=apply " + json.dumps({**summary, "oauth": oauth_summary}))
        print("\nDevelopment tenant ready. Wire the consumer to:")
        print(f"  PROJECT_HASH={project_hash}")
        print(f"  DEFAULT_USER_GROUP_HASH={group_hash}")
        print("\nSet OAUTH_CONFIG_SOURCE=db in the dev env file; URLs now live in the database.")
        return 0
    except (DevSetupError, oauth_import.ImportError_) as exc:
        print(f"dev-env-setup: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
