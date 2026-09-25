# Audit logs troubleshooting

Symptom, cause and fix. Error codes are listed in [reference.md](reference.md#error-codes).

## Access

### `403` "Admin access required"

**Cause:** the caller's user type is not root or admin. Audit routes check the user type only; an
`admin` permission from a global role does not count.

**Fix:** use a root or admin account.

### An admin sees other projects' records

**Cause:** audit routes have no project scoping. Any admin sees all projects.

**Fix:** none in the API. If you need isolation, restrict who holds the admin user type, or filter
exports by `project_id` before sharing them.

## Missing or unexpected data

### A request is not in `GET /admin/audit/logs`

**Cause:** one of:

- The path is excluded: `/ping`, `/health`, `/metrics`, `/docs`, `/redoc`, `/openapi.json`,
  `/auth/validate`, `/webhooks/email` (and their sub-paths), or the method is `OPTIONS`.
- It is older than `days` (default `30`).
- The filter uses a user or project hash instead of the internal ID.
- Writing the audit row failed; the failure is only in the application log.

**Fix:** widen `days` (up to `365`), drop filters one at a time, and use internal IDs.

### `response_status` is `0` and `is_success` is `null`

**Cause:** the request row is written before the route runs, and the response is written by a
background task after the response is sent. The task has not run yet, or it failed.

**Fix:** retry the query after a moment. Rows that stay at `0` point to an audit write failure in
the application log. These rows also appear as status `0` in `status_distribution`.

### `error_code`, `error_message` and `response_body` are empty for an error

**Cause:** the row is a success, still has `response_status = 0` (the response row is not written
yet), or the error body was not JSON or was larger than 64 KiB, so it was not captured. Keys that
look sensitive (including `code`) are masked inside `response_body`; `error_code` keeps the value.

**Fix:** filter on `status_code` and `is_success`, and read `error_code` rather than
`response_body.error.code`.

### `route_pattern` is `null`

**Cause:** no route matched the path (a `404` from the router), or the row was written before the
middleware resolved route templates.

**Fix:** use `endpoint_path` with a substring filter for those rows.

### The activity feed is empty or thin

**Cause:** one of:

- Read-only routes do not write activity rows, and many decorated routes log only failures.
- The type you filter on is never written. `GET /admin/activity/types` lists enum values, not
  types that actually occur.
- `activity_type_filter` is an exact match, not a prefix or substring.

**Fix:** remove the type filter and use `search`, then pick the exact type from the results.

### `GET /admin/activity/{activity_id}` returns `400` for an ID from the feed

**Cause:** rows written by database triggers have IDs of the form `act-log-{uuid}`, but the route
accepts only `act-` plus 32 hex characters.

**Fix:** read those rows from the feed or from a JSON export, which includes `metadata`.

### The activity `user_id` is the changed user, not the admin who changed it

**Cause:** triggers on `users` store the updated user in `user_id`; triggers do not know the
actor.

**Fix:** find the request at the same time in `GET /admin/audit/logs`, whose `user_id` is the
caller. See [Trace a permission or user-type change](scenarios.md#trace-a-permission-or-user-type-change).

### Security events are full of admin reads

**Cause:** any `/admin/` request by a root or admin user is flagged, including reading the audit
logs.

**Fix:** filter the `api_audit` events on `response_status` or `endpoint_path` on the client, or
use `GET /admin/audit/logs?security_event=true` with `endpoint_path` and `status_code` filters.

### Fewer security events than `limit`

**Cause:** each source reads `limit` rows, then `severity` is applied, then the merged list is cut
to `limit`. A severity filter can drop most rows. Activity events are only `warning` or
`critical`, so `severity=info` returns API audit events only.

**Fix:** query one source at a time with a higher `limit`. There is no `offset`.

### The user activity timeline stops at 100 entries

**Cause:** the timeline takes at most 50 rows from each log and has no paging. The activity counts
are based on the latest 500 activity rows.

**Fix:** use `GET /admin/activity` and `GET /admin/audit/logs` with `user_id` for full history.

### `GET /admin/email/logs` is empty

**Cause:** `status`, `purpose` and `provider` are exact matches, and unknown values return an
empty list instead of an error. There is no `days` window here, so age is not the cause.

**Fix:** run it without filters, then copy the exact values from a row.

### `has_more` is `true` but the next page is empty

**Cause:** email logs have no count query; `has_more` is `true` whenever the page was full.

**Fix:** stop when a page returns fewer rows than `limit`.

## Export

### `400` `VAL_3009` "Export would return N records"

**Cause:** more than `10,000` records match `filters`. The check ignores `limit`.

**Fix:** add filters until at most `10,000` match. Splitting by `days` does not work, because
`days` is always counted back from now; split by `project_id`, `user_id`, `http_method`,
`is_success`, `security_event` or `activity_type` instead. Check a count first with
`GET /admin/audit/logs?limit=1` and `pagination.total`.

### `400` `VAL_3001` "Invalid JSON body", or `VAL_3002`

**Cause:** the body is form data or malformed JSON (`VAL_3001`), or `source` or `format` is
missing (`VAL_3002`).

**Fix:** send `Content-Type: application/json` with both fields:

```bash
curl -X POST "http://localhost:8000/admin/audit/export" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"source": "api_audit", "format": "csv"}' \
  --output export.csv
```

### The CSV file is a single blank line

**Cause:** no records matched; the CSV writer then emits one empty row and no header.

**Fix:** widen the filters, or treat a one-line file as empty.

### The CSV lacks `metadata`, `session_id` or request bodies

**Cause:** the CSV has fixed columns. The JSON format returns every field.

**Fix:** export with `"format": "json"`, and handle the file as sensitive.

## Retention

### The tables keep growing

**Cause:** nothing deletes audit or activity rows. `sp_cleanup_old_activity_logs` exists but is
not scheduled, and `api_audit_log` has no cleanup procedure.

**Fix:** export on a schedule, then prune with your own job. For activity rows,
`CALL sp_cleanup_old_activity_logs(365, TRUE)` shows how many `info` rows a cleanup would delete.
