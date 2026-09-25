# Assistant integration: project review

Reviewed on 2026-09-24 against the current working tree. This review concentrates on administration routes, authorization, stored-procedure contracts, read/write classification, and the boundaries needed to let a root assistant operate safely. It does not claim a full production penetration test or live provider/database validation.

## Implemented boundaries and coverage

The explicit registry in `src/assistant/catalog.py` exposes 203 executable operations across ten skills: 96 read operations enabled by default and 107 mutations disabled by default. It derives request schemas from existing FastAPI routes and invokes those routes through an in-process ASGI client, retaining request validation, authentication, scope checks, recent-reauth requirements and application audit behavior. Adding an unrelated route cannot automatically expose it to the assistant.

Operations are grouped into users, groups, projects, security, audit, analytics, billing, Patreon, transactional email and system operations. Public login/refresh/OAuth callbacks, service-to-service endpoints, webhooks, arbitrary HTTP, SQL, shell and host filesystem access are deliberately outside the tool catalog. Application account creation, API-key administration, OAuth administration, billing, bulk operations and cache maintenance use their existing guarded application operations.

Every invocation independently verifies the current authenticated identity is still a root user in the database and reads current feature/skill/tool configuration. Mutation enablement requires both the master switch and the exact tool. Credentials are redacted before results enter model context or assistant event logs. Tool arguments, paths and result size are bounded; pagination is capped at 100 rows per call. The runtime additionally controls skill loading and approvals.

## Findings fixed in this change

### P1: dynamic identifiers must not reach a different configured tool

Evidence: the application registers static `/users/api-keys` before `/users/{user_hash}`. Substituting `api-keys` into the user-detail tool could otherwise invoke the separately configured security operation, bypassing individual tool/skill disablement.

Fix: the executor checks FastAPI's actual route resolution and requires it to match the registered operation template before invoking ASGI. A regression test disables the API-key tool, tries the shadowing identifier, verifies rejection without invocation, and verifies an ordinary user lookup still succeeds.

### P1: a Patreon GET performs application writes

Evidence: `src/routes/admin_patreon.py` calls `ensure_patreon_catalog_safely` before listing the tier map. Treating every GET as safe would permit configuration synchronization while the assistant's mutation switch is off.

Fix: the endpoint now accepts a backwards-compatible `refresh_catalog` flag. `admin_patreon__read_tier_map` pins it to false and does not expose the flag as a model argument. The existing refresh-and-list operation pins it to true and is classified as a mutation. The executor refuses an attempt to override the read variant's flag. Existing dashboard requests retain their prior refresh behavior.

Validation: direct real-handler tests prove the read variant does not call synchronization; ASGI tests prove the tool cannot promote the read to a write.

### P2: project-group updates pass the wrong stored-procedure arity

Evidence: canonical `schemas/stored_procedures/04_project_groups.sql` declares three parameters. The previous `update_project_group` wrapper passed a fourth serialized permissions argument, so normal rename/description updates failed against the canonical database.

Fix: `src/Util/db/db_project_groups.py` passes the three declared parameters. The legacy permissions argument is retained for compatibility but rejects a nonempty permission list: project groups are containers and do not own permissions. This avoids silently accepting a permission change that cannot be persisted.

Validation: cursor-boundary test checks the exact procedure name/arguments, commits and returned record; a separate test rejects unsupported permission assignment. Existing project-group integration tests pass.

### P2: project statistics parse unrelated result sets as counts

Evidence: `schemas/stored_procedures/03_projects.sql` returns project metadata, one aggregate access row, then group distribution. The previous Python wrapper interpreted the first project ID as the user count, the access user count as active sessions, and the first group name as a group count.

Fix: `src/Util/db/db_projects.py` reads the canonical result-set order, drains remaining results, returns numeric access/group counts and preserves the distribution. `active_sessions` is null because the procedure does not measure sessions; it is no longer fabricated from a different count. Route documentation now describes this behavior.

Validation: canonical three-result-set cursor tests verify distinct values for all counts, missing session measurement, empty distributions and zero counts. Existing project CRUD and administrative-scope integration tests pass.

### P2: the shared root helper is broader than this feature's root-only requirement

Evidence: `src/middleware/authentication.py` accepts `global_admin` permission even when `user_type` is not root. This is an existing application compatibility rule; this review does not assert an exploitable privilege escalation in the existing role-assignment rules.

Mitigation: the new assistant does not rely on that helper for its root-only boundary. `src/assistant/tools.py` requires the expected session owner, exact session root type and a fresh database root type. Transport authorization has the same strict requirement. Tests reject a demoted root and a different session owner.

## Remaining application limitations

### P2: ownership transfer and archive/unarchive are unimplemented routes

Evidence: `src/routes/projects.py` and `src/routes/projects.py` always raise `FEATURE_NOT_IMPLEMENTED` after validation. Exposing them as working tools would misrepresent application capabilities.

Disposition: both are explicitly recorded in `UNAVAILABLE_OPERATIONS` and omitted from the executable assistant registry. The projects skill explains the limitation and forbids replacing archive with deletion. Existing application behavior is preserved.

Follow-up: ownership transfer needs a persisted backend operation and a defined effect on administrative assignment. Archive/unarchive has stored procedures, but enabling the API also needs a deliberate session/API-key/cache invalidation policy and tests for restoring administrative access. `src/Util/cache_manager.py` currently clears project access/permission/role keys, not full-session or API-key caches. These changes were not approximated by a new unchecked assistant-only database path.

### P2: filtered user-list totals do not represent the filtered results

Evidence: `src/routes/users.py` applies search, group and project filters to the listing, while `src/Util/db/db_users.py` only forwards user type and include-inactive to `sp_count_users`; it ignores the supplied search argument. Administrative scoping is also applied after pagination in `src/routes/users.py`.

Impact: a filtered root query can report an unrelated pagination total, and scoped administrator pages can be sparse. The assistant tool description and users skill warn against treating that total as the count of matching users.

Follow-up: add a count query using the same predicates/access scope as the list query, and apply scope before pagination. Verify group/project/search combinations with real database fixtures.

### P2: project access counts are membership counts, not a count of active eligible accounts

Evidence: `schemas/stored_procedures/03_projects.sql` counts active membership rows without joining `users.is_active`; the aggregate also does not filter inactive parent groups in the same way as effective-access queries.

Impact: even with the Python result-set bug fixed, these statistics must not be used as an authorization decision or described as the exact number of currently eligible active users. The assistant uses actual membership/permission tools to inspect access.

Follow-up: align the statistics query with the canonical effective-access view, preserving a separately named membership metric if needed. This requires a database migration and deployment validation.

## Verification and limits

Focused verification passed 94 tests:

```sh
.venv/bin/python -m pytest \
  tests/unit/test_assistant_tools.py \
  tests/unit/test_assistant_project_review.py \
  tests/unit/test_admin_patreon_admin_endpoints.py \
  tests/integration/test_slice11_admin_project_groups.py \
  tests/integration/test_admin_scope_projects.py \
  tests/integration/test_slice9_project_crud.py -q --disable-warnings
```

Tests verify registration against the real management routers, self-contained request schemas, actual ASGI calls to selected real read routes, form/JSON request handling, live policy changes, safe path construction, session revocation, secret redaction and the database contract corrections. Database and provider side effects are mocked in these focused tests. The wider runtime, persistence, transport, client and deployment validation is tracked separately by the integration work.
