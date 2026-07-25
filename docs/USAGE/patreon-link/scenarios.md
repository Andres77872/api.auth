# Patreon Link Scenarios

This document describes expected behavior for common and failure scenarios in the Patreon entitlement/link integration.

Patreon is **entitlement/link only**. It is not local authentication authority and must not issue local sessions, access tokens, refresh tokens, cookies, or API keys.

## Scenario Matrix

| Scenario | Expected posture |
| --- | --- |
| Matching email | Email equality is a proof hint only; link still requires local auth, recent reauth, explicit intent, and provider identity resolution. |
| Mismatched email | Send email-loop proof only to the Patreon-returned member email; no entitlement until proof succeeds. |
| Hidden/null Patreon email | Block v1 automated activation safely; no fallback to user-supplied/local email. |
| Provider identity conflict | Reject generically without revealing the linked user's identity or entitlement. |
| Relink | Require explicit unlink/relink lifecycle and preserve prior history. |
| Unknown tier | Fail safe; do not grant paid entitlement from an unmapped tier. |
| Stale entitlement | Label as stale/degraded using normalized fields; do not hide freshness state. |
| Token refresh failure | Report degraded health and preserve last-known snapshots; fail closed for new grants. |
| Webhook replay | Return safe success without duplicate side effects. |
| Partial webhook | Enqueue source-of-truth resync or mark stale; no destructive downgrade. |
| Rollback | Disable behavior non-destructively and preserve live history. |

## 1. Matching Email

### Given

- The local user is authenticated.
- Recent local reauthentication is satisfied.
- `POST /auth/patreon/link/request` is called with explicit user intent.
- Patreon returns a non-null member email that matches the local activated email.

### Expected behavior

- The matching email may be treated as a proof hint only after explicit user confirmation and provider identity resolution.
- Durable authority is still the Patreon provider identity HMAC/fingerprint, not the email string.
- The link may activate only if no active conflict exists for the provider identity.
- The response remains safe and must not disclose raw Patreon identifiers, raw or masked Patreon email, signatures, payloads, hash prefixes, audit rows, tokens, or secrets.

### Must not happen

- Email equality must not create a link by itself.
- The Patreon email must not activate, primary-mark, recover, or otherwise authorize local email state.
- The flow must not create a local session.

## 2. Mismatched Email

### Given

- The local user's activated email differs from the non-null Patreon member email returned by the creator API.
- The local user explicitly requested linking.

### Expected behavior

- `api.auth` creates a pending proof request.
- A single-use email-loop token is sent only to the Patreon-returned member email.
- The pending proof is hash-only at rest, purpose-scoped to Patreon linking, short-lived, single-use, and bound to the initiating local user and pending link context.
- No active link or paid entitlement is granted until `POST /auth/patreon/link/confirm` consumes the proof successfully.

### Must not happen

- Do not send the proof to the local account email unless Patreon returned that exact email.
- Do not send to a user-supplied replacement email.
- Do not grant entitlement from email equality or from a user-entered hint.

## 3. Hidden or Null Patreon Email

### Given

- Patreon returns a member whose email is hidden or null.
- The configured v1 secondary proof is email-loop proof.

### Expected behavior

- The link remains unactivated or blocked-safe.
- The public response remains generic and neutral.
- Operators may see non-secret activity/health evidence of blocked hidden-email outcomes.
- No entitlement is granted from that membership in v1.

### Must not happen

- Do not ask the user to supply a replacement proof email as authority.
- Do not fall back to local email equality.
- Do not introduce a Patreon OAuth-login path as a workaround.
- Do not expose whether a hidden-email member exists to the browser.

## 4. Conflict: Provider Identity Already Linked

### Given

- Patreon provider identity `P1` is already actively linked to local user A.
- Local user B completes or attempts to complete proof for `P1`.

### Expected behavior

- The activation is rejected.
- The public response is generic.
- Activity records use redacted reason codes only, such as `provider_identity_unavailable`.
- User B learns nothing about user A's identity, email, plan, campaign, tier, link state, or history.

### Must not happen

- Do not return the existing owner.
- Do not disclose whether the owner is active, paid, revoked, or stale.
- Do not expose provider HMACs, fingerprints, hash prefixes, or audit rows.

## 5. Relink: Same User Wants a Different Patreon Identity

### Given

- The local user already has an active Patreon link to provider identity `P1`.
- The same local user attempts to link provider identity `P2`.

### Expected behavior

- The system requires an explicit unlink/relink lifecycle.
- Recent local reauthentication is required for unlink and relink-sensitive operations.
- Prior link, snapshot, entitlement, and unlink history for `P1` remains preserved indefinitely.
- Current entitlement should be projected to free/revoked/unlinked after unlink until a new link lifecycle completes.

### Must not happen

- Do not silently overwrite the active provider identity.
- Do not destructively delete prior link evidence.
- Do not revoke local auth sessions due to Patreon unlink/relink.

## 6. Unknown Tier

### Given

- Patreon returns an active member with an entitled tier.
- The campaign/tier pair has no active mapping in the configured tier map.

### Expected behavior

- Classification fails safe.
- No paid entitlement is granted from the unmapped tier.
- A non-secret tier-map miss activity/health signal is recorded.
- Source-of-truth resync may be queued if the payload is incomplete or ambiguous.

### Must not happen

- Do not expose raw campaign ID or raw tier ID to browser-visible responses.
- Do not invent a plan code from Patreon tier names.
- Do not downgrade an existing paid snapshot solely from a partial webhook with unknown tier evidence.

## 7. Stale Entitlement

### Given

- The current entitlement snapshot exists.
- `stale_after` has passed or sync freshness exceeds the configured threshold.

### Expected behavior

- `GET /auth/patreon/link/status` and S2S reads expose normalized stale/degraded state through safe fields.
- Existing last-known paid snapshots may be preserved as stale/degraded until source-of-truth correction completes.
- Health reports stale sync separately from unrelated local authentication health.
- Magic Worlds can apply its own bounded cache policy using `last_synced_at` and `stale_after`.

### Must not happen

- Do not present stale data as freshly confirmed.
- Do not add Patreon entitlement fields to `/auth/validate` to solve staleness.
- Do not leak provider failure internals, raw payloads, campaign/tier IDs, hashes, or audit rows.

## 8. Creator Token Refresh Failure

### Given

- The creator access token expires or refresh fails.
- Scheduled sync, manual resync, or provider API access cannot complete.

### Expected behavior

- Provider health is degraded with a non-secret reason such as `creator_token_invalid` or `creator_token_refresh_failed`.
- Existing snapshots are preserved as stale/degraded.
- New paid grants fail closed when no trusted current snapshot exists.
- Token state, if automatic refresh is enabled, remains global provider state and encrypted/server-only.

### Must not happen

- Do not store creator tokens in `user_external_accounts` or any per-user row.
- Do not log raw tokens, refresh tokens, client secrets, or token fingerprints to browser-visible surfaces.
- Do not revoke or downgrade users solely because the creator token could not be refreshed.

## 9. Webhook Replay

### Given

- Patreon retries the same webhook delivery.
- The delivery has the same allowed event type and raw body digest/member reference used for local idempotency.

### Expected behavior

- The delivery ledger recognizes the replay/duplicate.
- The receiver returns a safe success posture.
- No duplicate entitlement history, proof email, activity side effect, or user-visible mutation is created.

### Must not happen

- Do not treat replay as a second entitlement change.
- Do not expose the delivery hash, raw body digest, signature, or payload to clients.
- Do not rely on a native Patreon delivery ID; the local ledger owns idempotency.

## 10. Partial Webhook

### Given

- A verified Patreon webhook is missing relationships, tier data, campaign data, or other fields needed for safe classification.

### Expected behavior

- The webhook is accepted only after raw-body signature verification.
- The delivery is recorded safely.
- A per-member/campaign resync is queued when enough non-secret reference exists, or current state is marked stale/resync-pending.
- Current entitlement is not destructively downgraded from partial evidence.

### Must not happen

- Do not trust unverified payloads.
- Do not downgrade paid entitlement solely from missing fields.
- Do not persist raw payloads unless explicitly enabled for encrypted raw-payload quarantine with a 30-day maximum.

## 11. Rollback Behavior

### Given

- Live Patreon links, snapshots, webhook deliveries, proof rows, unlink history, or audit evidence may exist.
- Operators need to roll back the feature.

### Expected behavior

Rollback is non-destructive:

1. Disable `PATREON_LINKING_ENABLED`.
2. Disable `PATREON_WEBHOOKS_ENABLED` or block `POST /webhooks/patreon` at ingress.
3. Disable `PATREON_SYNC_ENABLED` and stop `src/workers/patreon_sync_worker.py`.
4. Disable `PATREON_S2S_ENTITLEMENT_ENABLED` so Magic Worlds stops pulling Patreon entitlement.
5. Disable `PATREON_CREATOR_TOKEN_REFRESH_ENABLED` and `PATREON_RAW_PAYLOAD_CAPTURE_ENABLED` if needed.
6. Clear only Patreon Redis namespaces for proof/rate/dedupe/sync locks.
7. Leave additive schema and history rows in place once live data exists.

### Must not happen

- Do not destructively delete live link, snapshot, webhook, proof, unlink, or audit history as normal rollback.
- Do not clear local auth session, refresh-token, Google OAuth, or unrelated Redis namespaces.
- Do not remove additive schema in environments with live Patreon records unless a separate destructive preflight proves it is safe.

## Scenario-to-Activity Hints

| Scenario | Typical activity code |
| --- | --- |
| Proof requested | `act-cat-075` / `patreon_link_proof_requested` |
| Proof consumed | `act-cat-076` / `patreon_link_proof_consumed` |
| Link activated | `act-cat-077` / `patreon_linked` |
| Link rejected/conflict/hidden email | `act-cat-078` / `patreon_link_rejected` |
| Unlink | `act-cat-079` / `patreon_unlinked` |
| Webhook accepted | `act-cat-080` / `patreon_webhook_received` |
| Webhook rejected | `act-cat-081` / `patreon_webhook_rejected` |
| Webhook replay | `act-cat-082` / `patreon_webhook_replay_ignored` |
| Sync started/completed/failed | `act-cat-083`..`act-cat-085` |
| Entitlement changed | `act-cat-086` / `patreon_entitlement_changed` |
| Unknown tier | `act-cat-087` / `patreon_tier_map_miss` |
| Token refresh outcome | `act-cat-088`..`act-cat-089` |
| Retention purge | `act-cat-090` / `patreon_retention_purged` |

Activity details must remain redacted and must not include raw Patreon IDs, emails, signatures, payloads, tokens, secrets, fingerprints, hash prefixes, or audit rows.

## Related Documentation

- [Overview](README.md)
- [Architecture](architecture.md)
- [Request Flow](request-flow.md)
- [Reference](reference.md)
- [Troubleshooting](troubleshooting.md)
- [Runbook](../../RUNBOOKS/patreon-link.md)

---

**Document Version**: 1.0
