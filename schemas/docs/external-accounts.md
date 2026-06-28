# External Accounts Schema

Documentation for external-account storage used by Google OAuth and Patreon account linking. Google remains a login/link provider; Patreon is entitlement/link only and never becomes a login provider.

## Purpose

`user_external_accounts` stores the durable link between a local consumer user and an external provider subject. It is identity-link metadata only. It is not an OAuth token store.

Provider roles are deliberately different:

- Google may authenticate/link a local consumer after the Google OAuth/OIDC flow succeeds and local project authorization passes.
- Patreon may link an existing authenticated local consumer to an entitlement source only. Patreon proof, creator API reads, webhooks, and sync never issue local sessions or local auth tokens.

## Table: `user_external_accounts`

| Column | Purpose | Security Notes |
| --- | --- | --- |
| `id` | Internal external-account row ID | Not browser authority. |
| `user_id` | Local `users(id)` owner | FK to local user. |
| `provider` | Provider enum: `google` or `patreon` | Provider role determines whether the linked subject may login (`google`) or is entitlement/link only (`patreon`). |
| `provider_sub_hash` | HMAC-SHA256 of Google `sub` or Patreon `user.id` | Primary external identity authority; raw provider IDs are not persisted. |
| `provider_sub_fingerprint` | Short non-reversible support fingerprint | Safe for redacted activity/audit correlation. |
| `provider_email_hash` | Optional HMAC of provider email snapshot | Email is not durable link authority for either provider. |
| `provider_email_masked` | Optional masked email snapshot | Never store raw provider email in activity/audit. |
| `provider_email_verified_at_link` | Provider email-verification snapshot when applicable | Does not activate local email. |
| `status` | `linked`, `unlinked`, or `revoked` | Active uniqueness applies only while linked. |
| `linked_at`, `linked_by` | Link metadata | Operational evidence. |
| `last_seen_at` | Returning login refresh point or provider sync/proof observation | Updated only by provider-appropriate safe flows. |
| `unlinked_at`, `unlinked_by`, `unlink_reason` | Soft-unlink metadata | Preserve history. |
| `metadata` | Redacted operational JSON | Do not store provider tokens or strict hashes. |
| `active_provider_sub_hash` | Generated uniqueness helper | Ensures one active user per provider subject. |
| `active_user_provider` | Generated uniqueness helper | Ensures one active provider link per user/provider. |

## Forbidden Columns

These columns must not exist in `user_external_accounts`:

```text
access_token, refresh_token, id_token, authorization_code, code, state, nonce, code_verifier,
creator_token, webhook_secret, proof_token, proof_secret, s2s_token
```

Google access token, refresh token, and id token material is not persisted anywhere in this schema. Patreon is creator-owned and does not use per-user Patreon tokens; creator tokens, webhook secrets, proof secrets, and S2S credentials are server-only configuration or dedicated provider-token state, never per-user external-account columns.

## Provider-sub Authority

The durable authority is the HMAC of the provider-owned stable subject:

```text
provider='google' + provider_sub_hash
provider='patreon' + provider_sub_hash
```

For Google, `provider_sub_hash` is the HMAC of Google's stable `sub` claim. For Patreon, `provider_sub_hash` is the HMAC of the Patreon `user.id` returned by trusted creator-owned API/webhook reconciliation. Raw provider identifiers stay server-only.

Email address, `email_verified`, display name, picture, hosted domain, local `users.email`, masked email, or email equality are not primary linking keys.

Email-only collision is treated as an account-takeover risk and must not auto-link accounts.

## Patreon No-Login Provider Model

Patreon uses the same external-account HMAC authority shape for durable link ownership, but it is not authentication authority:

- An already-authenticated local consumer must initiate Patreon linking.
- Patreon provider identity is stored as `provider='patreon' + HMAC(Patreon user.id)`.
- Patreon proof, webhook deliveries, creator API reads, and entitlement sync never create local sessions, local access tokens, refresh tokens, API keys, or local session cookies.
- `/auth/validate` remains identity/session-only and does not include Patreon plan, tier, subscription, link, or entitlement fields.
- The Patreon login/session route family is explicitly absent and forbidden: `/auth/patreon/login`, `/auth/patreon/authorize`, `/auth/patreon/callback`, and `/auth/patreon/token`.

Patreon HMAC/fingerprint values are support and lookup authority inside `api.auth`; they are not browser-visible response fields.

## Patreon Email-Loop Proof Boundary

Patreon email can participate only in the selected v1 proof loop, not in durable identity authority:

- The proof email is sent only to the non-null Patreon member email returned by the creator-owned Patreon API.
- A user-supplied email, local account email, or matching email is never enough to activate a Patreon link or grant entitlement.
- Proof tokens are single-use, short-lived, hash-only at rest, and purpose-scoped to Patreon linking.
- Hidden/null Patreon member email blocks v1 automated activation safely because the proof cannot be delivered to a Patreon-returned email.
- Consuming a Patreon proof does not activate, primary-mark, recover, or otherwise authorize local email state.

## Masked Email Snapshot

`provider_email_hash`, `provider_email_masked`, and `provider_email_verified_at_link` are snapshots for support and audit correlation only.

They must not:

- activate a local email,
- mark a local email primary,
- enable password recovery,
- mutate `users.email`,
- bypass the local `user_emails` activation lifecycle.

Auto-created users may get a pending `user_emails` row. That row remains pending until the existing local activation flow succeeds.

## Stored Procedures

| Procedure | Purpose |
| --- | --- |
| `sp_get_user_by_external_account` | Resolve active provider-sub link to active local consumer only. |
| `sp_link_external_account` | Link Google or Patreon to an existing active consumer; refuses provider-sub conflicts. |
| `sp_unlink_external_account` | Soft-unlink active Google or Patreon account. |
| `sp_touch_external_account_last_seen` | Update last-seen/masked snapshots after returning linked Google login or safe Patreon observation. |
| `sp_create_consumer_user_from_external_account` | Google-only consumer auto-create path with optional pending local email, optional group membership, and external link transactionally. |

Wrappers in `src/Util/db/db_external_accounts.py` accept only application-computed HMACs and masked snapshots; they do not accept raw Google token material or per-user Patreon token material.

## Triggers

`trg_external_accounts_before_insert` and `trg_external_accounts_before_update` enforce:

- provider is `google` or `patreon`,
- provider-sub hash is exactly 32 bytes,
- fingerprint is exactly 12 characters,
- terminal statuses require unlink time,
- linked status cannot retain unlink time,
- unlink/last-seen timestamps cannot precede link time,
- identity fields are immutable after insert.

Local MySQL test environments may skip trigger installation when binary logging requires elevated trigger privileges. Source and bootstrap validation still cover the trigger SQL.

## Link / Unlink Semantics

Linking:

- allowed only for active consumers,
- requires provisioning mode `link_only` or `both`,
- requires recent local reauthentication/proof,
- refuses provider-sub conflicts,
- does not mutate local email activation state.

Google unlinking:

- requires authenticated consumer and recent reauth,
- refuses when Google is the only usable auth method,
- soft-unlinks rather than deleting the row,
- revokes affected local auth state,
- preserves audit/history.

Patreon linking:

- requires an existing authenticated local consumer and recent local reauth,
- requires provider identity HMAC authority plus the selected proof boundary,
- grants only normalized entitlement state after proof/classification succeeds,
- never issues local sessions and never stores per-user Patreon tokens,
- preserves link/snapshot/history rows for audit and dispute investigation.

Patreon unlinking:

- requires authenticated ownership and recent local reauth,
- soft-unlinks rather than deleting the row,
- stops future Patreon-backed entitlement projection unless relink completes,
- does not revoke local auth sessions because Patreon is not a login provider,
- preserves privacy-minimized link, entitlement snapshot, unlink, audit, and activity history indefinitely.

## Rollback Preservation Rules

Do not destructively drop external-account schema when live or historical rows, OAuth audit rows, Google OAuth activity rows, Patreon proof/link/snapshot/unlink rows, webhook delivery records, entitlement history, or Patreon audit/activity evidence exist.

Preferred rollback is disabling the affected provider behavior while leaving this table and audit/activity evidence in place:

- Google rollback disables Google OAuth/provider-init issuance without dropping historical Google external-account evidence.
- Patreon rollback disables linking, webhooks, sync, and S2S entitlement reads through flags/ingress/worker controls without deleting live Patreon history.
