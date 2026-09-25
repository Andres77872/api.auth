# Google OAuth troubleshooting

Problems specific to the `/auth/google/*` aliases, the provider-init handshake, the
`GOOGLE_OAUTH_*` configuration and Google's ID tokens. Everything else — state replay,
redirect mismatches under the database source, provisioning denials, link and unlink
errors — is in the [OAuth troubleshooting](../oauth/troubleshooting.md) page.

Never copy Google authorization codes, state, nonce, code verifier, ID, access or refresh
tokens, provider-init tokens, raw Google subjects or e-mails, `project_hash` or
`user_group_hash` into tickets, logs, docs or chat. Use the `correlation_id`,
fingerprints, activity ids and masked snapshots. Filter the activity log by
`google_oauth_*` for alias requests.

## Quick triage

| Symptom | Likely cause | Safe action |
| --- | --- | --- |
| `/auth/google/start` `403` `EXT_8011` | `GOOGLE_OAUTH_ENABLED` off (environment source), or no usable `google` binding with `init_mode: legacy_redeem` (database source) | Check the switch, or the binding's readiness and redeem bridge. |
| `/auth/google/start` `503` `EXT_8010` | `GOOGLE_OAUTH_CLIENT_ID` missing | Set it through secret management. |
| Every Google route answers `500` (environment source) | The Google configuration fails to load: `GOOGLE_OAUTH_SCOPES` not exactly `openid email`, a TTL or leeway out of range, or an unknown provisioning mode | Fix the value; check key names only, never print values. |
| `/auth/google/start` `401` `EXT_8012` | Redemption failed; `google_oauth_provider_init_rejected` carries the reason | See [Provider-init redemption failures](#provider-init-redemption-failures). |
| `/auth/google/start` `400` `EXT_8013` | The redirect URI or return origin is not on the allow-list, or matches more than one binding | See [Redirect and return-origin mismatch](#redirect-and-return-origin-mismatch). |
| Callback `401` `EXT_8019` or `EXT_8020`–`EXT_8022` | ID token rejected: wrong client id, issuer override, clock skew, or a JWKS problem | See [JWKS `kid` miss or outage](#jwks-kid-miss-or-outage). |
| Callback `401` `EXT_8023` | The Workspace `hd` is not on the hosted-domain allow-list | Add the domain, or empty the list to allow every account. |
| Callback `502` `EXT_8018` | Wrong client secret, a code already used or expired, a redirect URI that differs at the token endpoint, or a Google outage | Test the secret; relay each callback once; never retry the same code against Google. |
| Redis unavailable | State, init-token and rate-limit controls cannot be enforced | OAuth fails closed (`401` `EXT_8014` or `429`). Restore Redis; there is no in-memory fallback in `api.auth`. |

## Provider-init redemption failures

`reason` recorded with `google_oauth_provider_init_rejected`:

| Reason | Cause | Fix |
| --- | --- | --- |
| `provider_init_not_configured` | No redeem URL or token (`PROVIDER_INIT_REDEEM_URL`, `PROVIDER_INIT_REDEEM_TOKEN`, or the binding's bridge) | Configure both. |
| `provider_init_redeem_url_unsafe` | The redeem URL is plain `http` to a non-local host, or contains credentials | Use `https://`; plain `http://` only to `localhost`, `127.0.0.1` or `::1`. |
| `provider_init_timeout_or_unavailable` | The companion did not answer within 5 seconds, or the connection failed | Check the companion and the network path. |
| `provider_init_http_rejected` | The companion answered non-`2xx` (unknown, expired or replayed token, wrong bearer), or a redirect | Check the companion's logs by token fingerprint; mint a new token. |
| `provider_init_malformed_response` | The body was not a JSON object | Fix the companion's redeem endpoint. |
| `provider_init_inactive`, `provider_init_signature_mismatch` | The companion marked the token inactive or invalid | Mint a new token. |
| `provider_init_provider_mismatch`, `provider_init_audience_mismatch`, `provider_init_purpose_invalid` | The redeemed binding names another provider, another audience, or an unknown purpose | Fix the companion's issuance. |
| `provider_init_binding_missing_project` | No `project_hash` in the answer | Fix the companion's issuance. |
| `provider_init_return_origin_denied`, `provider_init_return_origin_mismatch` | The redeemed origin is not in `PROVIDER_INIT_RETURN_ORIGINS` (or the binding's origins), or differs from the one in the start request | Align the origin lists; `http://localhost:3000` and `http://127.0.0.1:3000` are different origins. |
| `provider_init_expired_or_ttl_invalid` | No `expires_in`/`expires_at`, already expired, or more than `600` seconds left | Issue tokens with a lifetime of at most `600` seconds. |
| `provider_init_project_not_bound`, `provider_init_group_not_bound` | Database source: the redeemed project or group differs from the binding's | Re-import with the project and group the companion actually sends, or fix the companion. |
| `provider_init_redeem_failed` | Any other failure while redeeming | Check `api.auth` logs by correlation id. |

A companion with an in-memory token store loses every token on restart and cannot share
them between replicas: a browser routed to another companion instance fails redemption.
Use sticky routing or a shared store, or move to `/auth/oauth/init`.

## Redirect and return-origin mismatch

Allow-list checks are exact string matches. Trailing slashes, ports, scheme and path
differences all count, and `localhost` is not `127.0.0.1`. Under the environment source
the lists are `GOOGLE_OAUTH_REDIRECT_URIS` and `GOOGLE_OAUTH_RETURN_ORIGINS`; when the
start request omits them, the first entry is used. The redirect URI must also be
registered identically in the Google Cloud console. Under the database source the lists
are the binding's allow-list rows. Keep production values in deployment configuration,
not in docs or smoke files.

## JWKS `kid` miss or outage

The verifier is built to:

1. cache Google's JWKS in process memory, honoring Google's cache headers up to the cap
   (`GOOGLE_OAUTH_JWKS_CACHE_TTL_SECONDS` for the environment connection,
   `OAUTH_JWKS_CACHE_TTL_SECONDS` for database connections; at most `3600` seconds);
2. refetch once when the token's `kid` is not in the cached set;
3. fail closed if the `kid` is still missing or the fetch fails (`401` `EXT_8019`);
4. leave password login and existing sessions untouched.

During an outage use the kill switch rather than weakening validation:
`GOOGLE_OAUTH_ENABLED=false` under the environment source, or the catalog, connection or
binding switches under the database source. The rollout, kill switch and rollback procedures are in the
[Google OAuth runbook](../../RUNBOOKS/google-oauth.md).

## Neutral public errors

Most failures answer one of three messages: "OAuth authentication could not be
completed.", "OAuth provider is not available." or "External identity action could not
be completed." This is deliberate: the answer never reveals whether an account exists,
who owns a Google identity, the state of a local e-mail, project membership or strict
scope. Read `error.code` and the activity log instead.
