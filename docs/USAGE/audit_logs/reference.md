# Audit logs reference

The contract for the audit, activity and email-log routes. Suite-wide rules (root/admin only, no
project scoping, internal IDs, lookback window) are in [README.md](README.md#rules-and-caveats).

## Endpoints

All routes take an access token (`Authorization: Bearer` or the `access_token` cookie) of a root
or admin user.

| Path | Method | Source file | Purpose |
| --- | --- | --- | --- |
| `/admin/activity` | GET | `src/routes/admin_dashboard.py` | Paged activity-log feed |
| `/admin/activity/types` | GET | `src/routes/admin_dashboard.py` | The 101 `ActivityType` values |
| `/admin/activity/{activity_id}` | GET | `src/routes/admin_dashboard.py` | One activity-log entry with catalog details |
| `/admin/audit/logs` | GET | `src/routes/audit_logs.py` | Paged per-request API audit records |
| `/admin/audit/security-events` | GET | `src/routes/audit_logs.py` | Security events from both logs, merged |
| `/admin/audit/statistics` | GET | `src/routes/audit_logs.py` | API traffic summary |
| `/admin/audit/export` | POST | `src/routes/audit_logs.py` | CSV or JSON download (JSON body) |
| `/admin/users/{user_id}/activity` | GET | `src/routes/audit_logs.py` | One user's summary and merged timeline |
| `/admin/email/logs` | GET | `src/routes/audit_logs.py` | Email outbox ledger with redacted recipients |

Query parameters outside their range are rejected before the handler runs with `400` `VAL_3001`
("Request validation failed", with `details.validation_errors`).

## Query parameters

### Activity feed parameters

`GET /admin/activity`

| Parameter | Default | Range | Match |
| --- | --- | --- | --- |
| `limit` | `50` | 1–500 | — |
| `offset` | `0` | ≥ 0 | — |
| `activity_type_filter` | — | — | Exact `activity_type`; any stored value works, including trigger types not in the enum |
| `user_id` | — | — | Exact `user_id` (internal ID): the actor for application rows; trigger rows may hold the changed user ([why](architecture.md#design-decisions-and-limits)) |
| `project_id` | — | — | Exact project (internal ID) |
| `days` | `30` | 1–365 | `created_at` within the window |
| `search` | — | — | Substring of `activity_type`, `details` or the acting username; empty is ignored |

### API audit log parameters

`GET /admin/audit/logs`

| Parameter | Default | Range | Match |
| --- | --- | --- | --- |
| `limit` | `50` | 1–1000 | — |
| `offset` | `0` | ≥ 0 | — |
| `user_id` | — | — | Exact (internal ID) |
| `project_id` | — | — | Exact (internal ID) |
| `endpoint_path` | — | — | Substring (`LIKE %value%`) |
| `http_method` | — | — | Exact |
| `status_code` | — | — | Exact `response_status` |
| `is_success` | — | — | `true` = 2xx; `false` = any other logged status |
| `security_event` | — | — | Exact flag |
| `days` | `30` | 1–365 | `request_timestamp` within the window |

### Security event parameters

`GET /admin/audit/security-events`

| Parameter | Default | Range | Notes |
| --- | --- | --- | --- |
| `limit` | `100` | 1–500 | Read from each source, then applied again to the merged list |
| `days` | `30` | 1–365 | Activity-log events use `days × 24` hours |
| `severity` | — | `critical`, `warning`, `info` | Applied per source before merging |
| `source` | — | `api_audit`, `activity_log` | Read one source; any other value returns no events |

### Other parameters

| Route | Parameters |
| --- | --- |
| `GET /admin/audit/statistics` | `days` (default `7`, 1–365) |
| `GET /admin/users/{user_id}/activity` | Path `user_id` (internal ID, not the user hash); `days` (default `30`, 1–365) |
| `GET /admin/activity/{activity_id}` | Path `activity_id`: `act-` followed by 32 hex characters |
| `GET /admin/email/logs` | `limit` (default `50`, 1–500), `offset`, and exact-match `status`, `purpose`, `provider` |

`email_messages.status` values: `pending`, `processing`, `retry`, `sent`, `delivered`, `bounced`,
`complained`, `suppressed`, `dead`, `cancelled`. `purpose` values: `email_activation`,
`password_reset`, `admin_password_reset`, `security_notification`, `delivery_operation`,
`patreon_link_proof`. `provider` is free text (for example `resend` or `mailpit`). Unknown values
return an empty list, not an error.

## Responses

Every read response carries `generated_at` (UTC, ISO 8601 with `Z`).

### Activity feed response

```jsonc
{
  "activities": [
    {
      "id": "act-3f2a...",
      "activity_type": "user_update",
      "details": "...",
      "created_at": "2026-09-24T10:00:00Z",
      "user": { "id": "usr-...", "username": "alice", "user_hash": "..." },
      "project": { "id": "...", "name": "Main", "hash": "..." },
      "target_user": null,
      "ip_address": "203.0.113.7"
    }
  ],
  "pagination": { "total": 123, "limit": 50, "offset": 0, "has_more": true, "next_offset": 50 },
  "filters": { "activity_type": null, "user_id": null, "project_id": null, "days": 30, "search": null },
  "generated_at": "2026-09-24T10:05:00Z"
}
```

`user`, `project` and `target_user` are `null` when the row has no such ID. The echoed filter key is
`activity_type`, although the query parameter is `activity_type_filter`.

`GET /admin/activity/{activity_id}` returns `activity` with the same fields plus `severity_level`,
`user_agent`, `metadata`, `activity_name`, `activity_category` and `activity_description`.
`GET /admin/activity/types` returns `activity_types`, the list of enum values.

### API audit log fields

`GET /admin/audit/logs` returns `logs`, `pagination` (`total`, `limit`, `offset`, `has_more`,
`next_offset`) and the echoed `filters`. Each log has 33 fields:

| Field | Notes |
| --- | --- |
| `id` | `audit-{uuid}` |
| `request_id` | The `X-Request-ID` header, or `req-{uuid}` |
| `http_method`, `endpoint_path` | As received |
| `route_pattern` | Path template of the matched route (`/users/{user_hash}`); `null` when no route matches |
| `user_id`, `user_type` | From the access token or API key; `null` for anonymous requests |
| `session_id` | A non-credential session identifier, never token bytes: the access token's `session_id` claim (a UUID, stable across refreshes and project switches of one sign-in), or the API key ID for `X-API-Key` requests. A token without a usable claim is stored as `tokhash:` plus 32 hex characters (a keyed HMAC-SHA-256). Rows written before this change are masked the same way when read; see [Existing rows with token prefixes](#existing-rows-with-token-prefixes). `null` for anonymous requests. |
| `request_body`, `request_query` | Redacted JSON; `request_body` only for `POST`, `PUT`, `PATCH`, `DELETE`. Non-JSON bodies are stored as `{"_note": "Non-JSON body"}`. |
| `request_size_bytes`, `response_size_bytes` | Response size comes from `Content-Length` |
| `response_status` | `0` until the response row is written |
| `response_body` | Redacted JSON error body for `4xx`/`5xx` responses up to 64 KiB; `null` for successes and other bodies |
| `request_timestamp`, `response_timestamp` | Database time |
| `duration_ms` | Time from writing the request row to writing the response row |
| `client_ip` | First `X-Forwarded-For` entry, then `X-Real-IP`, then the socket address |
| `user_agent`, `referer` | Request headers |
| `is_success` | `true` for 2xx |
| `error_code`, `error_message` | `error.code` and `error.message` of a JSON error body; for an unhandled exception, the exception class name and message |
| `project_id` | Project of the token or key |
| `target_resource_type`, `target_resource_id` | Guessed from path segments such as `users`, `projects`, `emails` |
| `metadata` | Unused (`null`) |
| `tags` | JSON array, for example `["post", "client_error", "user_type_admin", "admin_action", "create", "security_event"]` |
| `security_event` | See [security event rules](#security-event-rules) |
| `username`, `user_hash`, `project_name`, `project_hash` | Joined at query time |

JSON columns are returned as JSON-encoded strings.

### Security events response

`events` sorted newest first, and `summary` with `total`, `by_source` (`api_audit`,
`activity_log`), `by_severity` and `period_hours`.

| Source | Fields | Severity |
| --- | --- | --- |
| `api_audit` | `id`, `source`, `timestamp`, `severity`, `event_type`, `user_id`, `username`, `client_ip`, `endpoint_path`, `http_method`, `response_status`, `error_code`, `error_message`, `duration_ms` | From the status: `403` → `critical`; `401` and 5xx → `warning`; anything else → `info` |
| `activity_log` | `id`, `source`, `timestamp`, `severity`, `event_type` (the `activity_type`), `user_id`, `username`, `client_ip`, `details`, `activity_name` | The row's `severity_level`; only `warning` and `critical` rows are read |

For `api_audit` events, `event_type` is `error_code` when set, otherwise the first tag containing
`security`, `auth` or `unauthorized`, otherwise the first tag.

### Statistics response

| Section | Fields |
| --- | --- |
| `overview` | `total_requests`, `successful_requests`, `failed_requests`, `success_rate` (percent), `avg_duration_ms`, `max_duration_ms`, `avg_request_size`, `avg_response_size` |
| `by_method[]` | `http_method`, `request_count`, `avg_duration_ms` |
| `top_endpoints[]` (up to 20) | `endpoint_path`, `request_count`, `avg_duration_ms`, `success_count`, `failure_count` |
| `status_distribution[]` | `response_status`, `count` |

### User activity response

| Field | Notes |
| --- | --- |
| `user_id` | As requested |
| `summary.activity_log_count` | Activity rows read for the user as actor (at most 500) |
| `summary.api_audit_count` | `total_requests` from the API audit summary |
| `summary.total_activities` | Sum of the two counts |
| `summary.activity_summary[]` | `activity_category`, `activity_name`, `count`, `last_activity`, grouped from those rows (catalog fields are `null` for uncatalogued types) |
| `summary.api_audit_summary` | `total_requests`, `successful_requests`, `failed_requests`, `unique_endpoints`, `first_request`, `last_request`, `avg_duration_ms` |
| `timeline[]` | Up to 50 activity rows and 50 audit rows, merged newest first. Activity entries: `source`, `id`, `timestamp`, `activity_type`, `activity_name`, `details`, `severity_level`, `project_id`, `ip_address`. Audit entries: `source`, `id`, `timestamp`, `http_method`, `endpoint_path`, `response_status`, `is_success`, `duration_ms`, `client_ip`. |

### Email delivery log fields

`GET /admin/email/logs` returns `success`, `logs`, `pagination` (`limit`, `offset`, `returned`,
`has_more`, `next_offset`), the echoed `filters` and `generated_at`. There is no total:
`has_more` is `true` whenever `returned == limit`.

| Field | Notes |
| --- | --- |
| `id`, `user_id`, `user_email_id` | Message and owner references |
| `purpose`, `template_code` | What was sent |
| `recipient_hash` | Hex of the `BINARY(32)` recipient hash |
| `recipient_masked` | Masked address |
| `provider`, `provider_message_id` | Provider and its message ID |
| `status`, `priority`, `attempt_count`, `max_attempts`, `next_attempt_at` | Outbox state (`priority` default `5`, `max_attempts` default `8`) |
| `sent_at`, `terminal_at` | Provider acceptance and terminal-state times |
| `last_error_code` | Last failure code; the error message is not returned |
| `created_at`, `updated_at` | Row timestamps |

Rows are ordered by `created_at`, newest first.

## Export

`POST /admin/audit/export` with `Content-Type: application/json`.

| Field | Required | Values | Notes |
| --- | --- | --- | --- |
| `source` | Yes | `activity`, `api_audit` | Select an activity or API audit export |
| `format` | Yes | `csv`, `json` | |
| `limit` | No | 1–10000 | Default `1000`; rows returned, newest first |
| `filters` | No | Object | Unknown keys are ignored |

| Source | Filter keys |
| --- | --- |
| `api_audit`, `audit` | `user_id`, `project_id`, `endpoint_path`, `http_method`, `status_code`, `is_success`, `security_event`, `days` (default `30`) |
| `activity` | `user_id`, `project_id`, `activity_type`, `days` (default `30`). There is no `search`. |

Before streaming, the handler counts the records that match `filters`. If more than `10,000` match,
the request fails with `400` `VAL_3009`, whatever `limit` is.

The response is an attachment named `audit_export_{source}_{YYYYMMDD_HHMMSS}.{format}`:

| Format | Content |
| --- | --- |
| `csv` | Header row plus one row per record. `api_audit` has 23 columns: `id`, `request_id`, `http_method`, `endpoint_path`, `route_pattern`, `user_id`, `user_type`, `username`, `user_hash`, `project_id`, `project_name`, `project_hash`, `request_timestamp`, `response_timestamp`, `duration_ms`, `response_status`, `is_success`, `error_code`, `error_message`, `client_ip`, `user_agent`, `security_event`, `tags`. `activity` has 19: `id`, `user_id`, `activity_type`, `details`, `project_id`, `target_user_id`, `ip_address`, `user_agent`, `severity_level`, `created_at`, `username`, `user_hash`, `project_name`, `project_hash`, `target_username`, `target_user_hash`, `activity_name`, `activity_category`, `activity_description`. An empty result is a single blank line with no header. |
| `json` | One JSON array of full rows: all 33 audit fields listed above (including `session_id`, `request_body` and `request_query`), or 22 activity fields (the CSV columns plus `user_group_id`, `metadata`, `user_group_name`) |

## Activity types

`GET /admin/activity/types` returns the 101 members of `ActivityType` in
`src/Util/activity_logger.py`. That list is not the full set of stored types: database triggers
write types that are not enum members, such as `user_deleted`, `session_created`, `role_assigned`,
`permission_group_assigned`, `project_group_creation` and the `api_key_*` types.
`activity_type_filter` accepts any stored value.

`schemas/tables/08_activity_logging_tables.sql` seeds 100 `activity_catalog` rows. The catalog
gives each type a name, category and `severity_level`; `sp_log_activity` copies that severity onto
the row, and uncatalogued types get `info`.

| Catalog IDs | Types |
| --- | --- |
| `act-cat-001` … `act-cat-040` | Core authentication, user, project, group, permission, bulk, admin and system events |
| `act-cat-041` … `act-cat-045` | `api_key_created`, `api_key_revoked`, `api_key_reactivated`, `api_key_expired`, `api_key_updated` |
| `act-cat-046` … `act-cat-063` | Email identity, password recovery and email delivery (below) |
| `act-cat-075` … `act-cat-090` | `patreon_*` |
| `act-cat-091` … `act-cat-106` | Billing: reserved in runtime code, not seeded |
| `act-cat-107` … `act-cat-127` | Provider-neutral `oauth_*` sign-in and connection events |

### Email and password catalog IDs

| Catalog ID | Activity | Severity |
| --- | --- | --- |
| `act-cat-046` | `user_email_added` | `info` |
| `act-cat-047` | `user_email_activation_requested` | `info` |
| `act-cat-048` | `user_email_activation_resent` | `info` |
| `act-cat-049` | `user_email_activated` | `warning` |
| `act-cat-050` | `user_email_removed` | `warning` |
| `act-cat-051` | `user_email_primary_changed` | `warning` |
| `act-cat-052` | `auth_email_login` | `info` |
| `act-cat-053` | `password_reset_requested` | `warning` |
| `act-cat-054` | `password_reset_consumed` | `critical` |
| `act-cat-055` | `admin_password_reset_requested` | `critical` |
| `act-cat-056` | `email_message_enqueued` | `info` |
| `act-cat-057` | `email_message_sent` | `info` |
| `act-cat-058` | `email_message_delivered` | `info` |
| `act-cat-059` | `email_message_bounced` | `warning` |
| `act-cat-060` | `email_message_complained` | `critical` |
| `act-cat-061` | `email_message_dead_lettered` | `critical` |
| `act-cat-062` | `email_suppression_updated` | `warning` |
| `act-cat-063` | `password_changed` | `critical` |

`password_changed` records a successful `POST /auth/password/change`. The reset entries cover the
link-based flows, which do not create a session. `email_message_enqueued` and
`email_message_dead_lettered` are written by triggers on `email_messages` (every enqueue path, and
every move to `dead`, including the retry budget running out inside `sp_finalize_email_message`);
their `metadata` holds the message id, purpose, template code and, for dead letters, the attempt
count and error code, never the recipient.

`api_key_expired` is written by the API-key update trigger when the expiry sweep (every 5 minutes
in the API process) deactivates a key past `expires_at`.

## Security event rules

`APIAuditLogger.is_security_event` sets `security_event = true` when any of these holds:

- status `403`;
- status `401` on a path containing `/auth/`;
- status ≥ `400` on OAuth sign-in paths (`/auth/oauth/*`), Stripe or Patreon
  webhooks, or internal billing and Patreon S2S routes;
- a `/auth/patreon*` request that fails or uses `POST` or `DELETE`;
- a path containing `/admin/` requested by a root or admin user;
- any `DELETE`;
- a path containing `/user-type`, `/permissions`, `/roles`, `/password`, `/reset`, `/auth/email`
  or `/users/me/emails`;
- an unhandled exception whose class name contains `auth`, `permission` or `unauthorized`.

## Redaction

- Request bodies, query parameters and error bodies: keys that name secrets or personal data
  (`password`, `token`, `api_key`, `secret`, `email`, `recipient`, `body`, `idempotency_key`,
  OAuth, Patreon and billing field names, and similar) become `***FILTERED***`. Other string values
  have email addresses, URLs and token-like strings replaced.
- Headers: `Authorization`, `Cookie`, `X-API-Key`, idempotency and webhook-signature headers become
  `***FILTERED***`. Request and response headers are stored but not returned by any read route.
- `/webhooks/email` requests are not audited at all. Patreon and Stripe webhook bodies are stored
  as `{"_note": "Request body excluded from audit"}`.
- Email log rows expose only `recipient_hash` and `recipient_masked`. They do not return the
  plaintext address, subject, body, template variables or error message.
- Email webhook activity rows carry only the provider, event type, event and message IDs, the
  recipient hash and the names of the payload keys; the payload itself is not stored.
- `session_id` never holds token material. `AuthContextMiddleware` sets `request.state.session_id`
  to the access token's `session_id` claim, and `APIAuditLogger.log_request`,
  `log_error_to_database` and `get_audit_logs` each pass the value through
  `src/Util/audit_session_id.py`. That helper keeps plain identifiers and turns anything
  token-shaped into its `session_id` (else `jti`) claim, or into a `tokhash:` keyed hash. The claim
  is read without verifying the signature and is only a label; nothing authorizes from it. The
  hash key is derived from `JWT_SECRET_KEY`, so rotating that secret changes the `tokhash:` values.

### Existing rows with token prefixes

Before this change, `api_audit_log.session_id` and `error_logs.session_id` stored the first 256
characters of the caller's access token. Current access tokens are longer than 400 characters and
their signature starts after character 375, so a stored prefix cannot be replayed. It still holds
the token header and part of its claims, and shorter tokens would have been stored whole.

- **Reads are masked.** `GET /admin/audit/logs` and JSON exports return these values as
  `tokhash:…` (the CSV export has no `session_id` column). Rows from the same token get the same
  hash, so they still group together.
- **The data at rest is not.** Direct SQL, replicas and backups still contain the prefixes.
  `error_logs` is not returned by any route, but its rows keep them too.

To remove the stored prefixes, optionally run the statements below. They are destructive: the
affected rows lose their `session_id`, and the old values cannot be recovered. Test on a copy
first and run them in a maintenance window. Nothing runs them automatically.

```sql
-- Optional one-off cleanup. Both statements only match values that start like a JWT
-- (base64url of '{"') or contain a dot; UUIDs, API key IDs and tokhash: values are untouched.
UPDATE api_audit_log
SET session_id = NULL
WHERE session_id LIKE 'eyJ%' OR session_id LIKE '%.%';

UPDATE error_logs
SET session_id = NULL
WHERE session_id LIKE 'eyJ%' OR session_id LIKE '%.%';
```

Run a `SELECT COUNT(*)` with the same `WHERE` clause first to see how many rows each statement
will change. On a large `api_audit_log`, run the update in batches (for example, add
`LIMIT 10000` and repeat until it affects no rows) to keep lock times short.

## Error codes

| Status | Code | When |
| --- | --- | --- |
| `401` | `AUTH_1003` | Missing, invalid or expired access token |
| `403` | `AUTHZ_2001` | Caller is not a root or admin user ("Admin access required") |
| `400` | `VAL_3001` | Query parameter out of range or of the wrong type ("Request validation failed") |
| `400` | `VAL_3001` | `GET /admin/activity/{activity_id}`: ID is not `act-` plus 32 hex characters. Export: body is not valid JSON. |
| `400` | `VAL_3002` | Export: `source` or `format` missing |
| `400` | `VAL_3012` | Export: unknown `source` or `format` |
| `400` | `VAL_3009` | Export: `limit` not in 1–10000, or more than `10,000` records match |
| `404` | `NF_4004` | No activity entry with that ID |
| `404` | `NF_4001` | `GET /admin/users/{user_id}/activity`: unknown user ID |

See [Errors](../errors.md) for the envelope.
