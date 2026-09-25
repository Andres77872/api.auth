# Audit logs scenarios

Workflows that combine several audit endpoints. Parameters and fields are in
[reference.md](reference.md); single calls are explained in [usage.md](usage.md). All examples use
a root or admin token in `$ADMIN_TOKEN`.

## Daily security review

1. Read the last day's critical events from both logs:

   ```bash
   curl "http://localhost:8000/admin/audit/security-events?severity=critical&days=1&limit=500" \
     -H "Authorization: Bearer $ADMIN_TOKEN"
   ```

2. Repeat with `severity=warning`.
3. Every `/admin/` request by a root or admin user is flagged too, so look past those and focus on:
   - repeated `403` responses from one `client_ip`;
   - `401` responses on `/auth/` paths from unfamiliar addresses;
   - `DELETE` requests you do not expect;
   - activity events such as `password_reset_consumed`, `admin_password_reset_requested`,
     `password_changed` and `email_message_complained` (all `critical`).
4. If `summary.total` equals `limit`, some events were cut. Query each source on its own with
   `source=api_audit` and `source=activity_log`.

## Investigate failed sign-ins

1. Find failed calls to the login route:

   ```bash
   curl "http://localhost:8000/admin/audit/logs?endpoint_path=/auth/login&is_success=false&days=7&limit=500" \
     -H "Authorization: Bearer $ADMIN_TOKEN"
   ```

2. Group the results by `client_ip` and look for many failures followed by a success.
3. Failed logins also write `user_login` activity rows with `"success": false` and the attempted
   username in `details` (the `user_id` is empty). Search for one username:

   ```bash
   curl "http://localhost:8000/admin/activity?activity_type_filter=user_login&search=alice&days=7" \
     -H "Authorization: Bearer $ADMIN_TOKEN"
   ```

`error_code` is empty on these audit rows, so use the status code, not the error code, to tell
failures apart.

## Investigate one user

1. Get the internal user ID (`usr-...`) from the users API; the audit filters do not accept the user
   hash.
2. Get a summary and a short timeline:

   ```bash
   curl "http://localhost:8000/admin/users/$USER_ID/activity?days=30" \
     -H "Authorization: Bearer $ADMIN_TOKEN"
   ```

3. Page through the full request history and activity:

   ```bash
   curl "http://localhost:8000/admin/audit/logs?user_id=$USER_ID&days=30&limit=1000" \
     -H "Authorization: Bearer $ADMIN_TOKEN"

   curl "http://localhost:8000/admin/activity?user_id=$USER_ID&days=30&limit=500" \
     -H "Authorization: Bearer $ADMIN_TOKEN"
   ```

4. Look for requests to projects the user should not reach, activity at unusual hours, and bursts
   of failures followed by successes.

## Trace a permission or user-type change

Changes to roles, permissions, groups, memberships and user types are written by database
triggers, so they appear in the feed even when no route logs them.

1. List the change type:

   ```bash
   curl "http://localhost:8000/admin/activity?activity_type_filter=user_type_changed&days=30" \
     -H "Authorization: Bearer $ADMIN_TOKEN"
   ```

   Other useful types: `permission_grant`, `permission_revoke`, `permission_group_assigned`,
   `permission_group_revoked`, `role_assigned`, `role_removed`, `user_group_assign`,
   `user_group_remove`, `user_status_change`, `user_deleted`.
2. Trigger rows record the changed record, not always the person who made the change. Take the
   `created_at` of the row and find the matching request. User types change through
   `PUT /user-types/{user_hash}/type` and `PATCH /users/{user_hash}/type`, so `/type` matches both:

   ```bash
   curl "http://localhost:8000/admin/audit/logs?endpoint_path=/type&days=30" \
     -H "Authorization: Bearer $ADMIN_TOKEN"
   ```

3. The audit row's `user_id` and `username` identify who sent the request.

## Audit API key activity

1. List key lifecycle events:

   ```bash
   curl "http://localhost:8000/admin/activity?activity_type_filter=api_key_revoked&days=90" \
     -H "Authorization: Bearer $ADMIN_TOKEN"
   ```

   Also `api_key_created`, `api_key_updated` and `api_key_reactivated`. The row's `metadata` holds
   `public_id` and, for revocations, `revoke_reason`; read it from a JSON export, because trigger
   rows cannot be fetched by ID and the CSV export has no `metadata` column.
2. Requests authenticated with `X-API-Key` are in the audit log with the key ID as `session_id`.
   Current key state is in [API keys](../api-keys/usage.md#list-one-projects-keys).

## Investigate an email that did not arrive

1. Find recent failures for the purpose:

   ```bash
   curl "http://localhost:8000/admin/email/logs?purpose=password_reset&status=dead&limit=100" \
     -H "Authorization: Bearer $ADMIN_TOKEN"

   curl "http://localhost:8000/admin/email/logs?status=bounced&limit=100" \
     -H "Authorization: Bearer $ADMIN_TOKEN"
   ```

2. Match the recipient by `recipient_masked` and `recipient_hash`; the plaintext address is never
   returned.
3. Read the row: `last_error_code`, `attempt_count` against `max_attempts` (`dead` means retries
   ran out), `suppressed` (the address is on the suppression list), `provider_message_id` for the
   provider's dashboard.
4. Cross-check the webhook events (only sent, delivered, bounced and complained are logged):

   ```bash
   curl "http://localhost:8000/admin/activity?activity_type_filter=email_message_bounced&days=7" \
     -H "Authorization: Bearer $ADMIN_TOKEN"
   ```

5. Fixes are in [Email troubleshooting](../email/troubleshooting.md).

## Monthly compliance export

1. Check the size first; `pagination.total` must be at most `10,000`:

   ```bash
   curl "http://localhost:8000/admin/audit/logs?days=30&limit=1" \
     -H "Authorization: Bearer $ADMIN_TOKEN"
   ```

2. Export each source:

   ```bash
   curl -X POST "http://localhost:8000/admin/audit/export" \
     -H "Authorization: Bearer $ADMIN_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"source": "api_audit", "format": "csv", "limit": 10000, "filters": {"days": 30}}' \
     --output api_audit_30d.csv

   curl -X POST "http://localhost:8000/admin/audit/export" \
     -H "Authorization: Bearer $ADMIN_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"source": "activity", "format": "csv", "limit": 10000, "filters": {"days": 30}}' \
     --output activity_30d.csv
   ```

3. If more than `10,000` records match, split the export by a filter, not by date: `days` is a
   lookback from now, so two exports with `days: 7` return the same week. Useful splits are
   `project_id`, `user_id`, `http_method`, `is_success` and `security_event` (API audit) or
   `activity_type` (activity).
4. Because nothing deletes old records, run the export on a schedule and keep the files; a
   `365`-day lookback is the longest window the API offers.

## Find slow or failing endpoints

1. Get traffic statistics:

   ```bash
   curl "http://localhost:8000/admin/audit/statistics?days=30" \
     -H "Authorization: Bearer $ADMIN_TOKEN"
   ```

2. In `top_endpoints`, compare `avg_duration_ms` and `failure_count`.
3. Drill into one endpoint and read `duration_ms` per request:

   ```bash
   curl "http://localhost:8000/admin/audit/logs?endpoint_path=/admin/dashboard&days=7&limit=100" \
     -H "Authorization: Bearer $ADMIN_TOKEN"
   ```

4. List server errors with `status_code=500`.
