# Getting started

From an empty database to a first authenticated request: configure the service, create the first
root user, set up a project and its groups, then register and log in a user.

## Who this guide is for

- **Operators and platform administrators** who run the service and bootstrap the first root user,
  projects and groups.
- **Integrators** who need a working account and project before building a client. After this
  guide, continue with [Authentication](authentication-usage-cases.md) and the
  [client integration guide](client-authentication-guide.md).

## Prerequisites

- MySQL and Redis reachable from the API host. Redis holds sessions, refresh families and rate-limit
  counters, so the API cannot authenticate anyone without it.
- Python 3.12 (the version in the project `Dockerfile`) with `pip install -r requirements.txt`.
- `curl` and `jq` for the examples. Examples use `API=http://localhost:8000`.

## Configuration essentials

Copy [.env.example](../../.env.example) to `.env` at the repository root; it documents every
variable, including email, OAuth and billing settings. Importing the `src` package loads `.env`
automatically, and variables already exported in the environment take precedence.

These are read at import time; a missing required value stops the server before it serves a
request:

| Variable | Required | Default | Notes |
| --- | --- | --- | --- |
| `DB_HOST`, `DB_USER`, `DB_MYSQL_PASSWORD`, `DB_NAME` | yes | — | `DB_PASSWORD` is accepted as a fallback for `DB_MYSQL_PASSWORD`. The canonical schema is created as `magic_auth`, so use `DB_NAME=magic_auth`. |
| `DB_PORT` | no | `3306` | |
| `REDIS_HOST` | yes | — | |
| `REDIS_PORT`, `REDIS_DB`, `DB_REDIS_PASSWORD` | no | `6379`, `0`, none | |
| `JWT_SECRET_KEY` | yes | — | HS256 signing key for access and refresh tokens, for example `openssl rand -hex 32`. See the caution below. |
| `API_KEY_PEPPER` | yes | — | HMAC pepper for API-key hashing. Changing it invalidates every issued API key. |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | no | `15` | Access-token lifetime. Refresh lifetimes are fixed; see [Authentication](authentication-usage-cases.md#lifetimes). |
| `ALLOWED_ORIGINS` | no | built-in list | Comma-separated browser origins for CORS, also used to accept email-link origins. See below. |
| `DEBUG_MODE` | no | `false` | `true`, `1` or `yes` adds error details and stack traces to responses. Never enable it in production. |
| `APP_ENV` | no | none | `test`, `testing` or `pytest` marks a test runtime (see the caution below). Use `production`, `staging`, `development` or `local` otherwise. |

> [!CAUTION]
> Outside a test runtime, a missing `JWT_SECRET_KEY` stops the server at import with
> `JWT_SECRET_KEY is required outside explicit test runtime`; there is no random fallback. In a test
> runtime (`APP_ENV=test`, or running under pytest) the server silently uses a fixed, public test
> secret, so never set a test `APP_ENV` in a deployment. Changing the secret invalidates every
> issued token.

`ALLOWED_ORIGINS` must list the exact browser origins of your frontends. When it is unset, CORS,
early-reject responses and email-link origin checks fall back to the single built-in
`DEFAULT_ALLOWED_ORIGINS` list in [src/Util/auth_constants.py](../../src/Util/auth_constants.py):
localhost and LAN development origins plus the hosted UI origin `https://auth-ui.arz.ai`. That list
is not a deployment configuration; set the variable in every deployment.

## Create the schema and run the server

```bash
python scripts/create_database.py    # creates the magic_auth schema, procedures and seed data
uvicorn src.main:app --host 0.0.0.0 --port 8000
```

From another shell, `curl -s http://localhost:8000/system/ping` answers `200` with a JSON body.

`GET /ping` is also public and returns `204 No Content`. All routes are mounted at the root path;
there is no configurable base-path prefix. Email delivery needs `EMAIL_DELIVERY_ENABLED` and the
worker (`python -m src.workers.email_worker`); see the [email suite](email/README.md).

## First-root bootstrap and current seed caveat

There is no API-based bootstrap for the very first root user: `POST /user-types/root` itself
requires a root access token. The repository ships a SQL seed, but its credential cannot be used
with the current login:

- `scripts/create_database.py` and `scripts/recreate_database.py` execute
  `schemas/tables/05_initialize_data.sql`;
- that SQL inserts user `root` (email `root@system.local`) with a legacy SHA-256 hash of the
  plaintext `1248163264`;
- the active password verifier accepts Argon2id hashes only, so that seeded credential cannot log
  in;
- both Python scripts print `admin123` on completion, which matches neither the seed nor any hash
  and also cannot log in.

Treat both values as invalid development artifacts, never as deployment credentials. Pick one of
the two paths below.

> [!WARNING]
> Until the seed is corrected, the rotation below is required before the first root login on a
> database created by the canonical scripts.

### Rotate the seeded root password

Run from the repository root after `scripts/create_database.py`. The password must satisfy the
[password policy](authentication-usage-cases.md#password-policy).

```bash
.venv/bin/python - <<'PY'
from getpass import getpass
from src.Util.db_config import get_connection
from src.Util.password_security import assert_password_policy, hash_password

password = getpass("Root password: ")
assert_password_policy(password, username="root", email="root@system.local")

with get_connection() as connection:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT id FROM users "
            "WHERE username = %s AND user_type = 'root' AND is_active = TRUE "
            "LIMIT 1",
            ("root",),
        )
        row = cursor.fetchone()
        if not row:
            raise SystemExit("Seeded root row was not found")
        cursor.callproc("sp_update_password_hash", [row[0], hash_password(password)])
    connection.commit()

print("Seeded root password rotated to Argon2id")
PY
```

### Create the first root without the seed

If the seed row was deliberately omitted, create the first root through the application helper. It
generates the IDs, hashes the password with Argon2id and calls the six-argument
`sp_create_root_user` procedure:

```bash
.venv/bin/python - <<'PY'
from getpass import getpass
from src.Util.db.db_users import create_root_user
from src.Util.password_security import assert_password_policy

username = input("Root username: ").strip()
email = input("Root email (optional): ").strip() or None
password = getpass("Root password: ")
assert_password_policy(password, username=username, email=email)
user = create_root_user(username=username, password=password, email=email, created_by=None)
print(f"Created {user.user_hash}")
PY
```

Do not call `sp_create_root_user` with a plaintext password: it expects generated IDs and a
password hash. `created_by=None` is acceptable only for this first user; create further root users
with `POST /user-types/root`.

### Log in as root

No project exists yet, so use the project-less platform login:

```bash
API=http://localhost:8000
ROOT_TOKEN=$(curl -s -X POST "$API/auth/platform/login" \
  --data-urlencode "username=root" \
  --data-urlencode "password=$ROOT_PASSWORD" | jq -r '.access_token')
```

The access token lasts `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` (15 minutes by default); run the command
again when later calls return `401`.

## Set up the first project and groups

Users reach projects through groups: user → user group → project group → project. Creating a
project builds a default chain for it, so the minimal setup is to create the project and register
users into its default `user_…` group.

### Create a project

`POST /projects` is root-only and takes form fields `project_name` (required) and
`project_description`:

```bash
PROJECT_HASH=$(curl -s -X POST "$API/projects" \
  -H "Authorization: Bearer $ROOT_TOKEN" \
  --data-urlencode "project_name=My Project" \
  --data-urlencode "project_description=First project" | jq -r '.project.project_hash')
```

The server also creates a project group containing the project and three user groups granted that
project group: `admin_<project_id>`, `user_<project_id>` and `readonly_<project_id>`, where
`<project_id>` is the internal project ID (`proj-…`).

### Find the registration group

Registration needs a `user_group_hash`. Take the default `user_…` group of the project:

```bash
PROJECT_GROUPS=$(curl -s "$API/projects/$PROJECT_HASH/groups" -H "Authorization: Bearer $ROOT_TOKEN")
GROUP_HASH=$(jq -r '.user_groups[] | select(.group_name | startswith("user_")) | .group_hash' <<<"$PROJECT_GROUPS")
```

Anyone who knows a group hash can register into it, so share it only with the audience that should
get the group's projects.

### Create a project admin

Optional. `POST /user-types/admin` (root only) takes internal project IDs, not project hashes. The
project API returns only hashes; the internal ID is the suffix of the default group names:

```bash
PROJECT_ID=$(jq -r '.user_groups[] | select(.group_name | startswith("user_")) | .group_name | ltrimstr("user_")' <<<"$PROJECT_GROUPS")
curl -s -X POST "$API/user-types/admin" \
  -H "Authorization: Bearer $ROOT_TOKEN" \
  --data-urlencode "username=project_admin" \
  --data-urlencode "password=$ADMIN_PASSWORD" \
  --data-urlencode "email=admin@example.com" \
  --data-urlencode "assigned_project_id=$PROJECT_ID"
```

The admin can then log in with `/auth/login` and this `project_hash`, or with
`/auth/platform/login`. See [user types](users/user-types.md) for multi-project admins.

### Use your own groups

Optional. To grant a custom user group access instead of the defaults, create both groups, put the
project in the project group, and grant the project group to the user group:

```bash
UG_HASH=$(curl -s -X POST "$API/admin/user-groups" -H "Authorization: Bearer $ROOT_TOKEN" \
  --data-urlencode "group_name=developers" | jq -r '.user_group.group_hash')
PG_HASH=$(curl -s -X POST "$API/admin/project-groups" -H "Authorization: Bearer $ROOT_TOKEN" \
  --data-urlencode "group_name=developer-projects" | jq -r '.project_group.group_hash')

curl -s -X POST "$API/admin/project-groups/$PG_HASH/projects" \
  -H "Authorization: Bearer $ROOT_TOKEN" --data-urlencode "project_hash=$PROJECT_HASH"
curl -s -X POST "$API/admin/user-groups/$UG_HASH/project-groups" \
  -H "Authorization: Bearer $ROOT_TOKEN" --data-urlencode "project_group_hash=$PG_HASH"
```

Users registered with `user_group_hash=$UG_HASH` then reach the project. The
[groups suite](groups/README.md) covers membership and revocation.

## Register and log in the first user

Register a consumer into the group. Registration is public for anyone holding the group hash; the
response already contains a token pair scoped to the group's first project.

```bash
curl -s -X POST "$API/auth/register" \
  --data-urlencode "username=alice" \
  --data-urlencode "password=$ALICE_PASSWORD" \
  --data-urlencode "user_group_hash=$GROUP_HASH"
```

Log in later with the project to work in. `project_hash` is required for every user type on
`/auth/login`:

```bash
ACCESS_TOKEN=$(curl -s -X POST "$API/auth/login" \
  --data-urlencode "username=alice" \
  --data-urlencode "password=$ALICE_PASSWORD" \
  --data-urlencode "project_hash=$PROJECT_HASH" | jq -r '.access_token')

curl -s "$API/users/profile" -H "Authorization: Bearer $ACCESS_TOKEN"
```

Passwords must pass the server-side policy (minimum 8 characters by default, no common passwords,
no username or email inside, no repeated or sequential runs); a rejection is `400 VAL_3007`. Details
are in [Authentication](authentication-usage-cases.md#password-policy).

## How clients authenticate

- Sign-in returns an **access token** (15 minutes by default) and a **refresh token** (72-hour
  sliding family, or 30 days absolute with `remember_me=true`) in the JSON body, and also sets them
  as the `session_token` and `refresh_token` cookies.
- Protected routes accept the access token as `Authorization: Bearer <token>` (APIs, mobile,
  scripts) or through the `session_token` cookie (same-site browser apps).
- `POST /auth/refresh` exchanges the refresh token for a new pair. Each refresh token works once,
  and the previous access token stops working at the same moment.
- A user API key in `X-API-Key` is not a general credential; `POST /auth/validate-api-key` resolves
  its owner and project for services.

The endpoint contract is in [Authentication](authentication-usage-cases.md); cookie attributes,
storage and refresh handling for real clients are in the
[client integration guide](client-authentication-guide.md).

## Common gotchas

Platform-wide rules (`User-Agent` on every request, 8 MiB POST limit, content types) are listed in
[platform-wide contracts](README.md#platform-wide-contracts).

| Symptom | Cause | Fix |
| --- | --- | --- |
| Server stops at import with `Missing required environment variable: DB_HOST` or `KeyError: 'API_KEY_PEPPER'` | A required variable is unset | Set it in `.env` or the environment |
| Stored-procedure or unknown-database errors on first requests | `DB_NAME` differs from the schema the scripts created | Use `DB_NAME=magic_auth` |
| `422` with body `{"status": "Error", "action": "User-Agent header not found"}` | No `User-Agent` header (curl sends one; some HTTP libraries and proxies do not) | Send a `User-Agent` on every request |
| The seeded or printed root password is rejected | Legacy seed; see the bootstrap caveat | [Rotate the seeded root password](#rotate-the-seeded-root-password) |
| `400 VAL_3002` "Project identifier is required for login" | `/auth/login` without `project_hash` | Send it, or use `/auth/platform/login` for root and admin |
| `403` on a consumer login | No user group of the user reaches that project | Link the groups as shown above |
| `401 AUTH_1001` when logging in with the registration email | That email is stored but not activated | Log in with the username, or add and activate the address with `/users/me/emails` |
| `401` on calls that worked a few minutes earlier | The access token expired or was rotated away by a refresh | Refresh, and always use the newest access token |
| `401 AUTH_1008` on `/auth/switch-project` | The sign-in is older than 300 seconds | Log in again with the target `project_hash` |
| `429 INT_7005` on login | 10 failures per IP and identifier, or 30 per identifier, within 15 minutes | Wait for `Retry-After` |
| Browser does not keep the auth cookies | Cookies are `Secure` and `SameSite=Strict`: plain HTTP (other than localhost) or a cross-site frontend drops them | Serve over HTTPS from the same site, or use bearer tokens |
| Browser reports a CORS error | Frontend origin missing from `ALLOWED_ORIGINS` | Add the exact origin (scheme, host and port) |

## What to read next

| Topic | Document |
| --- | --- |
| Endpoint contract: login, registration, email flows, refresh, switch, logout, API-key validation | [Authentication](authentication-usage-cases.md) |
| Building browser, mobile and server clients | [Client integration guide](client-authentication-guide.md) |
| Error envelope and codes | [Error reference](errors.md) |
| OAuth sign-in | [OAuth suite](oauth/README.md) |
| API keys | [API keys suite](api-keys/README.md) |
| Users, user types and email addresses | [Users suite](users/README.md) |
| Groups and project access | [Groups suite](groups/README.md) |
| Projects | [Projects suite](projects/README.md) |
| How permissions resolve | [Permission resolution](permissions/resolution.md) |
| Transactional email | [Email suite](email/README.md) |
