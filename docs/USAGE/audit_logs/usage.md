# Audit logs usage

One task per section. Parameter ranges, response fields and error codes are in
[reference.md](reference.md). All examples need a root or admin access token in `$ADMIN_TOKEN`.

## Pick the right endpoint

| Question | Endpoint |
| --- | --- |
| What happened, in business terms? | `GET /admin/activity` |
| Which HTTP requests were made, by whom, with what result? | `GET /admin/audit/logs` |
| What security-relevant events occurred? | `GET /admin/audit/security-events` |
| How is the API performing overall? | `GET /admin/audit/statistics` |
| What did one user do? | `GET /admin/users/{user_id}/activity` |
| Was an email sent and delivered? | `GET /admin/email/logs` |
| I need a file for a report | `POST /admin/audit/export` |

## Activity feed (dashboard)

### Browse the activity feed

`GET /admin/activity` — query `limit` (1–500), `offset`, `activity_type_filter`, `user_id`,
`project_id`, `days` (default `30`), `search`.

```bash
curl "http://localhost:8000/admin/activity?limit=50&days=7" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

Returns `activities` (newest first), `pagination` with `total`, `has_more` and `next_offset`, and
the echoed `filters`. Narrow it with an exact type or a free-text search:

```bash
curl "http://localhost:8000/admin/activity?activity_type_filter=user_type_changed&days=30" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

curl "http://localhost:8000/admin/activity?search=alice&days=7" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

`search` matches part of the activity type, the details text or the acting username.

### List activity types

`GET /admin/activity/types` returns the 101 values of the runtime `ActivityType` enum in
`activity_types`.

```bash
curl "http://localhost:8000/admin/activity/types" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

Trigger-written types such as `role_assigned` and `api_key_revoked` are not in this list but can
still be used in `activity_type_filter` ([activity types](reference.md#activity-types)).

### Open one activity entry

`GET /admin/activity/{activity_id}` returns `activity` with severity, user agent, metadata and the
catalog name, category and description.

```bash
curl "http://localhost:8000/admin/activity/act-0123456789abcdef0123456789abcdef" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

The ID must be `act-` plus 32 hex characters. Rows written by database triggers have
`act-log-{uuid}` IDs and cannot be opened here; read them from the feed or an export.

## API audit logs

### List API requests

`GET /admin/audit/logs` — query `limit` (1–1000), `offset`, `user_id`, `project_id`,
`endpoint_path` (substring), `http_method`, `status_code`, `is_success`, `security_event`, `days`.

```bash
curl "http://localhost:8000/admin/audit/logs?endpoint_path=/auth/login&is_success=false&days=7" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

Returns `logs` (newest first), `pagination` (`total`, `has_more`, `next_offset`) and `filters`.
More filters:

```bash
# All DELETE requests this week
curl "http://localhost:8000/admin/audit/logs?http_method=DELETE&days=7" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# Server errors this month
curl "http://localhost:8000/admin/audit/logs?status_code=500&days=30" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

## Security events

### Review security events

`GET /admin/audit/security-events` — query `limit` (1–500, default `100`), `days`, `severity`
(`critical`, `warning`, `info`), `source` (`api_audit`, `activity_log`).

```bash
curl "http://localhost:8000/admin/audit/security-events?severity=critical&days=1" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

Returns `events` from both logs in one shape, newest first, and a `summary` with counts by source
and severity. There is no `offset`. To see more of one log, query it on its own:

```bash
curl "http://localhost:8000/admin/audit/security-events?source=activity_log&limit=500&days=7" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

API-audit severity comes from the status code (`403` is `critical`; `401` and 5xx are `warning`).
Activity-log events keep the severity of their catalog entry.

## Audit statistics

### Summarize API traffic

`GET /admin/audit/statistics` — query `days` (default `7`).

```bash
curl "http://localhost:8000/admin/audit/statistics?days=30" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

Returns `overview` (totals, success rate, durations, sizes), `by_method`, `top_endpoints` (up to
20, with success and failure counts) and `status_distribution`.

## User activity

### Summarize one user

`GET /admin/users/{user_id}/activity` — path `user_id` is the internal ID (`usr-...`); query
`days`.

```bash
curl "http://localhost:8000/admin/users/$USER_ID/activity?days=30" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

Returns `summary` (activity counts by category and name, API request totals) and `timeline`, up to
50 entries from each log merged newest first. There is no paging; use `GET /admin/activity` and
`GET /admin/audit/logs` with `user_id` for the full history. Unknown IDs return `404`.

## Email delivery logs

### List sent and failed emails

`GET /admin/email/logs` — query `limit` (1–500), `offset`, and exact `status`, `purpose`,
`provider`.

```bash
curl "http://localhost:8000/admin/email/logs?status=dead&purpose=password_reset&limit=100" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

Returns `logs` from the `email_messages` ledger, newest first. Each row shows `recipient_hash` and
`recipient_masked`, never the plaintext address, subject or body.

```json
{
  "success": true,
  "logs": [
    {
      "id": "em-...",
      "user_id": "usr-...",
      "user_email_id": "uem-...",
      "purpose": "password_reset",
      "template_code": "password_reset",
      "recipient_hash": "A1B2C3...",
      "recipient_masked": "a***e@example.com",
      "provider": "resend",
      "provider_message_id": "re_...",
      "status": "delivered",
      "priority": 5,
      "attempt_count": 1,
      "max_attempts": 8,
      "next_attempt_at": "2026-09-24T12:00:00",
      "sent_at": "2026-09-24T12:00:01",
      "terminal_at": "2026-09-24T12:00:05",
      "last_error_code": null,
      "created_at": "2026-09-24T12:00:00",
      "updated_at": "2026-09-24T12:00:05"
    }
  ],
  "pagination": { "limit": 50, "offset": 0, "returned": 1, "has_more": false, "next_offset": null },
  "filters": { "status": "delivered", "purpose": null, "provider": null },
  "generated_at": "2026-09-24T12:05:00Z"
}
```

There is no total count and no `days` filter. `has_more` is `true` whenever the page is full, so
keep paging until a page returns fewer than `limit` rows. Provider webhook events also write
activity rows (`email_message_sent`, `email_message_delivered`, `email_message_bounced`,
`email_message_complained`, `email_suppression_updated`); the worker writes none.

## Export

### Download records as CSV or JSON

`POST /admin/audit/export` — JSON body `source` (`activity` or `api_audit`), `format` (`csv` or
`json`), optional `limit` (default `1000`, max `10000`) and `filters`.

```bash
curl -X POST "http://localhost:8000/admin/audit/export" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"source": "api_audit", "format": "csv", "limit": 5000, "filters": {"days": 7, "is_success": false}}' \
  --output audit_failures_7d.csv
```

The file downloads as `audit_export_{source}_{timestamp}.{format}`. If more than `10,000` records
match `filters`, the call fails with `400` `VAL_3009` even when `limit` is smaller; add filters
until the match count is at most `10,000`. Filter keys and output columns are in
[reference.md](reference.md#export).
