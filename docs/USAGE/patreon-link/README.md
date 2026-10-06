# Patreon account linking

A signed-in consumer can link their Patreon membership to their local account so that a
companion service (Magic Worlds in the original deployment) can read a normalized
entitlement — plan, tier, status, freshness — over a dedicated server-to-server contract.
`api.auth` reads Patreon with the creator's own API credentials, proves ownership of a
membership by e-mailing a one-time proof to the member's Patreon e-mail, classifies
memberships through a campaign-scoped tier map, and keeps the result current from signed
webhooks and a sync worker. Patreon is **entitlement and link only**: it never signs
anyone in and never issues local tokens, sessions or cookies.

## Key concepts

| Concept | What it is |
| --- | --- |
| Link | A `user_external_accounts` row with `provider = 'patreon'`, keyed on an HMAC of the Patreon user id. One active Patreon link per local user and per Patreon account. |
| Email-loop proof | A single-use `<lookup_id>.<secret>` token e-mailed only to the e-mail Patreon returns for the member. Consuming it from the same signed-in user activates the link. |
| Tier map | Configuration that maps `(campaign_id, tier_id)` to an internal `plan_code` and `tier_code` with a priority. It is the only classification authority; the database keeps an HMAC mirror of it. |
| Entitlement | One current normalized projection per user: `status` (`active`, `free`, `pending`, `former`, `revoked`, `stale`), `plan_code`, `tier_code`, `link_status` and freshness timestamps, plus append-only history. |
| Webhook | `POST /webhooks/patreon`, a signed fast path that applies complete member documents or queues a resync. |
| Sync worker | `src/workers/patreon_sync_worker.py`: scheduled full sweeps, the resync queue, retention and creator-token refresh. The source of truth. |
| S2S contract | `GET /internal/users/{user_hash}/entitlements`, authenticated with a dedicated bearer, never with user sessions. |

## Route families

| Family | Routes | Caller and authentication |
| --- | --- | --- |
| Link lifecycle | `POST /auth/patreon/link/request`, `POST /auth/patreon/link/confirm`, `GET /auth/patreon/link/status`, `DELETE /auth/patreon/link` | Signed-in user (`Authorization: Bearer` or the `access_token` cookie); request, confirm and unlink also need recent authentication |
| Webhook | `POST /webhooks/patreon` | Patreon; `X-Patreon-Signature` over the raw body |
| Server-to-server | `GET /internal/users/{user_hash}/entitlements`, `POST /internal/users/{user_hash}/entitlements/patreon/resync` | Companion service; `Authorization: Bearer <PATREON_S2S_BEARER_TOKEN>` |
| Operator dashboard | `/admin/patreon/*` (8 routes) | Root users only |

Everything is off by default. Six switches (`PATREON_LINKING_ENABLED`,
`PATREON_WEBHOOKS_ENABLED`, `PATREON_SYNC_ENABLED`, `PATREON_S2S_ENTITLEMENT_ENABLED`,
`PATREON_CREATOR_TOKEN_REFRESH_ENABLED`, `PATREON_RAW_PAYLOAD_CAPTURE_ENABLED`) enable the
parts independently; see [Feature switches](reference.md#feature-switches).

## Rules and caveats

- **No login, ever.** There is no `/auth/patreon/login`, `/auth/patreon/authorize`,
  `/auth/patreon/callback` or `/auth/patreon/token`, and none may be added under another
  name. Patreon data never reaches JWT claims, Redis session payloads, refresh-token
  state, cookies, login/register/switch-project responses or `/auth/validate`. A static
  test (`tests/static/test_patreon_no_login_static.py`) guards the source.
- **Consumers only.** Root and admin accounts get the neutral answer and nothing is sent.
- **The hint is required and must be the Patreon e-mail.** `patreon_email_hint` only
  selects the member in the configured campaigns; ownership is proven by the e-mailed
  proof, which is always sent to the e-mail Patreon returns. E-mail equality never links
  anything by itself, and a hidden or empty Patreon e-mail blocks linking.
- **Neutral answers.** The link routes answer the same body whatever happened (no member,
  hidden e-mail, conflict, feature off, provider error), so membership is never revealed.
- **One link at a time.** A user with an active Patreon link must unlink before linking
  again; a Patreon account linked to another user cannot be linked, and its owner is
  never disclosed.
- **Unlinking does not touch sessions.** It sets the entitlement to `free` and keeps all
  history.
- **Webhooks are a fast path; the worker is the source of truth.** Partial documents,
  delete events and unmapped tiers queue a resync instead of changing the entitlement.
- **Stale is labeled, not guessed.** Readers see `status: stale` once `stale_after` has
  passed on an active entitlement; outages never downgrade anyone.
- **No `EXT_81xx` code reaches a client today.** Patreon routes answer with neutral bodies
  and platform codes; see [Error codes](reference.md#error-codes).

## In this suite

| Document | Purpose |
| --- | --- |
| [README.md](README.md) | Concepts, route families and rules (this page). |
| [request-flow.md](request-flow.md) | What each link, webhook, sync, S2S and admin request does, step by step. |
| [scenarios.md](scenarios.md) | End-to-end cases: first link, hidden e-mail, conflicts, relink, unknown tier, outages, rollback. |
| [architecture.md](architecture.md) | Components, data model, classification rules, data classification and design decisions. |
| [reference.md](reference.md) | Settings, route contracts, response fields, statuses, activity codes, schema, retention. |
| [troubleshooting.md](troubleshooting.md) | Symptom, cause and fix, with the health fields to read. |

## Related

- [Patreon runbook](../../RUNBOOKS/patreon-link.md) — setup, webhook registration, token
  rotation, incident response and rollback.
- [OAuth](../oauth/README.md) — sign-in with external providers. Patreon is listed in the
  OAuth provider catalog as link-only and can never be enabled for sign-in there.
- [Error reference](../errors.md) — lists the `EXT_81xx` family, defined but not returned.
