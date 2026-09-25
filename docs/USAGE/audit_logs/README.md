# Audit logs

Root and admin users read what happened in the service from three stores: a per-request HTTP
audit trail, a semantic activity log, and the transactional email ledger. The endpoints list,
filter, summarize and export these records for security reviews, investigations and compliance.

## Data sources

| Store | Written by | One row per | Read through |
| --- | --- | --- | --- |
| `api_audit_log` | `APIAuditMiddleware` (`src/middleware/api_audit.py`) on every request except excluded paths | HTTP request | `/admin/audit/*`, `/admin/users/{user_id}/activity`, export source `api_audit` |
| `activity_logs` | The `@log_and_handle_errors` decorator, explicit `ActivityLogger` calls in services, and database triggers on users, projects, groups, roles, permissions, sessions and API keys | Business event, such as `user_update` or `api_key_revoked` | `/admin/activity*`, security events, `/admin/users/{user_id}/activity`, export source `activity` |
| `email_messages` | The email enqueue path; updated by the outbox worker and provider webhooks | Transactional email | `GET /admin/email/logs` |

The runtime `ActivityType` enum has 112 members; triggers also write types outside it (for
example `api_key_created`, `role_assigned`). See [reference.md](reference.md#activity-types).

## Route families

| Family | Source file | Routes |
| --- | --- | --- |
| Audit | `src/routes/audit_logs.py` | `GET /admin/audit/logs`, `GET /admin/audit/security-events`, `GET /admin/audit/statistics`, `POST /admin/audit/export`, `GET /admin/users/{user_id}/activity`, `GET /admin/email/logs` |
| Activity feed | `src/routes/admin_dashboard.py` | `GET /admin/activity`, `GET /admin/activity/types`, `GET /admin/activity/{activity_id}` |

## Rules and caveats

Platform-wide rules are in [Platform-wide contracts](../README.md#platform-wide-contracts). These
apply to this suite:

- **Root and admin user types only.** Every route checks the caller's user type. An `admin`
  permission from a global role does not grant access; other callers get `403` `AUTHZ_2001`.
- **No project scoping.** An admin sees every project's records, not only the projects they
  administer.
- **Filters take internal IDs.** `user_id` and `project_id` are internal IDs (`usr-...`), not user
  or project hashes.
- **A lookback window always applies.** `days` defaults to `30` (`7` for statistics) and accepts
  `1`–`365`. There is no start/end range.
- **Export takes a JSON body** and refuses any request whose filters match more than `10,000`
  records.
- **Nothing is deleted automatically.** `sp_cleanup_old_activity_logs` exists but nothing calls it,
  and `api_audit_log` has no cleanup procedure.
- **Audit reads are audit events.** Any `/admin/` request by a root or admin user is stored with
  `security_event = true`, so reviewing logs adds security events.
- **`error_code` and `error_message` are usually empty.** The middleware cannot read the body of a
  handled error response; these columns are filled only when an unhandled exception escapes.

> [!NOTE]
> `api_audit_log.session_id` holds the access token's `session_id` claim or the API key ID, never
> token bytes. Rows written before this change stored the first 256 characters of the access token.
> Reads and exports mask those values, but the database still holds them until the optional cleanup
> in [reference.md](reference.md#existing-rows-with-token-prefixes) is run. Audit output still
> contains personal data such as IPs and user agents, so treat it as sensitive.

## In this suite

| Document | Purpose |
| --- | --- |
| [usage.md](usage.md) | One task per section: feed, audit logs, security events, statistics, user activity, email logs, export |
| [scenarios.md](scenarios.md) | Workflows: daily review, sign-in failures, user and change investigations, email failures, compliance export |
| [reference.md](reference.md) | Endpoint and parameter tables, response fields, export contract, activity catalog, error codes |
| [request-flow.md](request-flow.md) | How a request is captured and how each read endpoint builds its answer |
| [architecture.md](architecture.md) | Tables, writers, security-event rules, redaction and design limits |
| [stored-procedures.md](stored-procedures.md) | The SQL procedures behind the audit and activity stores |
| [troubleshooting.md](troubleshooting.md) | Symptom, cause and fix |

## Related

- [Admin usage cases](../admin-usage-cases.md) — dashboard and system health
- [Email](../email/README.md) — the outbox and webhook behind `email_messages`
- [API keys](../api-keys/README.md) — the `api_key_*` activity rows
- [Errors](../errors.md) — error envelope and codes
