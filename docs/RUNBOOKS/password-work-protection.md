# Public password work protection

The four public password routes (`/auth/login`, `/auth/platform/login`,
`/auth/password/reset`, `/auth/register`) share one global and one client-IP Redis
budget. Atomic admission precedes database work and identifier-specific counters.
Accepted attempts count regardless of their eventual credential outcome. Rejected
attempts do not create extra IP buckets or extend their expiry.

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `AUTH_PASSWORD_WORK_GLOBAL_LIMIT` | `60` | Accepted attempts across all four routes and all replicas per window |
| `AUTH_PASSWORD_WORK_IP_LIMIT` | `20` | Accepted attempts per normalized client IP per window |
| `AUTH_PASSWORD_WORK_WINDOW_SECONDS` | `60` | Fixed-window lifetime |
| `AUTH_PASSWORD_WORK_CONCURRENCY` | `1` | Simultaneous password jobs per API process; no waiting queue |
| `FORWARDED_ALLOW_IPS` | empty | Explicit proxy IP addresses/CIDRs trusted by Uvicorn |

All password-work settings must be positive integers. Every replica must use the
same Redis and budget configuration. Existing account and email-link buckets remain
active. Redis failures and worker saturation return `429 INT_7005` with
`Retry-After: 1`; exhausted rate budgets use the remaining bucket expiry.

## Proxy boundary

Set `FORWARDED_ALLOW_IPS` to only the actual ingress addresses/networks. Wildcards
and all-address networks are rejected. An empty value trusts no forwarding data.
The ingress must replace untrusted incoming `X-Forwarded-For`, `X-Real-IP`, and
`X-Forwarded-Proto` values, supplying the observed client address and external
scheme. Keep API access behind that ingress. The auth limiter reads only the
server-normalized client address; request headers cannot independently override it.

The Docker entrypoint validates configuration before launching sibling processes
and passes explicit proxy flags to Uvicorn. For other launchers, export the value
before starting the server (Uvicorn parses it before the app imports `.env`):

```bash
python -m src.Util.proxy_config
python -m uvicorn src.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-}"
```

## Upgrade and validation

1. Apply `schemas/migrations/20261012_password_reset_prevalidation.sql` to the
   selected auth database before deploying the API. It only adds the read-only
   proof procedure. Use a database migration administrator with routine-management
   privileges; replacing a system-user-defined routine also requires `SYSTEM_USER`.
   Existing recovery
   links, tables, and the atomic consumer remain unchanged. Fresh databases install
   the procedure from the canonical email procedure file.
2. Configure ingress trust and sanitization. Verify HTTPS scheme handling and
   trusted/untrusted forwarding chains in staging.
3. Deploy the API with the conservative defaults. Verify sign-in, registration,
   both recovery-link purposes, and `429` handling with browser clients.
4. Monitor `password_work_rejected` by bucket, `password_work_completed` duration
   and active-job count, CPU, memory, and `/system/ping` latency. Logging includes no
   credentials, recovery-link material, identifiers, or IP values. Tune capacity
   using measured CPU/memory headroom; Argon2 uses approximately 64 MiB per active
   job plus runtime overhead. Total capacity scales with the API process count.

Proof validation precedes hashing and has no side effects. The atomic consumer
still rechecks current user/link state under locks, so revocation, concurrent use,
or password changes between prevalidation and consumption cannot authorize a stale
password update. Missing/unavailable proof procedures skip hashing and return the
neutral public response, so installing the migration before the API is essential.

Keep the additive procedure during application rollback. If reverting the resource
guards is unavoidable, temporarily block the four public password routes at ingress
until equivalent protection is restored.

Client payloads remain compatible. Apps must honor `429` and `Retry-After`, retain
the recovery link credential for a delayed retry, and avoid refresh/retry loops.
The API exposes the header through CORS; BFFs must relay it.
