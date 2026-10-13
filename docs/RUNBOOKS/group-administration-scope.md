# Group administration scope rollout

Group administration now requires a live root/admin identity. Root manages every group; admins
manage groups only when their complete administrative project set is assigned to them. Consumer
`admin`, `manage_users`, and `manage_roles` permission names do not authorize these routes.

## Client migration

Update clients that call `/admin/user-groups`, `/admin/project-groups`, or
`/admin/user-groups/bulk-assign`. Ordinary login, refresh, OAuth, validation, and invitation
registration contracts are unchanged. The inspected `magic_auth_client` consumer methods and
`api.magic_llm` / `magic-worlds-api` integrations do not call these management routes. A literal-path
search of the local PycharmProjects application source found these paths only in api.auth; inventory
clients that construct URLs dynamically or live outside that workspace before rollout.

For non-root creation, send the selected assigned project's hash:

```bash
curl -X POST "$AUTH_BASE/admin/user-groups" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "User-Agent: admin-console" \
  --data-urlencode "group_name=team" \
  --data-urlencode "project_hash=$PROJECT_HASH"
```

Use the same new form field on `POST /admin/project-groups`. The group is still empty: follow
with the existing project assignment, grant, and membership requests. Root can omit the field.
Root may also send `project_hash` alone on either group's PUT endpoint to bind/rebind a legacy
empty group. Other callers cannot change its administrative binding.

Use scoped list results; refresh old cached group selections. Treat `403` as a permission denial,
not a reason to refresh tokens. A bulk authorization denial returns `403` with zero assignments;
missing users and ordinary item errors retain partial-result handling after authorization.
Move consumer-based management workflows to dedicated admins assigned to the required projects.
Shared groups need an admin assigned to every associated project, or root. Changes to reserved
administrator assignments—including through project groups—require root.

## Database migration and deployment

1. Inventory management clients, delegated consumers, existing multi-project groups, and empty
   groups. Release the new creation field to management clients first; verify that the old API
   accepts it as an additional form field.
2. Use a database administrator account authorized to ALTER tables and create triggers under the
   deployment's binary-logging policy. The application account does not need elevated DDL privileges.
   Back up the database and pause **all graph writers**, including registration, OAuth
   provisioning, project bootstrap, and maintenance workers. MySQL DDL commits implicitly.
3. Run the read-only inventory against the intended database:

   ```bash
   python scripts/migrations/group_scope_upgrade.py --env-file /path/to/deployment.env --expected-host 192.168.1.90
   ```

4. Apply the additive migration while writers remain paused:

   ```bash
   python scripts/migrations/group_scope_upgrade.py --env-file /path/to/deployment.env \
     --expected-host 192.168.1.90 --apply --processes-stopped \
     --backup-dir /secure/path/new-group-scope-backup
   ```

   It adds nullable indexed foreign keys on both group tables, initializes the graph coordination
   row, installs 19 locking triggers, and binds previously unbound groups that have exactly one
   associated project. Existing bindings are preserved. Empty and multi-project groups remain
   unbound; an unbound nonempty group is manageable only within its full project scope.
   No memberships, grants, or project assignments are removed. Interrupted runs can be reapplied.
   The CLI requires the expected host, explicit downtime, and a new private backup directory.
   It saves affected table data, original table/trigger definitions, the source hash, and before/after
   reports. Verification compares every access relationship and unchanged group field, including
   existing bindings; it also verifies the deployed trigger bodies, index columns, and foreign-key
   targets. Existing timestamp triggers may update `updated_at` on newly bound groups; no other
   group metadata change is allowed. Protect these backups because they contain group identifiers.
5. Deploy the hardened API, verify the migration report shows 19 triggers, then resume writers.
   Smoke-test root management, admin creation in A, A-to-B denials, bulk preflight, normal login,
   and invitation registration. Watch management-route `403`/`400` rates for old client workflows.

Graph writes serialize on one InnoDB coordination row until commit, including direct SQL. This
trades group-write throughput for a consistent authorization snapshot. Read operations remain
independent. Monitor lock waits and mutation latency; denied or failed transactions release the lock.

Canonical fresh installations include the scope columns and coordination table. Docker test
initialization installs the locking triggers. Existing installations must use the migration;
schema catch-up alone does not perform binding backfill or constraint verification.

## Existing grants and rollback

This prevents future unauthorized grants. It does not decide whether existing cross-project
sharing was legitimate. Root must review existing links and remove confirmed bad grants through
the supported routes. Those removals revoke lost sessions and invalidate affected API-key caches.
Do not automatically remove all shared groups or sign out all users during deployment.

On migration/deployment failure, keep writers paused, repair and reapply, and verify the report
before resuming. Retain the additive schema and hardened authorization; restoring a permissive
API would restore the vulnerability. Keep existing access data for review instead of deleting it.

## Migration completed on 192.168.1.90

On 2026-10-13 at 19:27 UTC, the migration was applied to `magic_auth` on `nillison`
(MySQL 8.1.0) after the operator confirmed all graph writers were stopped. Both scope columns,
indexes, foreign keys, and all 19 coordination triggers were installed and verified.
Six of 16 user groups and two of five project groups received a binding. Ten user groups and
three project groups remain unbound under the empty/multi-project policy.

Every existing row in the access tables was compared with the private backup: 50 user
memberships, seven project assignments (six active), and 18 user-group grants were preserved.
Existing bindings and unrelated trigger definitions were also preserved. A rolled-back direct
writer smoke check confirmed serialization on the coordination row and left no persistent changes.
Read-only checks through the production connection pool confirmed root visibility and consumer
denial. There were no active admin accounts available for a live assigned-admin check; isolated
HTTP/MySQL tests cover assigned admins, foreign-project denials, and shared groups.

Backups and verification reports are retained in the ignored, private directory
`.migration-backups/group-scope-192.168.1.90-20261013T192723Z/`. These are affected-table and
trigger backups, not a dump of unrelated database tables. Disposable test containers, their network,
and their database volume were removed. Existing access and user identities were not cleaned up.

The refactor passed 120 scope/migration checks and 138 authentication/access regressions.
The unrelated documentation test for repository-file references remains excluded because it
already fails on the original revision. API code deployment, restart, and HTTP smoke checks on
192.168.1.90 remain release steps; the database migration alone does not enforce route authorization.
