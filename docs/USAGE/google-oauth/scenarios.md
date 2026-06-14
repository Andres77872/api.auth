# Google OAuth Scenarios

These scenarios describe expected behavior. They are not a manual for bypassing the provider-init boundary. Use only fake/local placeholders in examples.

## Returning Linked User

**Given** an active `user_external_accounts` row exists for provider `google` and the HMAC of Google's `sub`.

**When** the callback validates the ID token and the provider-sub HMAC matches.

**Then** `api.auth` resolves the active local consumer, refreshes last-seen/masked snapshots, checks access to the provider-init-bound project, issues the existing local `LoginResponse`, and emits `GOOGLE_OAUTH_LOGIN_SUCCEEDED`.

The Google email does not need to match the current activated local email.

## Auto-create Consumer

**Given** provisioning mode is `auto_create` or `both`, provider-init includes a valid server-side user-group binding, and no provider-sub link exists.

**When** Google returns a valid consumer identity without Workspace `hd`.

**Then** `api.auth` may create a local consumer, assign the provider-init-bound group, create a pending local email row if an email is available, create the external-account link, verify project access, and issue the normal local session.

Auto-create must fail closed if the provider-init binding lacks the required group. There is no client-selected group and no silent default group grant.

## Email Collision / Account-Takeover Blocked

**Given** Google returns an email that matches an existing local activated email, but the provider-sub is not linked.

**When** callback identity resolution runs.

**Then** `api.auth` must not auto-link by email alone. It returns a neutral denial/link-required posture, records only redacted details, and requires credential-first local proof before linking.

No public response may reveal whether the email matched a local account.

## Workspace `hd` Denial

**Given** the Google ID token contains a hosted-domain `hd` claim.

**When** the consumer-only policy evaluates the token.

**Then** the callback rejects it with neutral `EXT_8xxx` posture, emits ID-token rejection activity, and issues no local session.

This system is consumer-only for Google OAuth. Root, admin, platform, Workspace, and non-consumer OAuth login are unsupported and intentionally indistinguishable from ineligible/not found outcomes.

## Project Access Denial

**Given** Google identity succeeds and a local consumer is resolved.

**When** the consumer lacks group-derived access to the project bound inside provider-init/OAuth state.

**Then** `api.auth` denies local session issuance. It must not auto-pick another project and must not disclose which project/group/access-chain element failed.

Provider-init is not a privilege grant.

## Google-only Unlink Refusal

**Given** a consumer has Google as the only usable authentication method.

**When** the consumer tries `DELETE /auth/google/unlink`.

**Then** unlink is refused with `OAUTH_PASSWORD_REQUIRED_FOR_UNLINK` / `EXT_8029` posture until fallback local authentication exists. No raw provider subject or email is returned.

## Provider Outage

**Given** Google token exchange, JWKS fetch, or ID-token validation cannot be completed safely.

**When** callback processing reaches the provider-dependent step.

**Then** the OAuth path fails closed with a neutral external/provider error. Existing local password login, refresh, logout, API-key lifecycle, and local sessions remain available.

## Provider-init Replay

**Given** a `provider_init_token` was already redeemed or expired.

**When** `/auth/google/start` receives it again.

**Then** no OAuth state is created, no Google redirect is produced, and only a redacted provider-init rejection is audited/activity-logged.

## Known Verification Caveats

- Full-stack e2e callback success is present, but `/auth/validate` on the synthetic OAuth-issued local token remains a known test caveat until the test DB migration/session-validation path is resolved.
- Trigger install can be privilege-limited in local MySQL with binary logging; source/bootstrap validation still covers trigger SQL.
- Pre-existing admin project-auth failures are not caused by Google OAuth docs and remain separate follow-up work.
