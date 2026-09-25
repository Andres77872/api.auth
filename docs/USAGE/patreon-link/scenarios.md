# Patreon link scenarios

End-to-end cases chaining several calls. Request fields and bodies are in
[reference.md](reference.md); the steps inside each call are in
[request-flow.md](request-flow.md). Examples use `$AUTH` for the base URL,
`$ACCESS_TOKEN` for the signed-in consumer and `$S2S_TOKEN` for the companion's bearer.

## First link

1. The user signs in (or completes an OAuth reauth) so the session is recently
   authenticated.
2. The front end asks for a proof, sending the e-mail of the user's Patreon account:

   ```bash
   curl -X POST "$AUTH/auth/patreon/link/request" \
     -H "Authorization: Bearer $ACCESS_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"patreon_email_hint": "fan@example.com", "explicit_user_intent": true}'
   ```

   The answer is always the neutral `202`. If the e-mail belongs to a member of a
   configured campaign, a proof is e-mailed to that Patreon e-mail
   (`patreon_link_proof_requested`).
3. The user opens the e-mailed link. The front end takes its `token` parameter and, from
   the same signed-in session and still within the recent-authentication window, posts
   it:

   ```bash
   curl -X POST "$AUTH/auth/patreon/link/confirm" \
     -H "Authorization: Bearer $ACCESS_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"token": "'"$PROOF_TOKEN"'"}'
   ```

   `200` with `link_status: linked` and the entitlement (`patreon_linked`). If the
   Patreon read right after linking fails, the entitlement is `pending` and a resync is
   queued.
4. The companion reads the entitlement server-to-server:

   ```bash
   curl "$AUTH/internal/users/$USER_HASH/entitlements" \
     -H "Authorization: Bearer $S2S_TOKEN"
   ```

If the recent-authentication window runs out between steps 2 and 3, confirm answers
`401` `AUTH_1008`; the user reauthenticates and posts the same token again while it is
valid (`900` seconds by default).

## Hint does not match the Patreon e-mail

The user types an address that is not the one on their Patreon account. No member
matches, nothing is sent, and the answer is the same neutral `202`
(`patreon_link_rejected`, `member_not_available`). The UI should tell the user to use the
e-mail of their Patreon account and check that inbox; it must not reveal whether the
address belongs to a patron.

## Hidden or empty Patreon e-mail

The member is found but Patreon returns no e-mail for them. No proof can be delivered, so
nothing is sent and the answer is the neutral `202` (`patreon_email_hidden_or_null`).
There is no fallback: no user-supplied address, no local e-mail, no e-mail equality, no
Patreon login. The link cannot be completed until Patreon returns an e-mail.

## Patreon account linked to someone else

User B completes a proof for a Patreon account already linked to user A. Confirm answers
the neutral `202` (`provider_identity_unavailable`). B learns nothing about A: no
identity, plan, tier or link state. Only A unlinking frees the Patreon account.

## Switching to another Patreon account

A user with an active link who confirms a proof (for any Patreon account) gets the
neutral `202` (`active_patreon_link_exists`). To switch:

1. `DELETE /auth/patreon/link` (recent authentication required). The entitlement becomes
   `free`, history is kept, sessions are untouched.
2. Request and confirm a proof for the new account as in [First link](#first-link).

## Tier upgrade or downgrade

Patreon sends `members:pledge:update` with the full member document. The webhook verifies
the signature, finds the linked user, classifies the new tier and stores it at once
(`patreon_entitlement_changed`). The next S2S read reflects it. A downgrade is applied the
same way, because a complete signed document is Patreon's own statement of the member's
state.

## Cancellation or removal

A `members:delete` or `members:pledge:delete` event never changes the entitlement
directly: it queues a resync. The worker re-reads the member; once a complete read shows
no active mapped tier the entitlement becomes `former` with plan `free`. If Patreon no
longer returns the member at all, the next complete sweep downgrades them the same way.
The link stays, so the user can pledge again without relinking.

## Unknown tier

An active member holds a tier that is not in the tier map. Nothing is granted from it:
the entitlement becomes `pending` (a paid plan already on record is kept) and a resync is
requested. Webhook deliveries record `patreon_tier_map_miss`. Fix: add the mapping to the
tier-map source, restart the API and the worker so they read it, and queue a resync.

## Patreon outage or expired creator token

Sync jobs fail and retry with backoff; a Patreon `429` is honored exactly. Nothing is
written on failure, so every entitlement keeps its last value and reads as `stale` once
`stale_after` passes (`PATREON_SYNC_STALE_AFTER_SECONDS` after the last sync). Users with
no data stay free. A `401` from Patreon marks the stored creator token revoked and, with
refresh enabled, triggers an immediate refresh; otherwise rotate
`PATREON_CREATOR_ACCESS_TOKEN` (see the [runbook](../../RUNBOOKS/patreon-link.md)). After
recovery, the next sweep refreshes every linked member.

## Webhook redelivery

Patreon retries a delivery after a timeout. The ledger recognizes the delivery hash and
answers `200` without reprocessing. A delivery whose earlier attempt `failed`, or that
has been stuck in `received` for over 10 minutes, is processed again.

## Support asks for a fresh read

The companion (or an operator) queues a resync for one user:

```bash
curl -X POST "$AUTH/internal/users/$USER_HASH/entitlements/patreon/resync" \
  -H "Authorization: Bearer $S2S_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"force": true, "reason": "support_ticket"}'
```

`202` `status: queued` with the job id in `correlation_id`; repeating the call before the
job runs returns the same job. The worker must be running. Root users can do the same from
`POST /admin/patreon/resync`, which also answers `not_linked` for users without a link.

## Rollback

Rollback is non-destructive:

1. `PATREON_LINKING_ENABLED=false` — no new proofs or links.
2. `PATREON_WEBHOOKS_ENABLED=false`, or block `POST /webhooks/patreon` at ingress — Patreon
   receives `503` and retries later.
3. `PATREON_SYNC_ENABLED=false`, and stop the worker if needed.
4. `PATREON_S2S_ENTITLEMENT_ENABLED=false` — the companion's reads answer `401`; it must
   fall back to its own default.
5. Turn off `PATREON_CREATOR_TOKEN_REFRESH_ENABLED` and `PATREON_RAW_PAYLOAD_CAPTURE_ENABLED`
   if they were on.
6. Clear only `patreon_rate:*` Redis keys if needed.
7. Keep every table and history row.

Local sessions, refresh tokens, OAuth and unrelated Redis keys are not touched. Link
status and unlink keep working with linking disabled. The full procedure is in the
[runbook](../../RUNBOOKS/patreon-link.md).
