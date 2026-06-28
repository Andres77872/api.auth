# Google OAuth Troubleshooting

Troubleshooting must preserve the security boundary. Do not copy raw Google authorization codes, state, nonce, code verifier, ID token, access token, refresh token, provider-init token, raw provider subject, raw Google email, `project_hash`, or `user_group_hash` into tickets, logs, docs, or chat.

Use fingerprints, correlation IDs, activity IDs, and masked snapshots.

> Provider boundary: use this page for Google OAuth login/link failures. Patreon proof, webhook, sync, S2S, stale-entitlement, and tier-map failures belong to [Patreon account linking](../patreon-link/README.md); Patreon is entitlement/link only and must not be diagnosed as a Google-style local session callback.

## Fast Triage Table

| Symptom | Likely Cause | Safe Action |
| --- | --- | --- |
| `/auth/google/start` returns neutral OAuth error | Feature disabled/not ready, provider-init invalid, redirect/return origin mismatch, rate limit, Redis unavailable | Check config presence by key name only, verify exact localhost allowlists, inspect provider-init fingerprint and activity `act-cat-065`. |
| Google callback fails before token exchange | Missing/malformed/expired/replayed state | Inspect `GOOGLE_OAUTH_STATE_REJECTED`, state fingerprint, and Redis state/consumed namespaces. Do not print raw state. |
| Callback fails after token exchange | ID-token validation failure, nonce mismatch, Workspace `hd`, wrong audience/issuer, JWKS issue | Inspect `GOOGLE_OAUTH_NONCE_REJECTED` or `GOOGLE_OAUTH_ID_TOKEN_REJECTED`; compare config client ID by fingerprint only. |
| JWKS `kid` miss | Google rotated keys or fake provider mismatch | Verifier refetches JWKS once. If the `kid` is still absent, it must fail closed. Check JWKS cache TTL and fake provider fixtures. |
| Token exchange failure | Invalid/fake code, PKCE verifier mismatch, provider outage | Confirm state was consumed before exchange and code was attempted once. Never retry the same code manually against real Google. |
| Link fails | Missing recent reauth, provisioning mode not `link_only`/`both`, provider-sub conflict | Reauth locally first. Do not disclose the owner of an existing provider-sub link. |
| Unlink refused | Google is the only usable auth method | Establish fallback local password/auth first; then retry with recent reauth. |
| Redis unavailable | State/rate/replay controls cannot be enforced | OAuth paths should fail closed. Do not add in-memory fallback in `api.auth`. |

## State Replay / Expiry

Expected behavior:

- State TTL is capped at `600` seconds.
- State is consumed atomically before Google code exchange.
- A consumed tombstone prevents replay.
- Replayed/expired/missing state returns neutral `EXT_8xxx` posture.

Operator checks:

1. Confirm Redis is reachable from the `api.auth` process.
2. Inspect only HMAC-keyed namespaces such as `google_oauth_state:*` and `google_oauth_state_consumed:*`.
3. Use `state_fingerprint`, not raw state, in incident notes.

## Nonce Mismatch

Nonce mismatch means the ID token does not match the server-side OAuth transaction. Treat it as a security failure.

Safe checks:

- Confirm fake/test provider returns the nonce from Redis state.
- Confirm state was not manually edited in tests.
- Confirm no code path logs raw nonce.

## JWKS `kid` Miss / Outage

The verifier must:

1. cache JWKS according to provider cache headers with a hard cap of `3600` seconds,
2. refetch once on `kid` miss,
3. fail closed on second miss,
4. keep local password/session flows unaffected.

During an outage, disable Google OAuth rather than weakening validation.

## Provider-init Redemption Failure

Common causes:

- token expired,
- token already redeemed,
- wrong provider or audience,
- return origin not exact-match allowlisted,
- companion in-memory store restarted,
- browser is routed to a different companion process in a multi-instance deployment.

Important limitation: the current companion provider-init store is process-local memory. It is cleared on restart and requires sticky routing or a shared store for multi-instance production.

## Redirect / Return-Origin Mismatch

Allowlist checks are exact string matches. `http://localhost:3000` and `http://127.0.0.1:3000` are different origins. Trailing slashes and path differences matter for redirect URIs.

Use localhost examples only in docs and smoke files. Production origins must be configured outside docs through deployment-specific secret/config management.

## Neutral Public Errors

Most failures intentionally return:

- `OAuth authentication could not be completed.`
- `OAuth provider is not available.`
- `External identity action could not be completed.`

This is not a UX bug. It prevents account existence, provider-sub ownership, local email state, project membership, and strict scope leakage.

## Known Residual Verification Caveats

- Full-stack e2e `/auth/validate` caveat: callback can issue a `LoginResponse`, but synthetic OAuth-issued token validation remains unresolved in the local full-stack path until test DB migration/session validation is fixed.
- Trigger privilege caveat: local MySQL with binary logging can require elevated trigger privileges. Migration/source validation covers trigger SQL when the test user cannot create triggers.
- Pre-existing admin project auth failures are outside this OAuth docs phase and should not be treated as Phase 10 regressions.
