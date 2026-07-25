# Patreon Link Usage Guide

Operator and integrator index for the Patreon account-link and entitlement surface in `api.auth`.

Patreon is **entitlement/link only** in this repository. It is not login authority, it does not create local sessions, and it does not add Patreon-derived fields to JWTs, refresh-token state, session payloads, or `/auth/validate`.

## Quick Navigation

| Document | Purpose |
| --- | --- |
| [Architecture](architecture.md) | Ownership boundaries, email-loop proof, tier mapping, webhook/resync split, S2S contract, data classification, and diagrams. |
| [Request Flow](request-flow.md) | Link request, proof confirmation, status, unlink, webhook, scheduled/manual resync, retention, and S2S reads. |
| [Scenarios](scenarios.md) | Matching email, mismatched email, hidden email, conflict, relink, unknown tier, stale entitlement, token failure, webhook replay, partial webhook, and rollback behavior. |
| [Reference](reference.md) | Env vars, route contracts, safe fields, activity codes, schema concepts, retention windows, kill switches, rate limits, and forbidden browser fields. |
| [Troubleshooting](troubleshooting.md) | Hidden email, proof delivery, token expiry, webhook signature mismatch, webhook pause, tier-map miss, stale sync, rate limits, and companion S2S failures. |
| [Runbook](../../RUNBOOKS/patreon-link.md) | Setup, creator-token handling, webhook registration, tier-map seeding, health checks, resync operations, incident response, retention, rollout, and rollback. |
| [External Account Schema](../../../schemas/docs/external-accounts.md) | Provider identity HMAC authority, soft unlink, no per-user tokens, and history preservation. |

## What This Integration Does

`api.auth` uses creator-owned Patreon access to classify Patreon membership into a normalized entitlement that another server can consume safely.

The integration supports:

1. authenticated local users requesting a Patreon link,
2. proof delivery through an email-loop token sent only to the Patreon member email returned by the creator API,
3. durable provider identity authority through HMAC/fingerprint storage, not email equality,
4. multi-campaign, campaign-scoped tier mapping from day one,
5. webhook ingestion as a fast path,
6. scheduled/manual resync as source-of-truth correction,
7. safe internal S2S entitlement reads for Magic Worlds,
8. soft unlink and non-destructive rollback with audit/history preservation.

It does **not** make Patreon an authentication system.

## Disabled-by-Default Setup

All Patreon behavior is disabled unless operators explicitly enable the relevant server-side flags and provide server-only configuration.

Default-off switches:

| Switch | Default | Effect |
| --- | --- | --- |
| `PATREON_LINKING_ENABLED` | `false` | Blocks new user link request/confirm/status/unlink behavior that depends on Patreon. |
| `PATREON_WEBHOOKS_ENABLED` | `false` | Blocks Patreon webhook processing. |
| `PATREON_SYNC_ENABLED` | `false` | Blocks scheduled/manual Patreon API sync work. |
| `PATREON_S2S_ENTITLEMENT_ENABLED` | `false` | Blocks internal Magic Worlds entitlement reads. |
| `PATREON_CREATOR_TOKEN_REFRESH_ENABLED` | `false` | Blocks automatic creator-token refresh persistence. |
| `PATREON_RAW_PAYLOAD_CAPTURE_ENABLED` | `false` | Keeps raw payload quarantine disabled unless explicitly approved for diagnostics. |

Required server-only setup, when enabling the feature:

- creator access/refresh token or rotation mechanism,
- webhook secret,
- HMAC/pepper values for provider IDs, emails, proof tokens, and delivery hashes,
- S2S bearer token for Magic Worlds,
- enabled campaign list,
- campaign-scoped tier map,
- retention settings that do not exceed the documented caps.

Missing configuration must leave Patreon disabled or not-ready while local password login, Google OAuth behavior, existing sessions, refresh tokens, and `/auth/validate` continue unchanged.

## User Overview

From a user perspective, Patreon linking is a local-account action:

1. The user must already be authenticated locally in `api.auth`.
2. The user must satisfy recent local reauthentication or an equivalent local step-up proof.
3. The user explicitly requests Patreon linking.
4. `api.auth` looks up Patreon membership through creator-owned server credentials.
5. If proof is required, the system sends a single-use email-loop token only to the Patreon member email returned by Patreon.
6. After proof succeeds, `api.auth` links the Patreon provider identity and stores a normalized entitlement snapshot.
7. The user can view safe link status and unlink later, with recent reauthentication.

Email equality is only a hint. It is never durable authority and never grants entitlement by itself.

Hidden or null Patreon email blocks v1 automated activation because the selected proof cannot be delivered to a verified Patreon member email. The system must not fall back to a user-supplied email, local email, OAuth login, or email equality.

## Operator Overview

Operators own five safe-control loops:

| Loop | Operator responsibility |
| --- | --- |
| Configuration readiness | Keep flags disabled until secrets, campaigns, tier maps, S2S credentials, and retention settings are ready. |
| Tier-map management | Seed campaign-scoped tier mappings without printing raw campaign/tier IDs; validate ambiguity before enabling grants. |
| Webhook operations | Register `/webhooks/patreon`, verify signed deliveries, watch signature failures/replays, and pause safely on spikes. |
| Sync operations | Run scheduled and manual resync as source-of-truth correction; respect Patreon rate limits and stale/degraded states. |
| Retention and rollback | Purge proof/webhook/raw payload artifacts on schedule while preserving link/snapshot/unlink history indefinitely. |

The safe rollout posture is: deploy with all Patreon switches disabled, validate health, seed tier maps, enable S2S for no linked users, test linking, register webhooks, then enable sync. Phase 11 extends the runbook with the final deployment and rollback gates.

## Explicit No-Login / No-Session Boundary

Patreon proof, consent-like provider data, webhook deliveries, creator API reads, and resync jobs must never issue local authentication material.

Forbidden and absent Patreon auth routes:

- `/auth/patreon/login` — forbidden and absent.
- `/auth/patreon/authorize` — forbidden and absent.
- `/auth/patreon/callback` — forbidden and absent.
- `/auth/patreon/token` — forbidden and absent.

Those routes are intentionally forbidden. Do not add equivalent Patreon OAuth-login routes under another name.

Patreon flows must not return or set:

- local access tokens,
- refresh tokens,
- session cookies,
- API keys,
- `LoginResponse`, `RegisterResponse`, `SwitchProjectResponse`, or other local credential response shapes.

Patreon-derived entitlement fields must not be added to:

- JWT claims,
- Redis session payloads,
- refresh-token family state,
- browser cookies,
- `/auth/validate` response models or route output.

Magic Worlds reads Patreon entitlement through the dedicated internal S2S contract instead of overloading auth validation.

## Public and Internal Route Summary

| Route | Audience | Purpose |
| --- | --- | --- |
| `POST /auth/patreon/link/request` | Authenticated local user | Start link request after local reauth and explicit user intent. |
| `POST /auth/patreon/link/confirm` | Authenticated local user | Consume email-loop proof and activate link when all conditions are met. |
| `GET /auth/patreon/link/status` | Authenticated local user | Read owning user's safe link status and normalized entitlement summary. |
| `DELETE /auth/patreon/link` | Authenticated local user | Soft-unlink Patreon without revoking local sessions. |
| `POST /webhooks/patreon` | Patreon webhook sender | Verify raw-body HMAC-MD5 and process allowed member events safely. |
| `GET /internal/users/{user_hash}/entitlements` | Magic Worlds S2S | Read normalized entitlement using a dedicated internal bearer credential. |
| `POST /internal/users/{user_hash}/entitlements/patreon/resync` | Internal S2S/operator flow | Queue a safe manual Patreon resync. |

Browser-visible responses from user routes expose only normalized status and entitlement summaries. Internal S2S responses are also allow-listed and never expose raw Patreon internals.

## Retention Summary

| Artifact | Retention |
| --- | --- |
| Proof requests | 24 hours after expiry, then purge or irreversible stripping. |
| Webhook delivery hashes/idempotency records | 90 days. |
| Raw provider payload quarantine | Disabled by default; if enabled for approved diagnostics, max 30 days, encrypted/server-only, and must not be exposed. |
| Link history, entitlement snapshots/history, unlink history | Indefinite, privacy-minimized preservation. |

Indefinite history does not mean indefinite raw payload or raw email retention. Long-term evidence must remain redacted and non-reversible.

## Related Boundaries

- Google OAuth may login/link according to the Google OAuth suite; Patreon is entitlement/link only.
- `api.auth` owns link, proof, webhook, sync, snapshot, history, classification, retention, and S2S contract enforcement.
- Magic Worlds consumes normalized entitlement over S2S and decides its own product projection. Do not document or assume Magic Worlds internals from this repo.

---

**Document Version**: 1.0
