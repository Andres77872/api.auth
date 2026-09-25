# 09 — Open Questions and Decisions Needed

Each item states the decision, the options, and the reviewer's recommendation. None of these block Phases 0–2 of [07-migration-plan.md](07-migration-plan.md); items 1–4 must be settled before Phase 3.

## 1. Is identity global or per project?

`api.auth` users are global: one row in `users`, access to projects through groups. With per-project OAuth, the same Google account at two projects resolves to the same user.

| Option | Behaviour | Consequence |
| --- | --- | --- |
| **Global (recommended)** | One person, one user, many projects | Matches the existing model, single sign-on across a company's projects, one place to suspend a user. Requires the `existing_user_policy` setting. Unsuitable if unrelated organisations share one deployment. |
| Per project | Namespace includes the project, so each project sees a separate user | Strong tenant isolation; no cross-project account linkage; but duplicates users and breaks the "accessible projects" concept for OAuth users. |
| Per connection setting | Administrator chooses | Most flexible; most ways to misconfigure; harder to reason about. |

Deciding question: *will unrelated organisations ever share one `api.auth` deployment?* If no, choose global.

## 2. May a connection be shared between projects?

| Option | Notes |
| --- | --- |
| **Shareable, with an owner (recommended)** | Matches billing groups; one consent screen for a company's apps; per-project policy still separate. |
| Strictly one connection per project | Simpler mental model and authorisation; forces duplicate Google Cloud clients and duplicate secrets. |

## 3. Who may submit client secrets?

| Option | Notes |
| --- | --- |
| **Root only at first (recommended)** | Copies the billing precedent; smallest blast radius while the feature is new. |
| Project administrators for connections their project owns | Needed for real self-service; requires careful scoping and should exclude the generic `oidc` type (SSRF and mix-up surface). |

## 4. ENUM or VARCHAR for the provider column?

Widening the ENUM is additive and supported by the existing sync tooling; VARCHAR with a catalog foreign key is cleaner but is the repository's first non-additive migration. Recommendation: widen first, convert later as an isolated change (details in [06-data-model.md](06-data-model.md)).

## 5. Which init handshake?

Recommendation: inverted init API authenticated by project-scoped API key, with the legacy redeem callback kept only as a bridge (analysis in [04-research.md](04-research.md)). Sub-question: reuse `user_project_api_keys` (keys belong to a *user* and inherit that user's live permissions) or introduce a dedicated **project client credential** not tied to a person. A service credential is the cleaner long-term answer — a login flow should not stop working because an employee's account was deactivated — but reusing API keys is faster. Suggested: reuse API keys now, require a dedicated permission (`oauth_init`) on the key's owner, revisit later.

## 6. Hosted callback: now, later, or never?

Needed for any project without its own backend. Recommendation: later (Phase 7), but keep `delivery_mode` in the state record and binding from the start so it remains additive.

## 7. What should happen on an e-mail collision?

Today: nothing detects it (gap G-14). Options: (a) deny auto-create and tell the consumer to offer "sign in with your password, then link" — safest, needs the link flow fixed; (b) create the second account (current accidental behaviour); (c) link automatically when the provider e-mail is verified **and** the local e-mail is activated — convenient, but it is exactly the pattern behind the nOAuth class of takeovers when the provider's e-mail is administrator-controlled. Recommendation: (a), per binding, never (c) for provider types whose e-mail trust is not `verified_by_provider`.

## 8. Should Patreon move under the same abstraction?

Patreon is not an OAuth login flow here (no authorize/callback; creator token plus e-mail proof), and its router deliberately forbids login routes. Recommendation: leave it alone. Give it a catalog row with `login_enabled = FALSE` purely so that the external-accounts foreign key covers its rows. Do not try to make the login adapter Protocol fit it.

## 9. Which second provider?

Recommendation: GitHub first (cheapest proof that the non-OIDC path works), Microsoft second (proves namespace and issuer handling), Apple third. Confirm against actual product demand.

## 10. Are provider tokens ever needed after login?

The present design discards them, which is a strong privacy and security property. If a future feature needs to call a provider API on the user's behalf (calendar, repositories, guild membership), that is a **separate capability** with its own encrypted token store, consent, refresh and revocation handling — not an extension of the login adapter. Confirm that login-only is the scope.

## 11. Cache invalidation across instances

How many `api.auth` instances run in production? With one, in-process invalidation is enough. With several, choose between a short TTL only (simple, up to a minute of staleness after disabling a connection) and Redis pub/sub invalidation (immediate, more moving parts). The callback's re-resolve step bounds the damage either way.

## 12. Naming

`connection` is used throughout these documents for a configured client at a provider (the Auth0 term). Alternatives: `identity_provider` (Keycloak), `provider_config`. Pick one before the schema lands; renaming tables later is expensive in a stored-procedure-heavy code base.

## 13. Database name

Every SQL file begins with `USE magic_auth;`. Out of scope for the OAuth work, but if "agnostic to Magic Worlds" is a goal for the whole service, the database name should become a deployment parameter at some point.
