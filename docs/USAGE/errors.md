# Error Reference

Consolidated reference for all error response shapes, categories, status codes, and common troubleshooting guidance across the API.

---

## Table of Contents

- [Error Response Shape](#error-response-shape)
- [Debug Mode Differences](#debug-mode-differences)
- [Status Code Summary](#status-code-summary)
- [Error Code Catalog](#error-code-catalog)
- [UUID Masking](#uuid-masking)
- [Common Error Scenarios](#common-error-scenarios)
- [Troubleshooting Guide](#troubleshooting-guide)

---

## Error Response Shape

### Production (DEBUG_MODE=false)

All errors follow this standardized shape:

```json
{
  "status": "error",
  "error": {
    "code": "INVALID_CREDENTIALS",
    "category": "authentication",
    "message": "Invalid username or password"
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | Always `"error"` for error responses |
| `error.code` | string | Machine-readable ErrorCode enum name (e.g., `INVALID_CREDENTIALS`, `ACCESS_DENIED`) |
| `error.category` | string | Error category (e.g., `authentication`, `authorization`, `validation`) |
| `error.message` | string | Human-readable description |

### Success responses use a different shape:

```json
{
  "success": true,
  "message": "Operation completed successfully",
  "data": { ... }
}
```

---

## Debug Mode Differences

When `DEBUG_MODE=true`, the error object includes two additional fields:

```json
{
  "status": "error",
  "error": {
    "code": "INVALID_CREDENTIALS",
    "category": "authentication",
    "message": "Invalid username or password",
    "details": {
      "function": "login",
      "file": "src/routes/auth.py",
      "line": 145,
      "context": { ... }
    },
    "trace": "Traceback (most recent call last):\n  File ..."
  }
}
```

| Field | Description |
|-------|-------------|
| `details` | Structured context: function name, file path, line number, and relevant variables |
| `trace` | Full Python traceback string |

> **WARNING**: Never enable `DEBUG_MODE` in production. It exposes internal file paths, line numbers, and stack traces.

---

## Status Code Summary

| HTTP Status | Category | When |
|-------------|----------|------|
| `200` | Success | Normal successful responses |
| `201` | Created | Resource created (`POST /roles/roles`, `POST /roles/permission-groups`, `POST /roles/permissions`) |
| `202` | Accepted | Generic public email activation/forgot/reset/add/resend acceptance |
| `204` | No Content | `GET /ping` health check |
| `400` | Validation | Missing fields, invalid input, validation failures |
| `401` | Authentication | Invalid credentials, expired/invalid session, inactive account |
| `403` | Authorization | Insufficient permissions, access denied, project access denied |
| `404` | Not Found | User, project, group, role, or permission not found |
| `409` | Conflict | Username/email already exists, duplicate entry |
| `413` | Payload Too Large | POST body exceeds 8MB limit |
| `429` | Rate Limited | Email send/resend/consume/login/change-password buckets exceeded; honor `Retry-After` |
| `422` | Unprocessable Entity | Missing `User-Agent` header, malformed form data |
| `500` | Internal Server Error | Server errors, database failures, generic external-service failures |
| `501` | Not Implemented | `PATCH /projects/{hash}/owner`, `PATCH /projects/{hash}/archive` |
| `502` | Bad Gateway | Google OAuth authorization-code exchange failed (`OAUTH_CODE_EXCHANGE_FAILED`) |
| `503` | Service Unavailable | Google OAuth provider not configured/unhealthy (`OAUTH_PROVIDER_NOT_CONFIGURED`) |

---

## Error Code Catalog

Error codes are defined in `src/Util/error_handler.py` as the `ErrorCode` enum. Below are the codes **actually used** in the codebase, grouped by category.

### Authentication Errors (401)

| Code | Enum Value | Message | Cause | Resolution |
|------|-----------|---------|-------|------------|
| `AUTH_1001` | `INVALID_CREDENTIALS` | Invalid credentials | Wrong credentials on login or generic current-password denial on `/auth/password/change` | Verify credentials without branching on user/account state |
| `AUTH_1002` | `SESSION_EXPIRED` | Invalid or expired access session | Access token expired, access session deleted, or access credential malformed | Call `/auth/refresh` with the current refresh token if available; otherwise re-authenticate |
| `AUTH_1003` | `SESSION_INVALID` | Session is invalid | Token malformed or not found | Re-authenticate via login |
| `AUTH_1004` | `TOKEN_INVALID` | Token invalid | JWT malformed or failed validation | Use a valid access/refresh token for the endpoint |
| `AUTH_1005` | `ACCOUNT_INACTIVE` | Account is inactive | User status is `inactive` | Contact admin to reactivate |
| `AUTH_1010` | `API_KEY_INVALID` | Invalid API key | `X-API-Key` malformed, fails HMAC verification, or owner is inactive (raised via the API-key validation adapter/middleware) | Use a valid, active API key |
| `AUTH_1011` | `API_KEY_EXPIRED` | API key has expired | Key's `expires_at` has elapsed | Rotate or recreate the API key |
| `AUTH_1012` | `API_KEY_REVOKED` | API key has been revoked | Key was revoked by owner/admin | Create a new key |
| `AUTH_1013` | `REFRESH_TOKEN_INVALID` | Invalid refresh token | Refresh token malformed, missing Redis family/token record, hash mismatch, or otherwise not valid/current | Re-authenticate via login |
| `AUTH_1014` | `REFRESH_TOKEN_MISSING` | Refresh token required | `/auth/refresh` called without `refresh_token` cookie/body | Send a valid refresh token or log in again |
| `AUTH_1015` | `REFRESH_TOKEN_REUSED` | Refresh token reused | Old/used refresh token presented again; family revoked | Clear credentials and force re-login |
| `AUTH_1016` | `REFRESH_TOKEN_MISMATCH` | Refresh token mismatch | Cookie and explicit body refresh tokens differ | Send one matching refresh token source |
| `AUTH_1017` | `REFRESH_FAMILY_REVOKED` | Refresh family revoked | Logout, reuse detection, deactivation, or admin revocation invalidated the family | Re-authenticate via login |
| `AUTH_1018` | `TOKEN_TYPE_INVALID` | Wrong token type | Refresh token used as access token, or access/session token used for refresh | Use the correct token type for the endpoint |
| `AUTH_1019` | `TOKEN_EXPIRED` | Token expired | JWT `exp` claim elapsed. Access-token expiry is recoverable through `/auth/refresh`; refresh-token expiry is terminal. | Refresh access token if the refresh token is still valid; otherwise re-authenticate |
| `AUTH_1020` | `SESSION_REVOKED` | Session revoked | Server-side session/family context cannot be trusted, including unreconstructable legacy refresh context | Re-authenticate via login |
| `AUTH_1021` | `JWT_CONFIGURATION_FAILURE` | JWT configuration failure | `JWT_SECRET_KEY` missing/invalid outside tests | Set `JWT_SECRET_KEY`; this is an operator issue |

### Authorization Errors (403)

| Code | Enum Value | Message | Cause | Resolution |
|------|-----------|---------|-------|------------|
| `AUTHZ_2001` | `ACCESS_DENIED` | Access denied | User lacks required permission for endpoint | Contact admin to grant permission |
| `AUTHZ_2002` | `INSUFFICIENT_PERMISSIONS` | Insufficient permissions | User lacks specific permission (e.g., `manage_users`) | Contact admin to grant permission |
| `AUTHZ_2003` | `PROJECT_ACCESS_DENIED` | Access denied to project | User not in a group with access to the project | Verify user group → project group → project chain |
| `AUTHZ_2004` | `GROUP_ACCESS_DENIED` | Group access denied | User cannot access the requested group | Verify group membership |
| `AUTHZ_2005` | `RESOURCE_ACCESS_DENIED` | Resource access denied | Generic resource access failure | Check resource-level permissions |
| `AUTHZ_2006` | `ROLE_ASSIGNMENT_DENIED` | Role assignment denied | Cannot assign/remove role | Check role management permissions |
| `AUTHZ_2007` | `PERMISSION_DENIED` | Permission denied | Generic permission failure | Check specific permission requirements |
| `AUTHZ_2008` | `API_KEY_NO_ACCESS` | API key has no project access | API-key-authenticated admin is not assigned to the requested project | Verify the API key admin's project assignment |

### Validation Errors (400)

| Code | Enum Value | Message | Cause | Resolution |
|------|-----------|---------|-------|------------|
| `VAL_3001` | `INVALID_INPUT` | Invalid input | Field value does not match expected format | Check field type and constraints |
| `VAL_3002` | `MISSING_REQUIRED_FIELD` | Missing required field | Required form field not provided | Include all required fields |
| `VAL_3003` | `INVALID_FORMAT` | Invalid format | Input format is wrong | Check expected format |
| `VAL_3004` | `INVALID_UUID` | Invalid UUID | UUID format is invalid | Verify UUID format |
| `VAL_3005` | `INVALID_EMAIL` | Invalid email | Email format is invalid | Use a valid email address |
| `VAL_3006` | `INVALID_USERNAME` | Invalid username | Username format is invalid | Check username constraints |
| `VAL_3007` | `WEAK_PASSWORD` | Weak password | Shared server-side password policy rejected a password-setting request | Show safe `reason_codes` / `min_length`; never echo the submitted password |
| `VAL_3008` | `INVALID_DATE` | Invalid date | Date format is invalid | Use valid date format |
| `VAL_3009` | `INVALID_RANGE` | Invalid range | Value is out of allowed range | Check range constraints (e.g., limit 1-1000, days 1-365) |
| `VAL_3010` | `INVALID_LENGTH` | Invalid length | Value length is invalid | Check length constraints |
| `VAL_3011` | `INVALID_TYPE` | Invalid type | Value type is wrong | Check expected type |
| `VAL_3012` | `INVALID_ENUM_VALUE` | Invalid enum value | Value is not a valid enum option | Use a valid enum value (e.g., source: `activity`, `api_audit`, `audit`) |

### Not Found Errors (404)

| Code | Enum Value | Message | Cause | Resolution |
|------|-----------|---------|-------|------------|
| `NF_4001` | `USER_NOT_FOUND` | User not found | User hash does not exist | Verify user hash |
| `NF_4002` | `PROJECT_NOT_FOUND` | Project not found | Project hash does not exist | Verify project hash |
| `NF_4003` | `GROUP_NOT_FOUND` | Group not found | Group hash does not exist | Verify group hash |
| `NF_4004` | `RESOURCE_NOT_FOUND` | Resource not found | Generic resource not found | Verify resource identifier |
| `NF_4005` | `PERMISSION_NOT_FOUND` | Permission not found | Permission hash does not exist | Verify permission hash |
| `NF_4006` | `SESSION_NOT_FOUND` | Session not found | Session hash does not exist | Verify session or re-authenticate |
| `NF_4007` | `ROLE_NOT_FOUND` | Role not found | Role hash does not exist | Verify role hash |
| `NF_4008` | `ENDPOINT_NOT_FOUND` | Endpoint not found | Route does not exist | Check API documentation |
| `NF_4009` | `USER_TYPE_NOT_FOUND` | User type not found | User type does not exist | Use valid user type (root, admin, consumer) |
| `NF_4010` | `API_KEY_NOT_FOUND` | API key not found | API key id/public id does not exist or is not owned by the caller | Verify the key id; list your keys via `GET /users/api-keys` |

### Conflict Errors (409)

| Code | Enum Value | Message | Cause | Resolution |
|------|-----------|---------|-------|------------|
| `CONF_5001` | `USERNAME_EXISTS` | Username already exists | Registration or user creation with duplicate username | Use `POST /auth/check-availability` first |
| `CONF_5002` | `EMAIL_EXISTS` | Email already exists | Registration or user creation with duplicate email | Use `POST /auth/check-availability` first |
| `CONF_5003` | `RESOURCE_EXISTS` | Resource already exists | Attempting to create a resource that already exists | Use the existing resource or choose a different identifier |
| `CONF_5004` | `DUPLICATE_ENTRY` | Duplicate entry | Database-level duplicate constraint violation | Check for existing records |
| `CONF_5005` | `STATE_CONFLICT` | State conflict | Operation conflicts with current resource state | Check resource state before operation |
| `CONF_5006` | `VERSION_CONFLICT` | Version conflict | Optimistic locking version mismatch | Refresh and retry |

### Database Errors (500)

| Code | Enum Value | Message | Cause | Resolution |
|------|-----------|---------|-------|------------|
| `DB_6001` | `DATABASE_ERROR` | Database error | Generic database failure | Check DB connection and logs |
| `DB_6002` | `CONNECTION_ERROR` | Database connection failed | MySQL unreachable or credentials invalid | Check DB connection settings |
| `DB_6003` | `QUERY_ERROR` | Query execution failed | SQL error (syntax, constraint violation, etc.) | Check query parameters and DB state |
| `DB_6004` | `TRANSACTION_ERROR` | Transaction error | Transaction failed | Check transaction isolation and locks |
| `DB_6005` | `CONSTRAINT_VIOLATION` | Constraint violation | Database constraint violated | Check data integrity |
| `DB_6006` | `DEADLOCK` | Database deadlock | Concurrent transaction deadlock | Retry with backoff |

### Internal Errors (500)

| Code | Enum Value | Message | Cause | Resolution |
|------|-----------|---------|-------|------------|
| `INT_7001` | `INTERNAL_ERROR` | Internal server error | Unhandled exception | Check server logs; report with DEBUG_MODE context |
| `INT_7002` | `CONFIGURATION_ERROR` | Configuration error | Invalid or missing configuration | Check environment variables |
| `INT_7003` | `SERVICE_UNAVAILABLE` | Service unavailable | Dependent service is down | Check service health |
| `INT_7004` | `TIMEOUT` | Request timeout | Operation timed out | Check network and service performance |
| `INT_7005` | `RATE_LIMIT_EXCEEDED` | Rate limit exceeded | Email send/resend/consume/login/change-password buckets exceeded | Wait and retry after the `Retry-After` header |
| `INT_7006` | `FEATURE_NOT_IMPLEMENTED` | Feature not implemented | Endpoint is a reserved stub | Do not call; reserved for future use (`PATCH /projects/{hash}/owner`, `PATCH /projects/{hash}/archive`) |

### External Service Errors (`EXT_8xxx`, category `external`)

Generic third-party failures default to `500`; the Google OAuth / external-identity flows in this family carry their own HTTP status (see the status column).

| Code | Enum Value | HTTP | Notes |
|------|-----------|------|-------|
| `EXT_8001` | `EXTERNAL_SERVICE_ERROR` | 500 | Generic third-party service failure |
| `EXT_8002` | `EXTERNAL_API_ERROR` | 500 | Third-party API returned an error |
| `EXT_8003` | `EXTERNAL_TIMEOUT` | 500 | Third-party service timed out |

#### Google OAuth / External Identity (`EXT_80xx`)

These power the `/auth/google/*` flows. Public messages are intentionally neutral (e.g. "OAuth authentication could not be completed.") and never reveal which check failed; the codes below are for operators/clients reading the `error.code`. Full per-endpoint behavior lives in the [Google OAuth Suite](google-oauth/README.md).

| Code | Enum Value | HTTP | Meaning |
|------|-----------|------|---------|
| `EXT_8010` | `OAUTH_PROVIDER_NOT_CONFIGURED` | 503 | Provider prerequisites missing/unhealthy |
| `EXT_8011` | `OAUTH_PROVIDER_DISABLED` | 403 (start) / 404 (map default) | OAuth disabled by config |
| `EXT_8012` | `OAUTH_PROVIDER_INIT_INVALID` | 401 | Opaque provider-init token invalid |
| `EXT_8013` | `OAUTH_REDIRECT_URI_NOT_ALLOWED` | 400 | Return/redirect URI not allow-listed |
| `EXT_8014` | `OAUTH_STATE_INVALID` | 401 | Missing/invalid state token |
| `EXT_8015` | `OAUTH_STATE_EXPIRED` | 401 | State token expired |
| `EXT_8016` | `OAUTH_STATE_REUSED` | 401 | State token already consumed |
| `EXT_8017` | `OAUTH_NONCE_MISMATCH` | 401 | ID-token nonce mismatch |
| `EXT_8018` | `OAUTH_CODE_EXCHANGE_FAILED` | 502 | Authorization-code exchange with Google failed |
| `EXT_8019` | `OAUTH_ID_TOKEN_INVALID` | 401 | ID token missing/invalid/unverifiable claims |
| `EXT_8020` | `OAUTH_ISSUER_MISMATCH` | 401 | ID-token issuer not allowed |
| `EXT_8021` | `OAUTH_AUDIENCE_MISMATCH` | 401 | ID-token audience mismatch |
| `EXT_8022` | `OAUTH_TOKEN_EXPIRED` | 401 | ID/access token expired |
| `EXT_8023` | `OAUTH_WORKSPACE_DENIED` | 401 | Workspace/`hd` domain not permitted |
| `EXT_8024` | `OAUTH_PROVISIONING_DENIED` | 401 | Provisioning mode forbids this action |
| `EXT_8025` | `OAUTH_PROJECT_ACCESS_DENIED` | 403 | Resolved identity has no access to the project |
| `EXT_8026` | `EXTERNAL_IDENTITY_ALREADY_LINKED` | 409 | Reserved/latent — defined but not currently emitted |
| `EXT_8027` | `EXTERNAL_IDENTITY_SUB_CONFLICT` | 409 | Google `sub` already maps to a different account (broad link/finish failure) |
| `EXT_8028` | `EXTERNAL_IDENTITY_NOT_LINKED` | 404 | Unlink/reauth on an account with no linked identity |
| `EXT_8029` | `OAUTH_PASSWORD_REQUIRED_FOR_UNLINK` | 409 | Cannot unlink the only credential without setting a password first |
| `EXT_8030` | `OAUTH_RATE_LIMITED` | 429 | OAuth rate limit hit; honor `Retry-After` |

### Email / Transactional Auth Email Errors

Email-specific codes are reserved in the `EMAIL_9xxx` range. Public email flows intentionally avoid detailed user-visible outcomes to prevent enumeration.

| Code | Enum Value | Public posture | Notes |
|------|-----------|----------------|-------|
| `EMAIL_9001` | `EMAIL_DELIVERY_DISABLED` | Operator-facing/sanitized | Delivery is disabled by config; accepted API requests may still keep durable rows for later inspection. |
| `EMAIL_9002` | `EMAIL_PROVIDER_NOT_READY` | Operator-facing/sanitized | Provider prerequisites are missing or unhealthy. |
| `EMAIL_9003` | `EMAIL_REAL_SEND_BLOCKED_IN_TEST` | Test/operator-facing | No-real-send guard blocked real provider use in tests. |
| `EMAIL_9004` | `EMAIL_TOKEN_INVALID` | Generic `202` on public consume flows | Token malformed/unknown/invalid; public flows must not reveal which. |
| `EMAIL_9005` | `EMAIL_IDEMPOTENCY_CONFLICT` | Sanitized/generic | Same `Idempotency-Key` was reused with different request semantics. |
| `EMAIL_9006` | `EMAIL_SUPPRESSED` | Sanitized/operator-facing | Recipient hash is suppressed because of bounce/complaint/compliance state. |
| `EMAIL_9007` | `EMAIL_WEBHOOK_INVALID` | `400` for webhook caller | Missing/invalid Svix signature or rejected webhook payload; no mutation should happen. |
| `EMAIL_9008` | `EMAIL_OUTBOX_FAILURE` | Sanitized/operator-facing | Durable outbox/claim/finalize failure. |
| `EMAIL_9009` | `EMAIL_PROVIDER_SEND_FAILED` | Sanitized/operator-facing | Provider send failed; no raw provider payload should be exposed. |
| `EMAIL_9010` | `EMAIL_TEMPLATE_INVALID` | Sanitized/operator-facing | Transactional template/render failure. |

Public email endpoints return generic `202` when syntactically processable:

- `POST /auth/email/verify`
- `POST /auth/password/forgot`
- `POST /auth/password/reset`
- authenticated add/resend email routes

`429 RATE_LIMIT_EXCEEDED` with `Retry-After` is the intended public exception.

### Password and Recovery Error Details

Password-setting and recovery surfaces use sanitized, non-enumerating errors:

| Surface | Public code/status | Safe client behavior |
|---------|--------------------|----------------------|
| Weak registration/reset/change password | `VAL_3007` / 400 | Read `details.reason_codes` and `details.min_length`; do not expect the submitted password, denylist contents, hashes, token secrets, full links, or provider payloads. |
| Wrong current password on `/auth/password/change` | `AUTH_1001` / 401 | Show generic invalid-credentials copy; do not distinguish wrong password from account/session state. |
| Profile password mutation | `VAL_3001` / 400 | Use `POST /auth/password/change`; profile updates are for non-password fields only. |
| Change-password rate limit | `INT_7005` / 429 | Honor `Retry-After`; no credential or session success side effect occurred. |
| Unsupported bulk/admin password-control field | `VAL_3001` / 400 | Do not send `force_password_reset`; use reset-link recovery or `/auth/password/change`. |

Safe weak-password `reason_codes` currently include `too_short`, `common_password`, `obvious_identifier_derivation`, and `repeated_or_sequential`. These are categories, not leaked password material.

### Other Codes Defined but Not Currently Raised

The following codes exist in the `ErrorCode` enum but are **not currently raised** by any route in the codebase:

| Code | Enum Value | Notes |
|------|-----------|-------|
| `AUTH_1006` | `ACCOUNT_LOCKED` | Defined but not used (no account-lockout flow) |
| `AUTH_1007` | `PASSWORD_RESET_REQUIRED` | Defined but not used |
| `AUTH_1008` | `MFA_REQUIRED` | Defined but not used (MFA not implemented) |
| `AUTH_1009` | `MFA_INVALID` | Defined but not used (MFA not implemented) |
| `INT_7003` | `SERVICE_UNAVAILABLE` | Defined but not used |
| `EXT_8026` | `EXTERNAL_IDENTITY_ALREADY_LINKED` | Reserved/latent — defined and mapped (409) but not currently emitted by any route |

### Known Route References to Missing Enum Members

Some route paths currently reference names that are **not** defined in `ErrorCode`. Those paths surface as generic `INTERNAL_ERROR` until source code or the enum is fixed:

| Missing name | Known impact |
|--------------|--------------|
| `ALREADY_EXISTS` | Duplicate project-catalog role entry path |
| `NOT_FOUND` | Some generic not-found paths in roles/user-type/group helpers |
| `OPERATION_NOT_ALLOWED` | System-role delete path |
| `PERMISSION_GROUP_NOT_FOUND` | Permission-group not-found paths in roles/permissions routes |

---

## UUID Masking

All error responses **mask UUIDs** for security. Full identifiers are never exposed in error messages.

**Example:**

```
"User usr-[550e]...[0000] not found"
```

Instead of:

```
"User usr-550e8400-e29b-41d4-a716-446655440000 not found"
```

**Implications for clients:**
- You **cannot** parse full IDs from error messages
- Use the `user_hash`, `project_hash`, etc. from **success responses** for subsequent operations
- Error messages are for human debugging, not programmatic parsing

---

## Common Error Scenarios

### Login Fails

**Symptoms**: `401 INVALID_CREDENTIALS` on `POST /auth/login`

**Checklist**:
1. Verify username is correct (can be username OR email)
2. Verify password is correct
3. Check user account is active (`GET /users/{hash}` as admin)
4. Check Redis is running (sessions require Redis)

### Registration Fails

**Symptoms**: `404 GROUP_NOT_FOUND` or `400 INVALID_INPUT` on `POST /auth/register`

**Checklist**:
1. The `user_group_hash` must exist and be active
2. The user group must be linked to at least one project via a project group
3. Use `POST /auth/check-availability` before registering to avoid `409` conflicts

### Session Suddenly Invalid

**Symptoms**: `401 SESSION_EXPIRED`, `TOKEN_EXPIRED`, `SESSION_INVALID`, `SESSION_REVOKED`, or `REFRESH_FAMILY_REVOKED` on authenticated endpoints

**Checklist**:
1. Access token expired or `session:{access_jti}` was evicted by the short access TTL — call `/auth/refresh` with a valid current refresh token.
2. Refresh token expired/revoked/reused — clear credentials and re-authenticate.
3. Redis restarted or flushed — if refresh family/token/anchor state is gone, re-authenticate.
4. `JWT_SECRET_KEY` changed — all existing JWTs invalid; re-authenticate after operator fixes config
5. Admin deactivated/deleted/bulk-deactivated the user — sessions and refresh families are centrally revoked

### Refresh Token Required / Invalid

**Symptoms**: `401 REFRESH_TOKEN_MISSING`, `REFRESH_TOKEN_INVALID`, or `TOKEN_TYPE_INVALID` on `POST /auth/refresh`

Correct refresh request for non-browser clients:

```bash
curl -X POST "{BASE_URL}/auth/refresh" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -H "User-Agent: my-client/1.0" \
  -d "refresh_token=$REFRESH_TOKEN"
```

Canonical error envelope example:

```json
{
  "status": "error",
  "error": {
    "code": "AUTH_1014",
    "category": "authentication",
    "message": "A valid refresh token is required"
  }
}
```

Do **not** send `Authorization: Bearer <access_token>` to `/auth/refresh`; access/session tokens are rejected immediately and are not upgrade credentials.

Access-token expiry by itself should not surface here as `AUTH_1002` from `/auth/refresh`. The provider keeps `session:{access_jti}` short-lived and uses `refresh_anchor:{family_id}` plus DB reconstruction to rotate a valid current refresh token after the old access session has expired. If `/auth/refresh` returns one of the refresh-specific codes above, treat it as a refresh credential/state problem, not as a recoverable access-token expiry.

### Refresh Token Reuse or Family Revoked

**Symptoms**: `401 REFRESH_TOKEN_REUSED` or `REFRESH_FAMILY_REVOKED`

```json
{
  "status": "error",
  "error": {
    "code": "AUTH_1015",
    "category": "authentication",
    "message": "Refresh token reuse detected"
  }
}
```

**Checklist**:
1. Stop retrying refresh; the whole family is revoked.
2. Clear access and refresh tokens/cookies.
3. Force re-login.
4. Serialize refresh calls in clients so duplicate 401 handlers do not reuse the same refresh token.

### Inactive Account / Revoked Session

**Symptoms**: `401 ACCOUNT_INACTIVE`, `SESSION_REVOKED`, or `REFRESH_FAMILY_REVOKED` after deactivation/delete/bulk-deactivation

```json
{
  "status": "error",
  "error": {
    "code": "AUTH_1020",
    "category": "authentication",
    "message": "Session has been revoked"
  }
}
```

Once an account is inactive, deleted, or bulk-deactivated, old access and refresh credentials fail closed. Contact an administrator; clients should not refresh-loop.

### JWT Configuration Failure

**Symptoms**: startup/auth initialization failure or `JWT_CONFIGURATION_FAILURE`/configuration error

```json
{
  "status": "error",
  "error": {
    "code": "AUTH_1021",
    "category": "authentication",
    "message": "JWT secret key is not configured"
  }
}
```

This is an operator/configuration issue. Set `JWT_SECRET_KEY` outside explicit tests; the service no longer uses a silent random runtime fallback.

### Email Flow Returns 202 But Nothing Happens

This is expected public posture. `202` means the request was accepted for processing, not that an email/account/token exists.

Checklist:

1. For forgot/reset/verify, do not reveal state to the user.
2. Check `/system/health` email components as an operator.
3. Inspect `/admin/email/logs` as admin/root for masked/hash delivery state.
4. If `429`, wait for `Retry-After` before retrying.
5. Never log or paste activation/reset full links or token secrets.

### Google OAuth Flow Fails

**Symptoms**: an `EXT_80xx` code in `error.code` with a neutral message such as "OAuth authentication could not be completed."

The public message is deliberately generic and does **not** reveal which check failed. Read `error.code` to triage:

| If you see | Likely cause | Action |
|------------|--------------|--------|
| `OAUTH_PROVIDER_DISABLED` / `OAUTH_PROVIDER_NOT_CONFIGURED` | OAuth disabled or misconfigured | Operator: set/enable the `GOOGLE_OAUTH_*` config |
| `OAUTH_STATE_INVALID` / `_EXPIRED` / `_REUSED` | Stale/replayed callback or back-button reuse | Restart the flow from `POST /auth/google/start` |
| `OAUTH_ID_TOKEN_INVALID` / `_ISSUER_MISMATCH` / `_AUDIENCE_MISMATCH` | Token verification failed | Check client id/issuer config; retry a fresh sign-in |
| `OAUTH_PROVISIONING_DENIED` / `OAUTH_PROJECT_ACCESS_DENIED` | Identity resolved but provisioning/project access not allowed | Verify provisioning mode and the user's group→project chain |
| `EXTERNAL_IDENTITY_SUB_CONFLICT` (409) | Google account already maps to a different user | Sign in with the original account or unlink first |
| `OAUTH_RATE_LIMITED` (429) | Too many OAuth attempts | Honor `Retry-After` |

Full per-endpoint behavior is in the [Google OAuth Suite](google-oauth/README.md).

### Access Denied to Project

**Symptoms**: `403 PROJECT_ACCESS_DENIED`

**Checklist**:
1. User must be in a user group
2. User group must have access to a project group
3. Project must be in that project group
4. Verify the chain: `USER → USER_GROUP → PROJECT_GROUP → PROJECT`

### 422 on POST/PUT/PATCH

**Symptoms**: `422 Unprocessable Entity`

**Checklist**:
1. Missing `User-Agent` header — **required on every request**
2. Sending `application/json` instead of `multipart/form-data` — most write endpoints use `Form(...)`
3. Missing required form fields

---

## Troubleshooting Guide

### Step 1: Identify the error category

Look at the `category` field in the error response:

| Category | Likely cause |
|----------|-------------|
| `authentication` | Credentials, session, token issues |
| `authorization` | Permission or access scope issues |
| `validation` | Missing/invalid input |
| `not_found` | Resource does not exist |
| `conflict` | Duplicate resource |
| `database` | DB connectivity or query issues |
| `internal` | Server-side bug, rate limits, unimplemented stubs |
| `external` | Google OAuth / external-identity flow failure (`EXT_8xxx`) |
| `email` | Transactional email delivery/safety state (`EMAIL_9xxx`) |

### Step 2: Check DEBUG_MODE (development only)

If in development, enable `DEBUG_MODE=true` to get full traceback and context. **Disable in production.**

### Step 3: Verify the access chain

For project access issues, trace the full chain:

```bash
# 1. Check user's groups
curl -X GET "{BASE_URL}/admin/user-groups/users/$USER_HASH/groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "User-Agent: my-client/1.0"

# 2. Check group's project group access
curl -X GET "{BASE_URL}/admin/user-groups/$GROUP_HASH/project-groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "User-Agent: my-client/1.0"

# 3. Check project group's projects
curl -X GET "{BASE_URL}/admin/project-groups/$PG_HASH/projects" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "User-Agent: my-client/1.0"
```

### Step 4: Check system health

Use any valid access session:

```bash
curl -X GET "{BASE_URL}/system/health" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "User-Agent: my-client/1.0"
```

Verify both `database` and `redis` components report `healthy`.

### Step 5: Check cache state

Stale cache can cause permission mismatches after admin changes:

```bash
curl -X GET "{BASE_URL}/system/cache/stats" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "User-Agent: my-client/1.0"
```

If needed, invalidate the affected user's cache:

```bash
curl -X POST "{BASE_URL}/system/cache/invalidate/user/$USER_HASH" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "User-Agent: my-client/1.0"
```

---

## Related Documentation

- [Getting Started](getting-started.md) — Platform setup and first steps
- [Authentication Usage Cases](authentication-usage-cases.md) — Auth flows and troubleshooting
- [Client Authentication Guide](client-authentication-guide.md) — Error handling in client code
- [Permission Resolution](permissions/resolution.md) — Permission resolution mechanics and the auth-vs-inspection gap
- [Google OAuth Suite](google-oauth/README.md) — `EXT_8xxx` OAuth/external-identity error behavior
- [API Keys Suite](api-keys/README.md) — API-key validation and `API_KEY_*` errors
- [Email Suite](email/README.md) — `EMAIL_9xxx` codes and the generic-`202` public posture

---

**Document Version**: 1.1
