# External Accounts Schema

Documentation for the Google OAuth external-account storage added by `google-oauth-login`.

## Purpose

`user_external_accounts` stores the durable link between a local consumer user and a Google provider subject. It is identity-link metadata only. It is not an OAuth token store.

## Table: `user_external_accounts`

| Column | Purpose | Security Notes |
| --- | --- | --- |
| `id` | Internal external-account row ID | Not browser authority. |
| `user_id` | Local `users(id)` owner | FK to local user. |
| `provider` | Provider enum, currently `google` | Single-provider MVP. |
| `provider_sub_hash` | HMAC-SHA256 of Google `sub` | Primary external identity authority; raw `sub` is not persisted. |
| `provider_sub_fingerprint` | Short non-reversible support fingerprint | Safe for redacted activity/audit correlation. |
| `provider_email_hash` | Optional HMAC of Google email snapshot | Email is not link authority. |
| `provider_email_masked` | Optional masked email snapshot | Never store raw Google email in activity/audit. |
| `provider_email_verified_at_link` | Google `email_verified` snapshot | Does not activate local email. |
| `status` | `linked`, `unlinked`, or `revoked` | Active uniqueness applies only while linked. |
| `linked_at`, `linked_by` | Link metadata | Operational evidence. |
| `last_seen_at` | Returning login refresh point | Updated on successful linked login. |
| `unlinked_at`, `unlinked_by`, `unlink_reason` | Soft-unlink metadata | Preserve history. |
| `metadata` | Redacted operational JSON | Do not store provider tokens or strict hashes. |
| `active_provider_sub_hash` | Generated uniqueness helper | Ensures one active user per provider subject. |
| `active_user_provider` | Generated uniqueness helper | Ensures one active Google link per user. |

## Forbidden Columns

These columns must not exist in `user_external_accounts`:

```text
access_token, refresh_token, id_token, authorization_code, code, state, nonce, code_verifier
```

Google access token, refresh token, and id token material is not persisted anywhere in this schema.

## Provider-sub Authority

The durable authority is the HMAC of Google's stable `sub` claim:

```text
provider='google' + provider_sub_hash
```

Email address, `email_verified`, display name, picture, or hosted domain are not primary linking keys.

Email-only collision is treated as an account-takeover risk and must not auto-link accounts.

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
| `sp_link_external_account` | Link Google to an existing active consumer; refuses conflicts. |
| `sp_unlink_external_account` | Soft-unlink active Google account. |
| `sp_touch_external_account_last_seen` | Update last-seen/masked snapshots after returning linked login. |
| `sp_create_consumer_user_from_external_account` | Create consumer, optional pending local email, optional group membership, and external link transactionally. |

Wrappers in `src/Util/db/db_external_accounts.py` accept only application-computed HMACs and masked snapshots; they do not accept raw Google token material.

## Triggers

`trg_external_accounts_before_insert` and `trg_external_accounts_before_update` enforce:

- provider is `google`,
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

Unlinking:

- requires authenticated consumer and recent reauth,
- refuses when Google is the only usable auth method,
- soft-unlinks rather than deleting the row,
- revokes affected local auth state,
- preserves audit/history.

## Rollback Preservation Rules

Do not destructively drop external-account schema when live or historical rows, OAuth audit rows, or Google OAuth activity rows exist.

Preferred rollback is disabling Google OAuth and provider-init issuance while leaving this table and audit/activity evidence in place.
