# Google OAuth scenarios

Expected behavior for Google sign-in cases. They apply to `/auth/google/*` and to the
`google` connection under `/auth/oauth/*` alike, since both run the same pipeline; where
the alias differs, it is said. Use only fake or localhost values in examples.

## Returning linked user

An active `user_external_accounts` row exists for namespace `google` and the HMAC of the
user's Google `sub`. After the ID token verifies, `api.auth` finds that user, refreshes
the last-seen time and masked e-mail snapshot, checks the user's group-derived access to
the project bound at start, and returns the ordinary `LoginResponse`
(`google_oauth_login_succeeded` on the alias, `oauth_login_succeeded` otherwise). The
Google e-mail does not need to match any local e-mail.

## New user with auto-create

Provisioning mode is `auto_create` or `both` and no link exists. `api.auth` creates a
consumer with an unusable random password, adds it to the provisioning group, stores the
Google e-mail as a **pending**, non-primary local email, links the identity and signs the
user in. The provisioning group is:

- under `OAUTH_CONFIG_SOURCE=env` (alias start), the `user_group_hash` in the redeemed
  provider-init token;
- under `OAUTH_CONFIG_SOURCE=db`, the binding's default user group; a redeemed group, if
  any, must equal it.

Without a usable group the sign-in is refused (`401` `EXT_8024`, `sub_reason`
`no_bound_user_group` or `user_group_not_found`). There is no client-selected group and no
silent default. With `/auth/oauth/init` under the environment source there is never a
group, so new users cannot be created that way.

## E-mail already used by a local account

The Google identity is not linked, but its e-mail belongs to a local account. `api.auth`
never links or merges by e-mail. Because Google verifies e-mail, the answer is `409`
`EXT_8032`: the user signs in with their existing method and links Google from the
account (`POST /auth/google/link/start` or `POST /auth/oauth/google/link/start`). The
message reveals the match only to someone who just proved control of that verified
address at Google.

## Workspace `hd` not allowed

A hosted-domain allow-list is configured (`GOOGLE_OAUTH_ALLOWED_HOSTED_DOMAINS`, or
`restrictions.hosted_domains` on a database connection) and the ID token's `hd` is not on
it. The callback answers `401` `EXT_8023`, records an ID-token rejection and issues no
session. With an empty list (the default) or `*`, every Google account may sign in;
consumer Gmail has no `hd` and is always allowed.

## No access to the bound project

Google identity succeeds and the user is resolved, but the user's groups do not reach the
project fixed at start. The answer is `403` `EXT_8025`; no other project is picked and the
failing link of the access chain is not disclosed. A provider-init token is not a
privilege grant. Under the database source a binding with `existing_user_policy:
join_default_group` adds such a user to the default group first.

## Non-consumer account

The linked account is a root or admin user, or inactive. The sign-in is refused with the
neutral `401` `EXT_8024`, indistinguishable from other refusals.

## Unlink with Google as the only credential

A consumer created by auto-create has no usable password. `DELETE /auth/google/unlink`
answers `409` `EXT_8029` until the user sets a password. No subject or e-mail is returned.
A successful unlink revokes every session of the user.

## Google or JWKS outage

The token exchange, a JWKS fetch or ID-token verification cannot complete. The flow fails
closed: `502` `EXT_8018` for the exchange, `401` `EXT_8019` for an unverifiable token
(including a `kid` still missing after one refetch). Nothing is weakened; password login,
refresh, logout, API keys and existing sessions keep working. If the outage persists, use
the kill switch (see the [runbook](../../RUNBOOKS/google-oauth.md)).

## Provider-init replay

The companion already redeemed or expired the token, so its redeem endpoint refuses it.
`/auth/google/start` answers `401` `EXT_8012`, creates no state, produces no redirect, and
records `google_oauth_provider_init_rejected` with the reason
(`provider_init_http_rejected` or `provider_init_inactive`, depending on how the
companion answers). Single use is the companion's job; `api.auth` redeems once per start
request.
