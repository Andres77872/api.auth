# Google OAuth/OIDC Runbook

Operational runbook for rolling out, monitoring, disabling, and rolling back the consumer-only Google OAuth/OIDC login path.

## Safety Rules

- Keep examples localhost-only. Do not document production domains/origins here.
- Never paste real Google authorization codes, access tokens, refresh tokens, ID tokens, client credentials, provider-init tokens, raw `project_hash`, or raw `user_group_hash` into tickets or runbook evidence.
- Google OAuth requests `openid email` only. Google access, refresh, and id token material is not persisted.
- `magic-worlds-api` issues provider-init; `api.auth` redeems provider-init and issues the local session.
- OAuth errors are intentionally neutral and use `EXT_8xxx` values.

## Rollout Sequence

1. Ship schema, code, docs, and companion provider-init with `GOOGLE_OAUTH_ENABLED` disabled.
2. Run migration preflight/dry-run/validate in a local or test DB only.
3. Enable local fake-provider smoke with localhost redirect and return origins.
4. Enable staging as `link_only`; require existing local credential proof before linking.
5. Production first exposure should remain `disabled` or `link_only`.
6. Consider `auto_create`/`both` only after all gates pass:
   - provider-init group binding verified,
   - local email activation delivery verified,
   - project access denial metrics reviewed,
   - strict-hash secrecy tests green,
   - companion provider-init storage is production-appropriate.

## Kill Switch

Primary kill switch: set `GOOGLE_OAUTH_ENABLED` to disabled in the `api.auth` runtime configuration and restart/reload according to deployment practice.

Secondary gates:

- Set `GOOGLE_OAUTH_PROVISIONING_MODE` to `disabled`.
- Disable provider-init issuance in `magic-worlds-api`.
- Leave local password login, refresh, validate, logout, and API-key lifecycle available.

## Staging `link_only` Checklist

- Google OAuth enabled only for controlled localhost/staging config values outside this doc.
- `GOOGLE_OAUTH_SCOPES` is exactly `openid email`.
- Redirect URI allowlist contains only exact callback URIs for the environment.
- Return-origin allowlist contains only exact frontend origins for the environment.
- Provider-init redeem URL/token are configured through secret management.
- Existing local session recent-reauth works before link.
- Linking emits `act-cat-073` with redacted details.
- Callback audit rows use `auth_method='oauth'` and redact `code`, `state`, token material, provider-init token, and strict hashes.

## Auto-create Enablement Gates

Do not enable `auto_create` or `both` until:

1. provider-init reliably includes server-side target project and authorized user-group binding,
2. `user_external_accounts` migration validates,
3. pending local `user_emails` creation is verified and Google `email_verified` does not activate local email,
4. project access denial is monitored,
5. Google-only unlink refusal is tested,
6. companion provider-init store is not process-local memory in a multi-instance production topology, or sticky routing/shared storage is in place.

## JWKS Outage / Key Rotation

Expected behavior:

- JWKS cache honors provider cache directives but is capped at `3600` seconds.
- On `kid` miss, the verifier refetches once.
- On second miss or fetch failure, OAuth fails closed with neutral `EXT_8xxx` posture.
- Existing local sessions and password login remain unaffected.

Operational response:

1. Confirm the failure is limited to `/auth/google/*`.
2. Check recent `GOOGLE_OAUTH_ID_TOKEN_REJECTED` and token-exchange activity counts.
3. Keep local auth online.
4. If outage persists, use the kill switch instead of weakening validation.

## Google Client Secret Rotation

1. Create a new Google OAuth credential in the provider console.
2. Update secret management for `GOOGLE_OAUTH_CLIENT_ID` and `GOOGLE_OAUTH_CLIENT_SECRET` as an atomic deploy unit if the client ID changes.
3. Keep redirect URI allowlists exact and environment-driven.
4. Restart/reload `api.auth` workers.
5. Run fake/local smoke and one controlled non-production callback.
6. Revoke the old provider credential only after successful verification.

Never print the old or new secret value. Evidence should say only whether the key is present and which target class was checked.

## Redis Namespace Cleanup

During rollback or incident cleanup, allow short TTL keys to expire naturally when possible. If immediate cleanup is required in a local/test environment, target only OAuth namespaces:

- `google_oauth_state:*`
- `google_oauth_state_consumed:*`
- `google_oauth_link:*`
- `google_oauth_reauth:*`
- `google_oauth_jwks:*`
- `google_oauth_rate:*`
- `provider_init_redeem:*`

Do not clear unrelated `session:*`, `refresh_family:*`, or user-session namespaces unless incident response explicitly requires local auth revocation.

## Rollback

Preferred rollback is non-destructive:

1. Disable Google OAuth in `api.auth`.
2. Disable provider-init issuance in `magic-worlds-api`.
3. Let OAuth Redis keys expire or clear only OAuth namespaces in local/test.
4. Keep `user_external_accounts`, audit rows, and activity rows for evidence preservation.
5. Keep local sessions unless specific affected users require `revoke_user_auth_state(...)`.

Destructive rollback must refuse when live or historical external-account rows, OAuth audit rows, or Google OAuth activity rows exist. Use the migration rollback dry-run first and expect refusal-first posture.

## Monitoring Signals

- `GOOGLE_OAUTH_PROVIDER_INIT_REJECTED` spike: companion token replay/expiry/routing/config issue.
- `GOOGLE_OAUTH_STATE_REJECTED` spike: replay, expired state, Redis issue, browser callback repeats.
- `GOOGLE_OAUTH_ID_TOKEN_REJECTED` spike: JWKS, issuer/audience, Workspace `hd`, fake-provider drift.
- `GOOGLE_OAUTH_LOGIN_DENIED` spike: provisioning, project access, consumer policy, or email collision.
- `EXT_8030`: rate limit pressure.

## Companion In-memory Store Limitation

The current companion provider-init implementation stores tokens in memory. That means:

- process-local only,
- cleared on restart,
- replay state lost on restart,
- multi-instance traffic requires sticky routing or a shared store.

Do not treat the in-memory companion store as production-ready for stateless multi-replica deployments.

## Known Residual Verification Caveats

- Full-stack e2e `/auth/validate` caveat remains until the local test DB migration/session-validation path accepts OAuth-issued synthetic local tokens.
- Trigger privilege caveat remains on local MySQL when binary logging requires elevated trigger creation privileges for the test user.
- Pre-existing admin project-auth failures are separate from Google OAuth rollout and should not block docs completion by themselves.
