# Agnostic OAuth — Review, Research and Plan

Documents 01 to 11 are the research deliverable, written before any code changed. Document 12 records the implementation that followed. They review how Google OAuth works in `api.auth` today, establish how far it is tied to a single provider, a single OAuth client and a single consuming project (Magic Worlds), and propose how to make OAuth provider configuration database-resident, project-related and provider-agnostic through adapters.

Scope of the review: this repository (`api.auth`, the authentication service), its only current OAuth consumer (`magic-worlds-api`), and the administrative client (`magic-auth-dashboard`), where the new configuration is managed.

## Executive summary

**Is Google OAuth hardcoded to a single project?** Not in its logic — but yes in its configuration, and that is what blocks a second project.

- The login flow is already project-scoped: the project and user group are bound server-side at start, and the callback can only issue a session for that bound project. That part of the design is sound and reusable.
- **Every setting is a single deployment-wide environment variable**: one Google client id and secret, one list of redirect URIs, one list of return origins, one provisioning mode, one hosted-domain rule — and, critically, **one companion-backend URL with one static bearer token** that `api.auth` calls to learn which project a login belongs to. Only projects served by that one backend can use OAuth. Today that backend is `magic-worlds-api`, which itself holds exactly one project identity.
- **The provider is hardcoded at every layer**: route prefix, config class, Authlib client name, state store defaults, provider-init constant, a database `ENUM('google','patreon')`, five stored procedures, two triggers, eleven activity types and the audit path matcher.
- There is **no second OAuth implementation to generalise from**. Patreon, the only other "provider", is not an OAuth login flow at all.
- The repository **already contains the blueprint** for the fix: the billing subsystem moved from global environment credentials to per-tenant, Fernet-encrypted, rotatable database credentials with a provider registry table, an adapter Protocol, root-only secret submission and database triggers as a fail-closed backstop.

**Most important findings beyond the question asked:**

1. The **link** and **re-authentication** flows cannot complete as written; with auto-create enabled, a returning password user silently gets a duplicate account.
2. The production callback module contains **test-only branches** that accept forged state, authorization codes and ID tokens whenever a pytest environment variable is present.
3. The trust model lets the companion backend **assert any project and any user group**. That is acceptable with one trusted backend and becomes a cross-tenant privilege-escalation path the moment there are two.
4. The identity key `(provider, HMAC(sub))` is correct only for providers with globally stable subjects. Microsoft, Apple and Facebook issue per-client or per-team subjects; generic OIDC issuers can collide.

**Recommended direction:** a three-level model — *provider type* (adapter code plus a catalog row) → *connection* (encrypted credentials and endpoints in the database) → *project binding* (per-project policy and URL allow-lists) — with a provider-blind shared pipeline, an inverted init handshake in which the consumer authenticates to `api.auth` with a project credential instead of `api.auth` calling the consumer, and a seven-phase migration whose first three phases change no behaviour.

## Reading order

| # | Document | Contents |
| --- | --- | --- |
| 01 | [Current state](01-current-state.md) | How Google OAuth works today: components, endpoints, deployed BFF topology, step-by-step flow, storage, configuration surface, properties worth keeping. |
| 02 | [Findings: hardcoding](02-findings-hardcoding.md) | Inventory of provider coupling, single-tenant configuration coupling, Magic Worlds leakage, and the in-repository precedents that show the target is reachable. |
| 03 | [Gaps](03-gaps.md) | Part A: defects and incomplete behaviour today. Part B: capability gaps versus "any project, any provider, configuration in the database". |
| 04 | [Research](04-research.md) | Protocol families, provider quirk matrix, global versus pairwise subjects, e-mail trust, multi-issuer threat model, how established identity systems model this, handshake and topology options, secrets at rest, library notes, sources. |
| 05 | [Target architecture](05-target-architecture.md) | Adapter contract, adapter classes, registry, connection resolution, init handshake, routes, shared pipeline, package layout, what stays in the environment. |
| 06 | [Data model](06-data-model.md) | Proposed tables, changes to external accounts, secrets handling, administration API, activity vocabulary, Redis key space, schema rollout mechanics. |
| 07 | [Migration plan](07-migration-plan.md) | Seven phases with exit criteria and rollback, test strategy, relative sizing. |
| 08 | [Risks](08-risks.md) | Risk register: introduced, pre-existing and do-nothing risks; top five. |
| 09 | [Open questions](09-open-questions.md) | Decisions needed, with options and recommendations. |
| 10 | [Consumer guide](10-consumer-guide.md) | Today's consumer contract, the proposed contract for any project, what Magic Worlds changes and when, onboarding checklist. |
| 11 | [Admin dashboard](11-admin-dashboard.md) | The `magic-auth-dashboard` workstream: screens, the project-assignment mechanism, write-only credentials UI, readiness diagnostics, files and registration points, sequencing, testing. |
| 12 | [Implementation status](12-implementation-status.md) | What was built from the plan, how it was verified, what was deliberately left for a later release, rollout notes. |

## Identifier conventions

- `F-nn` — findings, in document 02.
- `G-nn` — gaps, in document 03.
- `R-nn` — risks, in document 08.

Source files are cited by path and function name rather than line number, in keeping with this repository's documentation lint (line references go stale and are rejected by the static documentation tests). Modules that do not exist yet are written in dotted form.

## How the review was done

- Read in full: the Google router, configuration, OAuth client, state store, provider-init redemption, ID-token verifier, project-pinning helpers, and the external-accounts tables, procedures and triggers.
- Surveyed: activity, audit and middleware coupling; error codes; rate limiting; API keys; the billing, Stripe, e-mail and Patreon subsystems as precedents; schema rollout scripts; the test suite's patch targets and static guards.
- Reviewed the consumer side in `magic-worlds-api`: provider-init issue and redeem, start shim, callback relay, delivery-code exchange, configuration, and the `magic_auth_client` library surface.
- Reviewed the administrative client `magic-auth-dashboard`: routing, navigation, transport and service conventions, permission model, design system, testing, and the billing credentials and project-attachment features used as precedents.
- Environment files containing real values were not read; variable *names* were taken from the template only.
- External protocol facts were checked against primary sources listed at the end of document 04.

## Limitations

- Static review only: nothing was executed against a live identity provider, database or Redis, apart from the repository's documentation lint.
- The working tree had uncommitted changes in unrelated areas (e-mail, billing, refresh lifecycle) at review time; OAuth modules were reviewed as found on disk.
- Statements about Magic Worlds reflect its repository at review time; its installed `magic_auth_client` metadata lagged its source, so the published client surface may differ.
- Effort figures in the plan are relative, not estimates in days.
