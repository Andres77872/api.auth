# 08 — Risk Register

Likelihood and impact are the reviewer's qualitative estimates (L / M / H). "Phase" refers to [07-migration-plan.md](07-migration-plan.md). Risks are ordered by severity within each group.

## A. Risks introduced by the change

| ID | Risk | L | I | Mitigation | Phase |
| --- | --- | --- | --- | --- | --- |
| R-01 | **Orphaning every existing Google link.** Any change to the subject pepper value, the HMAC input (for example prefixing the namespace into the hashed string), the hash function, or the lookup key shape makes `sp_get_user_by_external_account` miss. With auto-create on, each returning user silently gets a **new empty account**; with it off, everyone is locked out. | M | H | Namespace is a separate column, never part of the HMAC input. New pepper variable names must fall back to the old names and a start-up check must fail if both are set with different values. Golden-digest test introduced in Phase 1 and never edited. Rehearse on a production snapshot. | 1, 3 |
| R-02 | **Cross-tenant privilege escalation through caller-asserted scope.** Once a second backend exists, a caller that can assert `project_hash` and `user_group_hash` can provision users into another project or into a privileged group (findings F-26, F-27). | M (as soon as there are two tenants) | H | Derive the project from the authenticated credential; take the group from the binding row validated against the project; enforce equality in the legacy bridge; move the policy check into the create procedure. Do **not** onboard a second backend before Phase 4. | 4 |
| R-03 | **Mix-up / malicious IdP.** A tenant-configured generic OIDC connection is an attacker-controlled authorization server sharing a callback with honest ones. | L–M | H | Connection chosen only from the state record; per-connection issuer pin; RFC 9207 `iss` check; ID-token issuer compared to the connection, not to a global list; generic `oidc` type root-only until reviewed. | 2, 5, 7 |
| R-04 | **SSRF through administrator-supplied URLs** (discovery, JWKS, token, userinfo, legacy redeem). | M | H | HTTPS only; block private, loopback, link-local and cloud-metadata ranges after DNS resolution; no redirects; timeouts and size caps; built-in provider types ignore tenant endpoints. The inverted init handshake removes the redeem URL entirely. | 3, 4 |
| R-05 | **Secret leakage** through logs, audit rows, error details, admin responses, exception messages or database dumps. | M | H | Write-only APIs; fingerprints only; extend redaction name lists and leak-assertion fixtures; `repr`-suppressed secret objects; static test forbidding plaintext secret columns; encrypted at rest with a key that is not in the database. | 3 |
| R-06 | **Loss of the encryption key** makes every connection unusable at once. | L | H | Key id + decrypt map; documented rotation and escrow in a runbook; readiness endpoint reports undecryptable credentials distinctly; secrets can always be re-entered from the IdP console, so this is an outage, not data loss. | 3 |
| R-07 | **Identity forking with pairwise-subject providers.** Configuring Microsoft per project with `sub`, or Apple under two developer teams, makes one person two users; the reverse (namespace too coarse) merges two people. | M | H | Namespace computed by the adapter from immutable connection attributes; `oid` + `tid` for Microsoft; namespace immutability trigger; admin UI warns when two connections of one type have different namespaces. | 5 |
| R-08 | **Regression in a security-critical path during refactor.** The route module is about 1,500 lines with many implicit behaviours that tests depend on through roughly forty patch targets. | H | M–H | Phases 0–2 are behaviour-preserving with golden tests; move code rather than rewrite; keep compatibility names for patch targets for one release; run the end-to-end Magic Worlds flow on every phase. | 0–2 |
| R-09 | **Non-additive schema change** (ENUM → VARCHAR with dependent generated columns and unique indexes) fails midway or locks the table. | M | M | Defer it: widen the ENUM additively first; do the conversion as an isolated change with a rehearsed script and a maintenance window; the table is small. | 6 |
| R-10 | **Stale configuration cache** keeps serving a disabled or rotated connection. | M | M | Short TTL; explicit invalidation on admin write; the callback re-resolves the connection after consuming state; secrets are never cached. In a multi-instance deployment, invalidation must go through Redis pub/sub or rely on the TTL alone — decide explicitly. | 3 |
| R-11 | **Global-user model surprises tenants.** The same Google account is the same `api.auth` user in every project. With `existing_user_policy=join_default_group`, signing in at project B silently grants B access to an account created at A; account deletion or suspension at one project affects the other. | M | M | Default `deny`; document clearly; treat "identity scope per project" as an open product decision ([09-open-questions.md](09-open-questions.md)). | 4 |
| R-12 | **Rate-limit starvation between tenants** when buckets are shared or keyed by a BFF egress address. | M | M | Project and connection dimensions in bucket keys; per-binding overrides that can only lower deployment ceilings; trusted-proxy handling. | 2, 4 |
| R-13 | **Operator error multiplies.** Three places must agree byte-for-byte on a redirect URI (IdP console, binding row, consumer). Today that is one environment variable; tomorrow it is N rows maintained by different people. | H | L–M | Readiness endpoint that names the failing layer; "test connection" probe; the providers listing returns exactly what a consumer needs; onboarding checklist in [10-consumer-guide.md](10-consumer-guide.md). | 3 |
| R-14 | **Consumer and server release skew.** `magic_auth_client` hardcodes the Google endpoints; Magic Worlds pins a client version. | M | M | Aliases stay until Phase 6; the legacy redeem bridge stays until Magic Worlds has shipped the init-API client; version the client library with both method families for one release. | 2–6 |
| R-15 | **Apple-specific operational debt**: the signing key must be stored encrypted, the generated client secret expires, POST callbacks bypass assumptions in middleware that treats the callback as a GET. | M | L–M | Generate the client-secret JWT per exchange (no stored expiry to forget); accept POST explicitly on the callback only; CSRF exemptions reviewed for that one route. | 5 |
| R-16 | **Scope creep into a full identity provider.** Hosted callback, self-service IdP configuration and enterprise SSO are each substantial products. | M | M | Keep them in Phase 7, explicitly optional; do not let the state-record and route design exclude them, and do not build them early. | 7 |
| R-17 | **Configuration becomes unmanageable while the dashboard lags the backend.** After Phase 3 the source of truth is database rows; without the admin UI every change is a hand-written API call or raw SQL, which is more error-prone than the environment file it replaced. | M | M | The bootstrap import and admin API ship usable without a UI, but the dashboard work should follow immediately; see [11-admin-dashboard.md](11-admin-dashboard.md). Keep the readiness endpoint in the first backend release so misconfiguration is at least diagnosable. | 3 |
| R-18 | **Secret leakage through the admin client** — a secret rendered, retained in component state, logged, or sent form-encoded. | M | H | Write-only by construction (the server cannot return the value); JSON bodies for credentials; root-gated render branch; inputs cleared on success; tests asserting no secret is ever rendered. | 3 |

## B. Pre-existing risks the change should retire

| ID | Risk today | L | I | Retired by |
| --- | --- | --- | --- | --- |
| R-20 | Test-runtime branches in the production callback accept forged state, codes and ID tokens when a pytest environment variable is present (gap G-03). | L | H | Phase 0 — fakes move to fixtures and a fake adapter. |
| R-21 | Users cannot link or re-authenticate (gaps G-01, G-02); with auto-create on, returning password users get duplicate accounts (gap G-14). | H | M | Phase 0. |
| R-22 | Single static redeem bearer with no rotation; compromise lets an attacker mint bindings for any project and any group. | L | H | Phase 4 (equality check), Phase 6 (bridge removed). |
| R-23 | Unconditional trust in `X-Forwarded-For` weakens every per-IP limit. | M | M | Phase 4. |
| R-24 | Two blocking network fetches per callback inside the event loop (gaps G-05, G-06). | H | L–M | Phase 0 (cache), Phase 1 (async adapter I/O). |
| R-25 | Operators cannot diagnose provisioning denials because `sub_reason` is dropped (gap G-04). | H | L | Phase 0. |

## C. Risks of not doing this

| ID | Risk |
| --- | --- |
| R-30 | A second project can only be onboarded by standing up a second `api.auth` deployment (separate environment), which forks the user base the multi-project model exists to unify — or by routing the second project through the Magic Worlds backend. |
| R-31 | Every additional provider would be another ~1,500-line copy of the Google router, each inheriting the Part A defects in [03-gaps.md](03-gaps.md). |
| R-32 | Client credentials remain in environment files on disk, outside the audited, encrypted, rotatable path already built for billing secrets. |

## D. Top five to watch

1. **R-01** — do not touch the subject hash. Prove it with a golden test before anything else.
2. **R-02** — do not onboard a second backend until project and group stop being caller-asserted.
3. **R-08** — refactor in behaviour-preserving steps; the tests patch internals heavily.
4. **R-04 / R-03** — every tenant-supplied URL is an attack surface; keep generic OIDC root-only at first.
5. **R-05** — a new class of secret is entering the database; extend the leak assertions before the first secret is stored.
