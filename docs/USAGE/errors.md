# Error reference

Every error the API returns, how it is shaped, and what to do about it. The code is the source of
truth: `ErrorCode` and `ErrorCategory` live in `src/Util/error_handler.py`, the FastAPI exception
handlers in `src/middleware/error_handler.py`, and the database-error mapping in
`src/Util/db_error_wrapper.py`.

## Response envelope

### Standard error envelope

Application errors, plain HTTP errors and request-validation failures all use this shape:

```json
{
  "status": "error",
  "error": {
    "code": "AUTH_1001",
    "category": "authentication",
    "message": "Invalid username or password"
  }
}
```

| Field | Type | Description |
| --- | --- | --- |
| `status` | string | Always `"error"`. |
| `error.code` | string | `ErrorCode` value in `CATEGORY_NNNN` form; see the [catalog](#error-code-catalog). |
| `error.category` | string | `ErrorCategory` value: `authentication`, `authorization`, `validation`, `not_found`, `conflict`, `database`, `internal`, `external`, `billing` (`email` is defined but never emitted). |
| `error.message` | string | Human-readable text, sanitized (see [UUID masking](#uuid-masking)). Do not parse it, with one exception: [API-key validation codes](#codes-carried-only-in-the-message). |
| `error.details` | object | Present in production **only** for request-validation failures (`validation_errors`) and for email/login rate limits (`retry_after_seconds`). Everything else in `details` appears only with `DEBUG_MODE`. |

> [!IMPORTANT]
> In production, the `details` your code raises (for example the weak-password `reason_codes` and
> `min_length`) are **not** returned. A weak password answers only
> `{"code": "VAL_3007", "category": "validation", "message": "Weak password (VAL_3007)"}`.

### DEBUG_MODE additions

With `DEBUG_MODE=true` (also `1` or `yes`), `error.details` and `error.trace` are added:

```jsonc
{
  "status": "error",
  "error": {
    "code": "VAL_3007",
    "category": "validation",
    "message": "Weak password (VAL_3007)",
    "details": {
      "context": { "reason_codes": ["too_short"], "min_length": 8 },   // the error's own details
      "function": { "name": "reset_password_with_link", "params": { "payload": "<dict>", "new_password": "[REDACTED]" } }, // route locals
      "error_metadata": { "error_class": "ValidationError", "error_code": "VAL_3007", "category": "validation", "status_code": 400 },
      "api_error": { "endpoint": "/auth/password/reset", "method": "POST", "query_params": {}, "client_host": "203.0.113.10" }
    },
    "trace": "Traceback (most recent call last): ..."
  }
}
```

| `details` key | Present for | Content |
| --- | --- | --- |
| `context` | application errors that carry details | The error's own `details` (sensitive keys redacted). |
| `function` | application errors raised inside a route | Route function name and its local variables. Locals named like a secret (`password`, `secret`, `token`, `key`, `code`, `credential`, and the other sensitive keys) are `[REDACTED]` whatever their type. Of the remaining strings, only UUID identifiers are shown, masked (`usr-[550e]...[0000]`); every other string is `[REDACTED]`. Numbers and booleans are shown; objects show only their type (`<dict>`). |
| `database_error` | MySQL errors | `error_type`, `mysql_error_code`, `mysql_error_message`, plus `constraint_type` or `severity`. |
| `original_error` | other wrapped exceptions | `type`, `message`, `args`. |
| `error_metadata` | application errors | `error_class`, `error_code`, `category`, `status_code`. |
| `error_type`, `error_message` | plain HTTP errors and unhandled exceptions | Exception class and sanitized text (`error_module`, `error_args` for unhandled exceptions). |
| `api_error` | all | `endpoint`, `method`, `query_params`, `client_host`. |

> [!CAUTION]
> Never enable `DEBUG_MODE` outside development. It returns stack traces, file paths, source lines,
> and route local variables. Submitted passwords, tokens, and other secret or free-text values are
> fully redacted rather than shown by prefix, but masked identifiers, numbers, and traces still
> expose internals an attacker can use.

### Other error bodies

Some surfaces do not use the standard envelope:

| Surface | Body | Code available |
| --- | --- | --- |
| Request middleware: missing `User-Agent` (`422`), POST body over 8 MiB (`413`) | `{"status": "Error", "action": "User-Agent header not found"}` / `"Payload too large (max 8 MiB)"` | No |
| OAuth sign-in, link, reauth and unlink (`/auth/oauth/*`) | Standard `error` object plus top-level `"success": false` and `correlation_id` | Yes (`EXT_80xx`) |
| Patreon link denials, Patreon S2S and webhooks, billing S2S and Stripe webhooks | `{"success": false, "message": "..."}` | No |

### Success envelope

There is no single success envelope. Most JSON responses carry `"success": true` and an optional
`message` next to endpoint-specific fields; a few nest the payload under `data` (for example API-key
revoke), and several admin dashboard responses have no `success` flag at all. Public email flows
that must not reveal account state answer `202` with:

```json
{
  "success": true,
  "message": "If the request can be processed, it has been accepted."
}
```

## Status codes

| Status | Meaning here | Typical sources |
| --- | --- | --- |
| `200` | Success | Most routes, including bulk operations with per-item failures. |
| `201` | Created | `POST /roles`, `POST /roles/permission-groups`, `POST /roles/permissions`. |
| `202` | Accepted | Generic email flows (`POST /auth/email/verify`, `/auth/password/forgot`, `/auth/password/reset`, `POST /users/me/emails`, `POST /users/me/emails/{email_id}/resend`, `POST /users/{user_hash}/emails/{email_id}/resend`); some Patreon, billing S2S and webhook routes. |
| `204` | No content | `GET /ping` liveness probe. |
| `400` | Validation | Request-validation failures (`VAL_3001`) and route checks (`VAL_3xxx`). A few non-validation codes also use `400`: `AUTH_1012`, `EXT_8211`, `EXT_8013`, `EXT_8031`, and `INT_7005` on email-template send-test. |
| `401` | Authentication | Missing, invalid, expired or revoked credentials (`AUTH_1xxx`), step-up required (`AUTH_1008`), OAuth verification failures (`EXT_80xx`). |
| `403` | Authorization | Missing user type or permission (`AUTHZ_2xxx`), inactive caller on `/roles/*` (`AUTH_1005`). |
| `404` | Not found | Unknown resource (`NF_4xxx`) or unknown route (`NF_4004`). |
| `405` | Method not allowed | Wrong HTTP method; returned as `INT_7001` with category `internal`. |
| `409` | Conflict | Duplicates (`CONF_5001`–`CONF_5004`), [stored-procedure refusals](#stored-procedure-refusals) (`CONF_5005`), OAuth identity conflicts. |
| `413` | Payload too large | POST body over 8 MiB (middleware body, no code). |
| `422` | Unprocessable | Missing `User-Agent` (middleware body, no code); internal email recipient, `action_url`, template or variable checks (`VAL_3001`); billing S2S request or `Idempotency-Key` checks (`{"success": false}`). Request-validation failures are `400`, not `422`. |
| `429` | Rate limited | `INT_7005`, `EXT_8030`, Patreon and billing surfaces. Honor `Retry-After` when present. |
| `500` | Server error | `INT_7001`, `DB_6xxx`, and `INT_7003` for Redis failures inside database helpers. |
| `501` | Not implemented | `PATCH /projects/{project_hash}/owner`, `PATCH /projects/{project_hash}/archive` (`INT_7006`). |
| `502` | Bad gateway | OAuth code exchange with the provider failed (`EXT_8018`). |
| `503` | Unavailable | OAuth provider not configured (`EXT_8010`), billing provider registry missing (`EXT_8200`), internal template email not configured or template state unavailable (`INT_7003`). |

### Plain HTTP errors

Checks that raise a bare HTTP status (bearer-token validation, unknown routes, most internal email
checks) get `code` and `category` from the status:

| Status | `category` | `code` |
| --- | --- | --- |
| `400` | `validation` | `VAL_3001` (`INVALID_INPUT`) |
| `401` | `authentication` | `AUTH_1003` (`SESSION_INVALID`) |
| `403` | `authorization` | `AUTHZ_2001` (`ACCESS_DENIED`) |
| `404` | `not_found` | `NF_4004` (`RESOURCE_NOT_FOUND`) |
| `409` | `conflict` | `CONF_5004` (`DUPLICATE_ENTRY`) |
| `422` | `validation` | `VAL_3001` (`INVALID_INPUT`) |
| `503` | `internal` | `INT_7003` (`SERVICE_UNAVAILABLE`) |
| any other (`405`, `500`, ...) | `internal` | `INT_7001` (`INTERNAL_ERROR`) |

Headers set on these exceptions (such as `WWW-Authenticate`) are not forwarded to the response.

## Validation errors

When FastAPI cannot parse a request (missing form field, wrong type, out-of-range query value,
malformed JSON body), the API answers `400` with `VAL_3001` and always includes
`error.details.validation_errors`, even in production:

```json
{
  "status": "error",
  "error": {
    "code": "VAL_3001",
    "category": "validation",
    "message": "Request validation failed",
    "details": {
      "validation_errors": [
        {
          "field": "query.limit",
          "message": "Input should be greater than or equal to 1",
          "type": "greater_than_equal"
        }
      ]
    }
  }
}
```

| Field | Content |
| --- | --- |
| `field` | Location and name joined with `.`: `body.user_hashes`, `query.limit`, `path.project_id`. |
| `message` | Pydantic message, for example `Field required`. |
| `type` | Pydantic error type, for example `missing`, `int_parsing`, `greater_than_equal`. |

The OpenAPI document advertises this as a `400` response instead of FastAPI's default `422`. Checks
made inside a route handler also answer `400` but with a specific `VAL_3xxx` code and no `details`
in production. `422` is used only for the cases listed under [Status codes](#status-codes).

## Stored-procedure refusals

Stored procedures reject some requests with `SIGNAL SQLSTATE '45000'` (MySQL error `1644`), for
example "Email row does not exist for user". The database is healthy; the procedure's literal message
is returned as `error.message`:

| Procedure message | Status | Code |
| --- | --- | --- |
| Contains "not found" or "does not exist" | `404` | `NF_4004` (`RESOURCE_NOT_FOUND`) |
| Anything else | `409` | `CONF_5005` (`STATE_CONFLICT`) |

A route may translate a refusal into a more specific error first; revoking an API key that is
already inactive answers `400` / `AUTH_1012`.

Other MySQL errors raised through the database wrapper map as follows: duplicate key (`1062`) →
`409` `CONF_5004`; foreign-key or other integrity violation → `500` `DB_6005`; other operational
errors → `500` `DB_6002`; SQL/programming errors → `500` `DB_6003`; Redis errors → `500` `INT_7003`.

## UUID masking

Error messages and details are sanitized before they leave the service:

| Input | Output |
| --- | --- |
| Prefixed UUID, e.g. `usr-550e8400-e29b-41d4-a716-446655440000` | `usr-[550e]...[0000]` |
| Plain UUID | `[550e]...[0000]` |
| `id=123`, `user_id=123` | `id=[REDACTED]`, `user_id=[REDACTED]` |
| Email address | `[EMAIL_REDACTED]` |
| `http(s)://...` URL | `[LINK_REDACTED]` |
| `token=`, `secret=`, `api_key=`, `idempotency_key=` values; OAuth, Patreon and billing field assignments; raw Stripe IDs | `[REDACTED]` |

Only hyphenated UUIDs are masked; hyphen-less IDs such as `act-0123...` are returned as sent. The
masked form (`usr-[550e]...[0000]`) also appears in some success fields, such as `cleared_by` on
cache endpoints. Take identifiers from success responses, never from error messages.

## Error code catalog

The tables in this section list the codes that reach clients in `error.code`, with the HTTP status
they are returned with. Codes that exist in `ErrorCode` but are never returned are listed once in
[Defined but not returned](#defined-but-not-returned).

### Authentication (`AUTH_1xxx`)

| Code | Name | HTTP | Returned when |
| --- | --- | --- | --- |
| `AUTH_1001` | `INVALID_CREDENTIALS` | 401 | Wrong username/email or password on `POST /auth/login` or `POST /auth/platform/login` (an inactive account gets the same answer); wrong current password on `POST /auth/password/change`. |
| `AUTH_1003` | `SESSION_INVALID` | 401 | Every bare `401`: no token (`Not authenticated`), invalid, expired or revoked access token on any protected route; explicit "Invalid or expired session" checks; failed API-key validation. |
| `AUTH_1005` | `ACCOUNT_INACTIVE` | 403 | `/roles/*` routes when the caller's own account is inactive. Category `authorization`. |
| `AUTH_1008` | `MFA_REQUIRED` | 401 | Step-up gate (not MFA): API-key create, update or revoke (`/users/api-keys*`, `/api-keys*`), `POST /auth/switch-project`, and Patreon link request, confirm or unlink, called more than `OAUTH_RECENT_REAUTH_SECONDS` (default `300`) after the session signed in, with no OAuth reauth of that session. `auth_time` survives `/auth/refresh`, so refreshing does not help. OAuth link and unlink use `EXT_8024` and `EXT_8028` instead. |
| `AUTH_1012` | `API_KEY_REVOKED` | 400 | `PUT` or `DELETE` on `/users/api-keys/{key_id}` or `/api-keys/{key_id}` for a key that is already revoked or inactive. Category `validation`. |
| `AUTH_1013` | `REFRESH_TOKEN_INVALID` | 401 | `POST /auth/refresh`: malformed, unknown or non-current refresh token (also the fallback for unrecognized refresh failures). |
| `AUTH_1014` | `REFRESH_TOKEN_MISSING` | 401 | `POST /auth/refresh` without the `refresh_token` cookie or form field. |
| `AUTH_1015` | `REFRESH_TOKEN_REUSED` | 401 | A consumed refresh token presented after the replay grace window, or an older ancestor token. The whole family is revoked. |
| `AUTH_1016` | `REFRESH_TOKEN_MISMATCH` | 401 | Cookie and form-field refresh tokens differ. |
| `AUTH_1017` | `REFRESH_FAMILY_REVOKED` | 401 | Logout, reuse detection, deactivation or admin action revoked the family. |
| `AUTH_1018` | `TOKEN_TYPE_INVALID` | 401 | An access token was sent to `POST /auth/refresh` as the refresh credential. |
| `AUTH_1019` | `TOKEN_EXPIRED` | 401 | The refresh token itself expired. Terminal: sign in again. |
| `AUTH_1020` | `SESSION_REVOKED` | 401 | During refresh, the user or project context is inactive or cannot be reconstructed. |
| `AUTH_1022` | `REFRESH_TOKEN_REPLAYED` | 401 | The token that was just rotated was presented again inside the grace window (lost response, retry, second tab). The family is **not** revoked; use the newer token. |

### Authorization (`AUTHZ_2xxx`)

| Code | Name | HTTP | Returned when |
| --- | --- | --- | --- |
| `AUTHZ_2001` | `ACCESS_DENIED` | 403 | Caller is not root or `admin` user type on admin-only routes (dashboard, activity, cache clear and invalidation, admin email routes); also every bare `403`, including API-key owners who lost project access. |
| `AUTHZ_2002` | `INSUFFICIENT_PERMISSIONS` | 403 | Caller's session lacks a required permission (for example `admin` or `manage_users`) or is not root where root is required. |
| `AUTHZ_2003` | `PROJECT_ACCESS_DENIED` | 403 | User has no group path to the project (user group → project group → project), or an admin acts outside assigned projects. |
| `AUTHZ_2009` | `OPERATION_NOT_ALLOWED` | 403 | Target is protected regardless of permissions: deleting a system role; a non-root caller changing their own role in a bulk role assignment. |

### Validation (`VAL_3xxx`)

| Code | Name | HTTP | Returned when |
| --- | --- | --- | --- |
| `VAL_3001` | `INVALID_INPUT` | 400 / 422 | Request-validation failure (with `validation_errors`), route-level format checks, every bare `400` or `422`; also profile updates that try to change a password (use `POST /auth/password/change`) and `force_password_reset` on bulk update, which is not supported. |
| `VAL_3002` | `MISSING_REQUIRED_FIELD` | 400 | A field the handler checks itself is empty (for example registration without `user_group_hash`, bulk update without `is_active` or `user_type`). |
| `VAL_3007` | `WEAK_PASSWORD` | 400 | The shared password policy rejected a new password (registration, reset, change, root/admin creation). Reason codes (`too_short`, `common_password`, `obvious_identifier_derivation`, `repeated_or_sequential`) are visible only with `DEBUG_MODE`. |
| `VAL_3009` | `INVALID_RANGE` | 400 | Audit-log `limit` or `days` out of range, or an export larger than the hard limit. |
| `VAL_3010` | `INVALID_LENGTH` | 400 | Bulk list longer than the route limit (`100` users, `50` for bulk delete). |
| `VAL_3012` | `INVALID_ENUM_VALUE` | 400 | Unknown `user_type`, audit export `source` or `format`, or billing provider value. |

### Not found (`NF_4xxx`)

| Code | Name | HTTP | Returned when |
| --- | --- | --- | --- |
| `NF_4001` | `USER_NOT_FOUND` | 404 | User hash unknown; most lookups also treat inactive users as unknown. |
| `NF_4002` | `PROJECT_NOT_FOUND` | 404 | Project hash unknown. |
| `NF_4003` | `GROUP_NOT_FOUND` | 404 | User group unknown or inactive, including registration with an unknown `user_group_hash` and unknown `group_names` in bulk group assignment. |
| `NF_4004` | `RESOURCE_NOT_FOUND` | 404 | Generic lookups, unknown routes, a missing link (permission group not on the role, role not in the project catalog), and procedure refusals saying a row is missing. |
| `NF_4005` | `PERMISSION_NOT_FOUND` | 404 | Permission hash unknown. |
| `NF_4007` | `ROLE_NOT_FOUND` | 404 | Role hash unknown, or an unknown or inactive name in `role_names` (bulk role assignment, `details.role_names` in DEBUG only). |
| `NF_4010` | `API_KEY_NOT_FOUND` | 404 | Key ID unknown or not owned by the caller on API-key management routes. |
| `NF_4011` | `PERMISSION_GROUP_NOT_FOUND` | 404 | Permission group hash unknown or soft-deleted (`/roles/*`, permission assignment routes). |

### Conflict (`CONF_5xxx`)

| Code | Name | HTTP | Returned when |
| --- | --- | --- | --- |
| `CONF_5001` | `USERNAME_EXISTS` | 409 | Registration with a taken username. Check first with `POST /auth/check-availability`. |
| `CONF_5002` | `EMAIL_EXISTS` | 409 | Registration with a taken email. |
| `CONF_5003` | `RESOURCE_EXISTS` | 409 | Adding a role that is already in the project catalog. |
| `CONF_5004` | `DUPLICATE_ENTRY` | 409 | MySQL duplicate key (`1062`) on create or update; every bare `409`. |
| `CONF_5005` | `STATE_CONFLICT` | 409 | Request conflicts with current state, including [stored-procedure refusals](#stored-procedure-refusals). Read `error.message`. |

### Database (`DB_6xxx`)

| Code | Name | HTTP | Returned when |
| --- | --- | --- | --- |
| `DB_6002` | `CONNECTION_ERROR` | 500 | MySQL operational error that is not a procedure refusal: unreachable server, lost connection, but also a missing stored procedure or unknown column. The message starts `Database connection error:`. |
| `DB_6003` | `QUERY_ERROR` | 500 | MySQL programming error: SQL syntax error or missing table. |
| `DB_6005` | `CONSTRAINT_VIOLATION` | 500 | Foreign-key or other integrity violation other than a duplicate key. |

### Internal (`INT_7xxx`)

| Code | Name | HTTP | Returned when |
| --- | --- | --- | --- |
| `INT_7001` | `INTERNAL_ERROR` | 500 | Unhandled exception (inside a decorated route the message is `Error during <operation>`); failed cache clear or invalidation; every bare status without its own mapping (`405`, `500`). |
| `INT_7003` | `SERVICE_UNAVAILABLE` | 500 / 503 | Redis error inside a database helper (`500`); bare `503` from internal email routes. |
| `INT_7005` | `RATE_LIMIT_EXCEEDED` | 429 | Login-identifier, email send/resend/consume, and change-password buckets (`Retry-After` header set; email and login bodies also carry `details.retry_after_seconds`); Patreon admin resync (`Retry-After` header set). Email-template send-test answers it with `400`. |
| `INT_7006` | `FEATURE_NOT_IMPLEMENTED` | 501 | The reserved project owner and archive `PATCH` stubs. |

### External and billing (`EXT_8xxx`)

#### OAuth / external identity (`EXT_80xx`)

These power the provider-agnostic `/auth/oauth/*` routes ,
for every provider (Google, GitHub, Discord, Microsoft, generic OIDC). Category `external`. Public
messages are deliberately neutral and never say which check failed; read `error.code`. The status is
the default for the code; some routes override it (for example `EXT_8011` is `403` on start and
`EXT_8012` is `400` for a malformed init token). Per-endpoint behavior is in the
[OAuth reference](oauth/reference.md).

| Code | Name | HTTP | Meaning |
| --- | --- | --- | --- |
| `EXT_8010` | `OAUTH_PROVIDER_NOT_CONFIGURED` | 503 | Connection or provider prerequisites missing or unhealthy. |
| `EXT_8011` | `OAUTH_PROVIDER_DISABLED` | 404 | OAuth or the connection is disabled. |
| `EXT_8012` | `OAUTH_INIT_INVALID` | 401 | Init token missing, invalid or expired. |
| `EXT_8013` | `OAUTH_REDIRECT_URI_NOT_ALLOWED` | 400 | Return or redirect URI not allow-listed for the binding. |
| `EXT_8014` | `OAUTH_STATE_INVALID` | 401 | Missing, unknown or invalid state. |
| `EXT_8016` | `OAUTH_STATE_REUSED` | 401 | State already consumed (back button, replayed callback). |
| `EXT_8017` | `OAUTH_NONCE_MISMATCH` | 401 | ID-token nonce does not match the flow. |
| `EXT_8018` | `OAUTH_CODE_EXCHANGE_FAILED` | 502 | Authorization-code exchange with the provider failed. |
| `EXT_8019` | `OAUTH_ID_TOKEN_INVALID` | 401 | ID token or userinfo missing, malformed, unsigned or unverifiable. |
| `EXT_8020` | `OAUTH_ISSUER_MISMATCH` | 401 | ID-token issuer not allowed, including a Microsoft tenant outside the connection's allowed tenants. |
| `EXT_8021` | `OAUTH_AUDIENCE_MISMATCH` | 401 | ID-token audience does not match the client. |
| `EXT_8022` | `OAUTH_TOKEN_EXPIRED` | 401 | Provider token expired. |
| `EXT_8023` | `OAUTH_WORKSPACE_DENIED` | 401 | Provider restriction not satisfied, such as Google's hosted-domain (`hd`) allow-list. Microsoft tenants fail with `EXT_8020`. |
| `EXT_8024` | `OAUTH_PROVISIONING_DENIED` | 401 | Provisioning mode or binding forbids the action; also OAuth link without a recent sign-in. |
| `EXT_8025` | `OAUTH_PROJECT_ACCESS_DENIED` | 403 | Resolved identity has no access to the project. |
| `EXT_8027` | `EXTERNAL_IDENTITY_SUB_CONFLICT` | 409 | Linking refused: the provider account is already linked to a different user, or the link could not be stored. |
| `EXT_8028` | `EXTERNAL_IDENTITY_NOT_LINKED` | 404 | Unlink or reauth on an account with no linked identity; `401` when unlink lacks a recent sign-in. |
| `EXT_8029` | `OAUTH_PASSWORD_REQUIRED_FOR_UNLINK` | 409 | Unlinking would remove the only credential; set a password first. |
| `EXT_8030` | `OAUTH_RATE_LIMITED` | 429 | OAuth rate limit; `Retry-After` set. |
| `EXT_8031` | `OAUTH_USER_CANCELLED` | 400 | User cancelled or denied consent at the provider. A normal outcome; the state is consumed. |
| `EXT_8032` | `OAUTH_ACCOUNT_LINK_REQUIRED` | 409 | A local account already has this verified email. Accounts are never merged by email: sign in with the existing method, then link the provider. |

#### Billing (`EXT_82xx`)

Only two billing codes reach `error.code`; the full billing contract is in the
[Stripe billing reference](stripe-billing/reference.md#error-codes).

| Code | Name | HTTP | Returned when |
| --- | --- | --- | --- |
| `EXT_8200` | `STRIPE_PROVIDER_NOT_CONFIGURED` | 503 | Admin billing routes when the `stripe` row is missing from the billing provider registry. Category `billing`. |
| `EXT_8211` | `STRIPE_PORTAL_CONFIGURATION_INVALID` | 400 | Admin Stripe credential save, rotate or test with a portal configuration that is missing or does not meet the restricted-portal contract. Category `validation`. |

`EXT_8204`, `EXT_8205`, `EXT_8209` and `EXT_8210` are raised inside the Stripe adapters, but the
webhook and billing S2S routes replace them with a generic `{"success": false}` body, so clients
never see them.

### Codes carried only in the message

API-key validation (`X-API-Key` on `POST /auth/validate-api-key` and on routes that accept API keys)
raises plain HTTP errors. The envelope's `error.code` is therefore `AUTH_1003` (`401`) or
`AUTHZ_2001` (`403`), and the specific code is the suffix of `error.message`:

| `error.message` | Status | Meaning |
| --- | --- | --- |
| `Malformed API key: AUTH_1010` | 401 | Not in `sk_{public_id}.{secret}` form. |
| `Invalid API key: AUTH_1010` / `API key verification failed: AUTH_1010` | 401 | Secret does not verify. |
| `API key owner is inactive: AUTH_1010` | 401 | Owner deactivated. |
| `API key has expired: AUTH_1011` | 401 | Past `expires_at`. |
| `API key has been revoked: AUTH_1012` | 401 | Revoked. |
| `API key not found: NF_4010` | 401 | Unknown public ID. |
| `API key owner lost project access: AUTHZ_2008` | 403 | Owner no longer reaches the key's project. |

Validation results are cached for `60` seconds, so a revoke or deactivation can take that long to
show here. See the [API keys suite](api-keys/README.md).

### Defined but not returned

These `ErrorCode` members exist but no code path returns them to a client. Do not branch on them.

| Family | Codes |
| --- | --- |
| Authentication | `AUTH_1002` `SESSION_EXPIRED` (the `/auth/validate` and `/auth/logout` handlers raise it, but the route decorator validates the token first and answers `AUTH_1003`), `AUTH_1004` `TOKEN_INVALID`, `AUTH_1006` `ACCOUNT_LOCKED`, `AUTH_1007` `PASSWORD_RESET_REQUIRED`, `AUTH_1009` `MFA_INVALID`, `AUTH_1021` `JWT_CONFIGURATION_FAILURE` |
| Authorization | `AUTHZ_2004` `GROUP_ACCESS_DENIED`, `AUTHZ_2005` `RESOURCE_ACCESS_DENIED`, `AUTHZ_2006` `ROLE_ASSIGNMENT_DENIED`, `AUTHZ_2007` `PERMISSION_DENIED` |
| Validation | `VAL_3003` `INVALID_FORMAT`, `VAL_3004` `INVALID_UUID`, `VAL_3005` `INVALID_EMAIL`, `VAL_3006` `INVALID_USERNAME`, `VAL_3008` `INVALID_DATE`, `VAL_3011` `INVALID_TYPE` |
| Not found | `NF_4006` `SESSION_NOT_FOUND`, `NF_4008` `ENDPOINT_NOT_FOUND` (unknown routes return `NF_4004`), `NF_4009` `USER_TYPE_NOT_FOUND` |
| Conflict | `CONF_5006` `VERSION_CONFLICT` |
| Database | `DB_6001` `DATABASE_ERROR`, `DB_6004` `TRANSACTION_ERROR`, `DB_6006` `DEADLOCK` |
| Internal | `INT_7002` `CONFIGURATION_ERROR`, `INT_7004` `TIMEOUT` |
| External, generic | `EXT_8001` `EXTERNAL_SERVICE_ERROR`, `EXT_8002` `EXTERNAL_API_ERROR`, `EXT_8003` `EXTERNAL_TIMEOUT` |
| OAuth | `EXT_8015` `OAUTH_STATE_EXPIRED` (expired state reports `EXT_8014`), `EXT_8026` `EXTERNAL_IDENTITY_ALREADY_LINKED` |
| Patreon | All of `EXT_8100`–`EXT_8116` (`PATREON_PROVIDER_NOT_CONFIGURED` through `PATREON_RATE_LIMITED`). Patreon surfaces answer `{"success": false, "message": "..."}` without a code; see the [Patreon suite](patreon-link/README.md). |
| Billing | `EXT_8201`–`EXT_8203`, `EXT_8206`–`EXT_8208`, `EXT_8212`–`EXT_8215` |
| Email | All of `EMAIL_9001`–`EMAIL_9010` (`EMAIL_DELIVERY_DISABLED` through `EMAIL_TEMPLATE_INVALID`). Public email flows answer a generic `202`; see the [email suite](email/README.md). |

## Troubleshooting by symptom

### Sign-in and sessions

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `401` `AUTH_1001` on `POST /auth/login` | Wrong identifier or password, or the account is inactive; login does not say which. | Recheck credentials; an admin can look for the user with `GET /users/list?include_inactive=true`. |
| `401` `AUTH_1003` `Not authenticated` | Neither `Authorization: Bearer` nor the `access_token` cookie was sent. | Send the access token. |
| `401` `AUTH_1003` on a protected route, including `GET /auth/validate` | Access token expired, or its Redis session was removed (logout, deactivation, cache clear, per-user cache invalidation). | Call `POST /auth/refresh`; if that fails, sign in again. |
| `401` `AUTH_1008` | Sensitive operation more than `OAUTH_RECENT_REAUTH_SECONDS` (default `300`) after sign-in. | Sign in again, or complete `POST /auth/oauth/{connection}/reauth/start` for this session, then retry. |
| `403` `AUTH_1005` on `/roles/*` | The caller's account is inactive. | Reactivate the account. |
| `409` `CONF_5001` or `CONF_5002` on `POST /auth/register` | Username or email taken. | Call `POST /auth/check-availability` first. |
| `404` `NF_4003` on `POST /auth/register` | `user_group_hash` unknown or inactive. | Use an active user group that is linked to a project through a project group. |

### Refresh failures

All refresh failures are `401` on `POST /auth/refresh`. Send the refresh token as the
`refresh_token` cookie or form field; `Authorization` headers are ignored, so an access token cannot
refresh itself.

```bash
curl -X POST "$BASE_URL/auth/refresh" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "refresh_token=$REFRESH_TOKEN"
```

| Code | Fix |
| --- | --- |
| `AUTH_1014` | Send the refresh token. |
| `AUTH_1016` | Send one source only, or make the cookie and field match. |
| `AUTH_1018` | You sent an access token; send the refresh token. |
| `AUTH_1022` | Another request already rotated this token. Use the token from the response that succeeded; if the client never received it, sign in again. |
| `AUTH_1015` | Reuse detected and the family is revoked. Clear stored tokens and sign in. Serialize refresh calls so parallel `401` handlers do not reuse one token. |
| `AUTH_1013`, `AUTH_1017`, `AUTH_1019`, `AUTH_1020` | Terminal. Clear stored tokens and sign in; do not retry in a loop. |

### Access denied

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `403` `AUTHZ_2001` on `/admin/dashboard/*`, `/admin/activity*`, `/system/cache/*` writes | Caller's user type is not root or `admin`. | Use a root or admin account. |
| `403` `AUTHZ_2002` | Session permissions lack the required permission, or root is required. | Grant the permission (it is picked up on the next session) or use root. |
| `403` `AUTHZ_2003` | No group path from the user to the project. | Walk the chain below. |

The access chain is user → user group → project group → project:

```bash
# 1. The user's groups
curl "$BASE_URL/admin/user-groups/users/$USER_HASH/groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# 2. Project groups the user group can reach
curl "$BASE_URL/admin/user-groups/$GROUP_HASH/project-groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# 3. Projects in a project group (see assigned_projects)
curl "$BASE_URL/admin/project-groups/$PROJECT_GROUP_HASH" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

Permission resolution beyond group membership is covered in
[Permission resolution](permissions/resolution.md).

### Request rejected before the handler

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `422` with `{"status": "Error", "action": "User-Agent header not found"}` | No `User-Agent` header. | Send one; `curl` does by default. |
| `413` with `"Payload too large (max 8 MiB)"` | POST `Content-Length` over 8 MiB. | Send a smaller body. |
| `400` `VAL_3001` with `validation_errors` | Missing or mistyped field. Most write routes take form fields; list fields repeat the key (`user_hashes=a&user_hashes=b`). | Fix the fields named in `validation_errors[].field`. |
| `405` `INT_7001` `Method Not Allowed` | Wrong HTTP method for the path. | Check the method in the suite reference. |

### Email flows

A `202` means the request was accepted, not that an account, address or token exists. Do not show
users anything more specific. As an operator:

1. Check the email components of `GET /system/health` (`email_provider`, `email_outbox`, `email_worker`).
2. Inspect `GET /admin/email/logs` (root or admin), which shows only masked addresses and hashes.
3. On `429`, wait for `Retry-After`.
4. Never log or paste activation or reset links, or any token secret.

### OAuth sign-in

| `error.code` | Likely cause | Fix |
| --- | --- | --- |
| `EXT_8010`, `EXT_8011` | Provider or connection not configured or disabled. | Operator: `GET /admin/oauth/projects/{project_hash}/readiness` names the failing layer. |
| `EXT_8012`, `EXT_8014`, `EXT_8016` | Stale or replayed flow. | Restart sign-in from the beginning; state is single-use. |
| `EXT_8019`, `EXT_8020`, `EXT_8021` | Token verification failed. | Check the connection's client ID and issuer, then retry. |
| `EXT_8024`, `EXT_8025` | Provisioning or project access not allowed, or link without a recent sign-in. | Check the binding's provisioning mode and the user's group chain; sign in again before linking. |
| `EXT_8027` | Provider account already linked to another user. | Sign in with that account, or unlink it there first. |
| `EXT_8030` | Rate limited. | Honor `Retry-After`. |
| `EXT_8031` | User cancelled at the provider. | Offer to try again; do not report an error. |
| `EXT_8032` | A local account already uses this verified email. | Sign in with the existing method, then link the provider. |


### JWT configuration failure

`JWT_SECRET_KEY` is read when the app starts. If it is unset outside an explicit test runtime, the
process raises at import and never serves requests, so there is no HTTP error to catch; `AUTH_1021`
is never returned. Set a fixed secret and restart. Changing the secret invalidates every issued
token: protected routes then answer `401` `AUTH_1003`, and `POST /auth/refresh` answers a refresh
error, so every client must sign in again.

### Server errors

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `500` `DB_6002` | MySQL unreachable or connection lost; or the schema lacks a stored procedure or column the code calls. | Check database connectivity with `GET /system/health`; if the database is up, apply the canonical SQL under `schemas/`. |
| `500` `DB_6003` | SQL error or missing table. | Apply the canonical SQL under `schemas/`. |
| `500` `INT_7003` | Redis failed during a database or cache operation. | Check Redis; most authenticated calls fail while it is down. |
| `500` `INT_7001` | Unhandled exception. | Check server logs; reproduce in development with `DEBUG_MODE=true`. |
| `503` `INT_7003` on `/internal/email/*` | Transactional email not configured, or template state unreadable. | Fix the email configuration; see the [email suite](email/README.md). |

Check component health with any valid access session:

```bash
curl "$BASE_URL/system/health" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

Both `components.database.status` and `components.redis.status` should be `healthy`. The admin
view of health and cache state is in [Administration and operations](admin-usage-cases.md#system-health--metrics).

## Related

- [Client authentication guide](client-authentication-guide.md): handling these errors in client code
- [Authentication usage](authentication-usage-cases.md): login, refresh and logout flows
- [API keys suite](api-keys/README.md): API-key validation errors
- [OAuth suite](oauth/README.md): `EXT_80xx` per-endpoint behavior
- [Patreon suite](patreon-link/README.md) and [Stripe billing suite](stripe-billing/README.md): provider surfaces and their generic bodies
- [Email suite](email/README.md): the generic `202` posture
- [Administration and operations](admin-usage-cases.md): health, cache and bulk operations
